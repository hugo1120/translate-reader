import csv
import json
import re
import shutil
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from time import perf_counter

from translate_manga.cli.cache import BatchStageCache
from translate_manga.cli.debug_artifacts import BatchDebugArtifactWriter
from translate_manga.cli.quality_review import read_quality_review_entries
from translate_manga.config.paths import find_project_root
from translate_manga.config.settings import (
    load_settings,
    resolve_multimodal_layout_config,
    resolve_ocr_config,
    resolve_path_value,
    resolve_pipeline_config,
    resolve_translation_config,
    resolve_translation_prompt_config,
)
from translate_manga.core.context.manga_context import load_or_generate_manga_context
from translate_manga.core.natural_sort import natural_sort_key
from translate_manga.core.multimodal_layout import apply_multimodal_layout_assist
from translate_manga.core.styles import resolve_style_profile
from translate_manga.core.pipeline.page_classifier import classify_preprocessed_page
from translate_manga.core.pipeline.runtime import IMAGE_EXTENSIONS, PipelineRuntime
from translate_manga.core.pipeline.service import (
    _build_translation_context,
    build_bubble_text_profiles,
    preprocess_page,
    run_page_pipeline,
    translate_texts as pipeline_translate_texts,
    translate_texts_multi_round as pipeline_translate_texts_multi_round,
)
from translate_manga.core.translation_payload import (
    build_legacy_translation_payload as _build_legacy_translation_payload,
    default_ocr_retry_state as _default_ocr_retry_state,
    empty_usage as _empty_usage,
    normalize_translation_payload as _normalize_translation_payload,
)
from translate_manga.core.pipeline.filtering import load_image_size
from translate_manga.core.translate.openai_compatible import (
    TRANSLATION_PROMPT_SIGNATURE,
    is_translation_failure_text,
)
from translate_manga.integrations.saber_loader import SaberWorkerSession


@dataclass
class PreparedPage:
    page: dict
    source_path: Path
    target_path: Path
    preprocessed_payload: dict
    classification: dict | None = None
    translated_texts: list[str] | None = None
    translation_payload: dict | None = None
    translation_seconds: float = 0.0


def translate_texts(texts, model, base_url, api_key=None, context_snapshot=None):
    return pipeline_translate_texts(
        texts=texts,
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_snapshot=context_snapshot,
    )


_DEFAULT_TRANSLATE_TEXTS = translate_texts
_LONG_NARRATION_STRONG_BREAK_RE = re.compile(r"(?<=[。！？；!?;])")
_LONG_NARRATION_SOFT_BREAK_RE = re.compile(r"(?<=[，、：,:])")
_LONG_NARRATION_ASCII_PUNCT_TRANSLATION = str.maketrans({
    ",": "，",
    ":": "：",
    ";": "；",
    "!": "！",
    "?": "？",
    "(": "（",
    ")": "）",
})
_CJK_PERIOD_RE = re.compile(r"(?<=[\u3400-\u9fff）】》」』])\.(?=[\u3400-\u9fff（【《「『]|$)")
_JAPANESE_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\uff66-\uff9f]")
_LATIN_WORD_RE = re.compile(r"(?<![A-Za-z])([A-Za-z][A-Za-z'-]{3,})(?![A-Za-z])")
_KNOWN_JAPANESE_TERM_TRANSLATIONS = {
    "マスどり": "量斗",
}
_KNOWN_JAPANESE_TERM_ROMAJI = {
    "マスどり": re.compile(r"(?<![A-Za-z])masudori(?![A-Za-z])", re.IGNORECASE),
}
_KNOWN_JAPANESE_SOUND_EFFECT_TRANSLATIONS = {
    "シュル": "嗖",
    "ラスル": "嗖",
    "ワウン": "汪",
    "アウッ": "嗷",
    "ビーッ": "哔",
}
_KNOWN_JAPANESE_SOUND_EFFECT_FORCE_TRANSLATIONS = {
    "アアッミ": "啊啊",
}
_KNOWN_JAPANESE_SOUND_EFFECT_TRANSLITERATIONS = {
    "ラスル": ("拉斯尔", "拉斯鲁"),
}
_LONG_NARRATION_PARAGRAPH_MARKERS = (
    "因此",
    "此外",
    "另外",
    "然而",
    "不过",
    "总之",
    "当然",
    "与此同时",
    "另一方面",
    "于是",
)


def translate_texts_multi_round(texts, model, base_url, api_key=None, context_snapshot=None):
    if translate_texts is not _DEFAULT_TRANSLATE_TEXTS:
        attempts = [
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
                "api_key": api_key,
                "context_snapshot": context_snapshot,
            },
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
                "context_snapshot": context_snapshot,
            },
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
            },
        ]
        last_error = None
        translated = None
        for kwargs in attempts:
            try:
                translated = translate_texts(**kwargs)
                break
            except TypeError as error:
                last_error = error
                error_text = str(error)
                if "unexpected keyword argument" not in error_text and "required keyword-only argument" not in error_text:
                    raise
        if translated is None:
            raise last_error
        return _build_legacy_translation_payload(translated)
    return pipeline_translate_texts_multi_round(
        texts=texts,
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_snapshot=context_snapshot,
    )


class NullBatchDebugArtifactWriter:
    def record_page(self, **kwargs):
        return {}

    def finish(self, summary=None, records=None, run_options=None):
        return None


def format_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    remain = int(seconds % 60)
    return f"{minutes:02d}:{remain:02d}"


class BatchProgressReporter:
    def __init__(self, stream=None):
        import sys

        self.stream = stream or sys.stdout
        self._has_progress_line = False

    def update(self, current_index, total_count, current_name, succeeded, skipped, failed, elapsed_seconds):
        message = (
            f"[{current_index}/{total_count}] current={current_name} "
            f"ok={succeeded} skip={skipped} fail={failed} elapsed={format_seconds(elapsed_seconds)}"
        )
        self.stream.write(f"\r{message}")
        self.stream.flush()
        self._has_progress_line = True

    def log(self, message):
        if self._has_progress_line:
            self.stream.write("\n")
        self.stream.write(f"{message}\n")
        self.stream.flush()
        self._has_progress_line = False

    def finish(self, total_count, succeeded, skipped, failed, elapsed_seconds):
        self.log(
            f"DONE total={total_count} ok={succeeded} skip={skipped} fail={failed} elapsed={format_seconds(elapsed_seconds)}"
        )


def scan_input_images(input_dir):
    directory = Path(input_dir)
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"Input folder not found: {directory}")

    return sorted(
        [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda item: natural_sort_key(item.name),
    )


def _resolve_numeric_output_width(image_paths):
    widths = [len(path.stem) for path in image_paths if path.stem.isdigit()]
    return max(widths) if widths else None


def _normalize_output_stem(source_path, numeric_width=None):
    stem = Path(source_path).stem
    if numeric_width and stem.isdigit():
        return stem.zfill(int(numeric_width))
    return stem


def build_output_path(source_path, output_dir, numeric_width=None):
    stem = _normalize_output_stem(source_path, numeric_width=numeric_width)
    return Path(output_dir) / f"{stem}.translated.png"


def find_missing_output_page_names(image_paths, output_dir, numeric_width=None):
    image_paths = list(image_paths or [])
    if numeric_width is None:
        numeric_width = _resolve_numeric_output_width(image_paths)
    missing = set()
    for image_path in image_paths:
        source_path = Path(image_path)
        if not build_output_path(source_path, output_dir, numeric_width=numeric_width).exists():
            missing.add(source_path.name)
    return missing


_TRANSLATION_TEXT_FILE_SUFFIXES = (
    ".draft.translation.txt",
    ".contextual.translation.txt",
    ".final.translation.txt",
    ".translation.txt",
)


def _translation_text_source_stem(path):
    name = Path(path).name
    for suffix in _TRANSLATION_TEXT_FILE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def find_translation_failure_text_page_names(image_paths, output_dir, existing_debug_page_names=None):
    texts_root = Path(output_dir) / "_debug" / "texts"
    if not texts_root.exists():
        return set()

    image_name_by_stem = {Path(image_path).stem: Path(image_path).name for image_path in image_paths or []}
    existing_debug_page_names = set(existing_debug_page_names or [])
    names = set()
    for text_path in sorted(texts_root.glob("*.translation.txt"), key=lambda item: natural_sort_key(item.name)):
        source_stem = _translation_text_source_stem(text_path)
        if not source_stem:
            continue
        source_name = image_name_by_stem.get(source_stem)
        if not source_name or source_name in existing_debug_page_names:
            continue
        try:
            content = text_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(is_translation_failure_text(line) for line in content.splitlines()):
            names.add(source_name)
    return names


def _load_retry_review_page_names(output_dir, image_paths=None, numeric_width=None, include_quality_review=False):
    debug_root = Path(output_dir) / "_debug"
    failed_tsv_path = debug_root / "failed-translations.tsv"
    names = set()
    page_source_names = set()

    if failed_tsv_path.exists():
        with failed_tsv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                source_name = str((row or {}).get("sourceName") or "").strip()
                if source_name:
                    names.add(source_name)

    review_pages_path = debug_root / "review-pages.txt"
    if review_pages_path.exists():
        for line in review_pages_path.read_text(encoding="utf-8").splitlines():
            source_name = line.split("\t", 1)[0].strip()
            if source_name:
                names.add(source_name)

    if include_quality_review:
        for entry in read_quality_review_entries(output_dir):
            source_name = str((entry or {}).get("sourceName") or "").strip()
            if source_name:
                names.add(source_name)

    pages_root = debug_root / "pages"
    if pages_root.exists():
        for page_json_path in pages_root.glob("*.json"):
            try:
                record = json.loads(page_json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source_name = str(record.get("sourceName") or "").strip()
            if source_name:
                page_source_names.add(source_name)
            if _debug_record_needs_retry(record):
                if source_name:
                    names.add(source_name)

    names.update(
        find_translation_failure_text_page_names(
            image_paths or [],
            output_dir,
            existing_debug_page_names=page_source_names,
        )
    )
    names.update(find_missing_output_page_names(image_paths or [], output_dir, numeric_width=numeric_width))
    return names


def _debug_record_needs_retry(record):
    if not isinstance(record, dict):
        return False
    if record.get("needsReview"):
        return True
    if str(record.get("status") or "").strip().lower() == "failed":
        return True

    reasons = []
    reasons.extend(record.get("reviewReasons") or [])
    ocr_retry = record.get("ocrRetry")
    if isinstance(ocr_retry, dict):
        reasons.extend(ocr_retry.get("reasons") or [])
    translation = record.get("translation")
    if isinstance(translation, dict):
        translation_retry = translation.get("ocrRetry")
        if isinstance(translation_retry, dict):
            reasons.extend(translation_retry.get("reasons") or [])

    if any(str(reason or "").strip() == "translation_failed" for reason in reasons):
        return True

    translated_texts = list(record.get("translatedTexts") or [])
    if isinstance(translation, dict):
        translated_texts.extend(translation.get("translatedTexts") or [])
        for round_payload in translation.get("rounds") or []:
            if isinstance(round_payload, dict):
                translated_texts.extend(round_payload.get("translatedTexts") or [])
    return any(is_translation_failure_text(text) for text in translated_texts)


def _load_existing_debug_records(output_dir):
    pages_root = Path(output_dir) / "_debug" / "pages"
    records = {}
    if not pages_root.exists():
        return records

    for page_json_path in pages_root.glob("*.json"):
        try:
            record = json.loads(page_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_name = str(record.get("sourceName") or "").strip()
        if source_name:
            records[source_name] = record
    return records


def _debug_record_translated_texts(record):
    translated_texts = list((record or {}).get("translatedTexts") or [])
    translation = (record or {}).get("translation")
    if isinstance(translation, dict):
        translated_texts.extend(translation.get("translatedTexts") or [])
        for round_payload in translation.get("rounds") or []:
            if isinstance(round_payload, dict):
                translated_texts.extend(round_payload.get("translatedTexts") or [])
    normalized = []
    for text in translated_texts:
        value = str(text or "").strip()
        if value and not is_translation_failure_text(value) and value not in normalized:
            normalized.append(value)
    return normalized


def _debug_record_to_context_result(record):
    if not isinstance(record, dict) or _debug_record_needs_retry(record):
        return None

    translated_texts = _debug_record_translated_texts(record)
    if not translated_texts:
        return None

    original_texts = [str(text or "").strip() for text in (record.get("originalTexts") or [])]
    bubble_states = []
    max_count = max(len(original_texts), len(translated_texts))
    for index in range(max_count):
        original = original_texts[index] if index < len(original_texts) else ""
        translated = translated_texts[index] if index < len(translated_texts) else ""
        if not translated:
            continue
        bubble_states.append({"originalText": original, "translatedText": translated})

    if not bubble_states:
        return None
    return {
        "manualEdited": False,
        "originalTexts": original_texts,
        "translatedTexts": translated_texts,
        "bubbleStates": bubble_states,
        "bubbles": bubble_states,
    }


def _seed_runtime_context_from_debug(runtime, all_pages, debug_records_by_source, retry_page_names):
    retry_page_names = set(retry_page_names or set())
    for page in all_pages:
        source_name = str(page.get("fileName") or "").strip()
        if not source_name or source_name in retry_page_names:
            continue
        result = _debug_record_to_context_result((debug_records_by_source or {}).get(source_name))
        if result is not None:
            runtime.save_result(page["id"], result)


def _debug_record_to_preprocessed_payload(record):
    if not isinstance(record, dict):
        return None
    payload = record.get("preprocessedPayload")
    if not isinstance(payload, dict):
        return None
    if not payload.get("bubbleCoords"):
        return None

    normalized = {
        "bubbleCoords": payload.get("bubbleCoords") or [],
        "bubblePolygons": payload.get("bubblePolygons") or [],
        "autoDirections": payload.get("autoDirections") or [],
        "textlinesPerBubble": payload.get("textlinesPerBubble") or [],
        "bubbleColors": payload.get("bubbleColors") or [],
        "multimodalLayout": payload.get("multimodalLayout"),
        "bubbleLayoutHints": payload.get("bubbleLayoutHints") or [],
        "originalTexts": payload.get("originalTexts") or record.get("originalTexts") or [],
        "ocrResults": payload.get("ocrResults") or [],
        "rawMask": payload.get("rawMask"),
    }
    timings = payload.get("timings")
    if isinstance(timings, dict):
        normalized["timings"] = timings
    return normalized


def _normalize_ocr_engine_name(value):
    return str(value or "").strip().lower()


def _preprocessed_payload_matches_ocr_options(preprocessed_payload, ocr_options):
    if not isinstance(preprocessed_payload, dict):
        return False

    expected_engines = {
        _normalize_ocr_engine_name((ocr_options or {}).get("engine")),
        _normalize_ocr_engine_name((ocr_options or {}).get("secondary_engine")),
    }
    expected_engines = {engine for engine in expected_engines if engine}
    if not expected_engines:
        return True

    ocr_results = preprocessed_payload.get("ocrResults") or []
    if not ocr_results:
        return True

    for result in ocr_results:
        if not isinstance(result, dict):
            continue
        observed_engines = {
            _normalize_ocr_engine_name(result.get("engine")),
            _normalize_ocr_engine_name(result.get("primaryEngine")),
        }
        observed_engines = {engine for engine in observed_engines if engine}
        if observed_engines and observed_engines.isdisjoint(expected_engines):
            return False
    return True


def _merge_context_items(base_items, extra_items):
    merged = list(base_items or [])
    for item in extra_items or []:
        value = str(item or "").strip()
        if value and not is_translation_failure_text(value) and value not in merged:
            merged.append(value)
    return merged


def _augment_context_with_debug_neighbors(context_snapshot, all_pages, current_page_id, debug_records_by_source, retry_page_names, window=3):
    snapshot = dict(context_snapshot or {})
    page_ids = [page.get("id") for page in all_pages]
    if current_page_id not in page_ids:
        return snapshot

    current_index = page_ids.index(current_page_id)
    start_index = max(0, current_index - int(window))
    end_index = min(len(all_pages), current_index + int(window) + 1)
    retry_page_names = set(retry_page_names or set())
    extra_translations = []
    glossary = dict(snapshot.get("glossary") or {})

    for page in all_pages[start_index:end_index]:
        if page.get("id") == current_page_id:
            continue
        source_name = str(page.get("fileName") or "").strip()
        if not source_name or source_name in retry_page_names:
            continue
        result = _debug_record_to_context_result((debug_records_by_source or {}).get(source_name))
        if result is None:
            continue
        for bubble in result.get("bubbleStates") or []:
            original = str(bubble.get("originalText") or "").strip()
            translated = str(bubble.get("translatedText") or "").strip()
            if not translated or is_translation_failure_text(translated):
                continue
            extra_translations.append(translated)
            if original and original not in glossary:
                glossary[original] = translated

    snapshot["confirmedTranslations"] = _merge_context_items(snapshot.get("confirmedTranslations") or [], extra_translations)
    snapshot["glossary"] = glossary
    return snapshot


def _build_pages(image_paths):
    pages = []
    for index, image_path in enumerate(image_paths, start=1):
        pages.append(
            {
                "id": f"page-{index:04d}",
                "pageIndex": index,
                "fileName": image_path.name,
                "sourcePath": str(image_path),
                "translatedPath": None,
                "status": "idle",
                "cacheKey": str(uuid.uuid4()),
            }
        )
    return pages


def _default_cache_root():
    return find_project_root(__file__) / ".cache" / "translate_manga_cli"


def _build_style_ocr_config(ocr_config, style_profile=None):
    resolved = dict(ocr_config or {})
    style_profile = style_profile or {}
    if style_profile.get("source_language"):
        resolved["source_language"] = style_profile["source_language"]
    if style_profile.get("reading_order"):
        resolved["reading_order"] = style_profile["reading_order"]
    for key, value in ((style_profile.get("ocr") or {}).items()):
        resolved[key] = value
    return resolved


def _is_multimodal_layout_config_ready(config):
    return all(str((config or {}).get(key) or "").strip() for key in ("model", "base_url", "api_key"))


def _build_preprocess_signature(settings, style_profile=None):
    payload = {
        "version": "preprocess-v1",
        "ocr": _build_style_ocr_config(resolve_ocr_config(settings=settings), style_profile=style_profile),
        "reading_order": (style_profile or {}).get("reading_order"),
    }
    layout_assist = (style_profile or {}).get("layout_assist")
    if layout_assist:
        multimodal_config = resolve_multimodal_layout_config(
            settings=settings,
            enabled_override=bool(layout_assist.get("enabled")),
        )
        payload["layout_assist"] = dict(layout_assist)
        payload["multimodal_layout"] = {
            "enabled": bool(multimodal_config.get("enabled")),
            "configured": _is_multimodal_layout_config_ready(multimodal_config),
            "model": multimodal_config.get("model"),
            "base_url": multimodal_config.get("base_url"),
            "max_edge": multimodal_config.get("max_edge"),
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_translation_quality(value):
    quality = str(value or "high").strip().lower()
    return quality if quality in {"fast", "balanced", "high"} else "high"


def _build_translation_signature(settings, style_profile=None, manga_context_payload=None, translation_quality=None):
    prompt_profile = (style_profile or {}).get("prompt_profile", "default")
    prompt_config = resolve_translation_prompt_config(settings=settings, prompt_profile=prompt_profile)
    if translation_quality is None:
        translation_quality = resolve_pipeline_config(settings=settings).get("translation_quality", "high")
    payload = {
        "version": TRANSLATION_PROMPT_SIGNATURE,
        "promptProfile": prompt_profile,
        "promptConfig": prompt_config,
        "translationQuality": _normalize_translation_quality(translation_quality),
        "mangaContext": str((manga_context_payload or {}).get("content") or "").strip(),
    }
    digest = sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{TRANSLATION_PROMPT_SIGNATURE}:{digest}"


def _apply_layout_assist_to_preprocessed(source_path, preprocessed_payload, *, style_profile=None, settings=None):
    layout_assist = (style_profile or {}).get("layout_assist") or {}
    if layout_assist.get("type") != "multimodal" or not layout_assist.get("enabled"):
        return preprocessed_payload
    multimodal_config = resolve_multimodal_layout_config(
        settings=settings,
        enabled_override=True,
    )
    cached_layout = (
        preprocessed_payload.get("multimodalLayout")
        if isinstance(preprocessed_payload, dict) and isinstance(preprocessed_payload.get("multimodalLayout"), dict)
        else {}
    )
    if (
        multimodal_config.get("cache_enabled", True)
        and isinstance(preprocessed_payload, dict)
        and cached_layout.get("status") == "ok"
        and "multimodalLayout" in preprocessed_payload
        and "bubbleLayoutHints" in preprocessed_payload
    ):
        return preprocessed_payload
    return apply_multimodal_layout_assist(source_path, preprocessed_payload, multimodal_config)


def _resolve_cli_settings():
    settings = load_settings()
    translation = resolve_translation_config(settings=settings)
    ocr = resolve_ocr_config(settings=settings)
    paths = settings.get("paths") or {}
    pipeline = resolve_pipeline_config(settings=settings)
    render = settings.get("render") or {}
    default_style_profile = resolve_style_profile(layout_mode=str(render.get("layout_mode") or "vertical").strip() or "vertical")
    return {
        "translation": translation,
        "ocr": ocr,
        "pipeline": pipeline,
        "render": {
            "layout_mode": str(render.get("layout_mode") or "vertical").strip() or "vertical",
        },
        "paths": {
            "input_dir": resolve_path_value(paths.get("input_dir")),
            "output_dir": resolve_path_value(paths.get("output_dir")),
            "workspace_root": resolve_path_value(paths.get("workspace_root")),
            "cache_root": resolve_path_value(paths.get("cache_root")),
        },
        "settings": settings,
        "preprocess_signature": _build_preprocess_signature(settings, style_profile=default_style_profile),
    }


def _layout_style_name(layout_mode):
    mapping = {
        "horizontal": "Style 1",
        "vertical": "Style 2",
    }
    return mapping.get(layout_mode, str(layout_mode or "vertical"))


def _style_name(style_profile, layout_mode):
    mapping = {
        "style1": "Style 1",
        "style2": "Style 2",
        "style3": "Style 3",
        "auto": "Auto",
        "style_mm": "多模态AI辅助",
    }
    return mapping.get((style_profile or {}).get("style_id"), _layout_style_name(layout_mode))


def _build_run_options(
    *,
    input_dir,
    output_dir,
    layout_mode,
    overwrite_existing,
    launch_mode,
    model,
    ocr_config,
    retry_review_pages=False,
    target_page_names=None,
    style_profile=None,
    translation_quality="high",
):
    style_profile = style_profile or resolve_style_profile(layout_mode=layout_mode)
    normalized_target_page_names = []
    for name in target_page_names or []:
        value = str(name or "").strip()
        if value and value not in normalized_target_page_names:
            normalized_target_page_names.append(value)
    return {
        "inputDir": str(Path(input_dir)),
        "outputDir": str(Path(output_dir)),
        "layoutMode": layout_mode,
        "styleId": style_profile.get("style_id"),
        "styleName": _style_name(style_profile, layout_mode),
        "layoutAssist": deepcopy(style_profile.get("layout_assist")) if style_profile.get("layout_assist") else None,
        "sourceLanguage": style_profile.get("source_language", "japanese"),
        "readingOrder": style_profile.get("reading_order"),
        "promptProfile": style_profile.get("prompt_profile", "default"),
        "translationQuality": _normalize_translation_quality(translation_quality),
        "overwriteExisting": bool(overwrite_existing),
        "retryReviewPages": bool(retry_review_pages),
        "targetPageNames": normalized_target_page_names,
        "launchMode": str(launch_mode or "args"),
        "translationModel": str(model),
        "ocrEngine": str((ocr_config or {}).get("engine") or ""),
        "secondaryOcrEngine": str((ocr_config or {}).get("secondary_engine") or ""),
    }


def _call_translate_texts_multi_round(*, texts, model, base_url, api_key=None, context_snapshot=None):
    attempts = [
        {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "context_snapshot": context_snapshot,
        },
        {
            "model": model,
            "base_url": base_url,
            "context_snapshot": context_snapshot,
        },
        {
            "model": model,
            "base_url": base_url,
        },
    ]
    last_error = None
    for kwargs in attempts:
        try:
            return translate_texts_multi_round(texts, **kwargs)
        except TypeError as error:
            last_error = error
            error_text = str(error)
            if "unexpected keyword argument" not in error_text and "required keyword-only argument" not in error_text:
                raise
    raise last_error


def _call_run_page_pipeline(
    runtime,
    page_id,
    source_path,
    *,
    model,
    base_url,
    api_key,
    preprocessed_payload,
    translated_texts,
    context_snapshot,
    saber_session,
    translation_payload,
):
    attempts = [
        {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "preprocessed_payload": preprocessed_payload,
            "translated_texts": translated_texts,
            "context_snapshot": context_snapshot,
            "saber_session": saber_session,
            "translation_payload": translation_payload,
        },
        {
            "model": model,
            "base_url": base_url,
            "preprocessed_payload": preprocessed_payload,
            "translated_texts": translated_texts,
            "context_snapshot": context_snapshot,
            "saber_session": saber_session,
            "translation_payload": translation_payload,
        },
        {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "preprocessed_payload": preprocessed_payload,
            "translated_texts": translated_texts,
            "context_snapshot": context_snapshot,
            "saber_session": saber_session,
        },
        {
            "model": model,
            "base_url": base_url,
            "preprocessed_payload": preprocessed_payload,
            "translated_texts": translated_texts,
            "context_snapshot": context_snapshot,
            "saber_session": saber_session,
        },
    ]
    last_error = None
    for kwargs in attempts:
        try:
            return run_page_pipeline(
                runtime,
                page_id,
                source_path,
                **kwargs,
            )
        except TypeError as error:
            last_error = error
            error_text = str(error)
            if "api_key" not in error_text and "translation_payload" not in error_text:
                raise
    raise last_error


def _call_preprocess_page(source_path, *, saber_session=None, ocr_options=None):
    try:
        return preprocess_page(source_path, saber_session=saber_session, ocr_options=ocr_options)
    except TypeError as error:
        error_text = str(error)
        if "unexpected keyword argument" not in error_text:
            raise
    try:
        return preprocess_page(source_path, saber_session=saber_session)
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        return preprocess_page(source_path)


def _count_page_chars(preprocessed_payload):
    texts = preprocessed_payload.get("originalTexts", []) or []
    return sum(len((text or "").strip()) for text in texts)


def _count_page_texts(preprocessed_payload):
    return len(preprocessed_payload.get("originalTexts", []) or [])


def _translation_weight(item):
    return max(1, _count_page_chars(item.preprocessed_payload) or _count_page_texts(item.preprocessed_payload) or 1)


def _assign_batch_translation_seconds(prepared_pages, elapsed_seconds):
    elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
    total_weight = sum(_translation_weight(item) for item in prepared_pages)
    if total_weight <= 0:
        return
    for item in prepared_pages:
        item.translation_seconds = elapsed_seconds * (_translation_weight(item) / total_weight)


def _with_batch_translation_timing(payload, translation_seconds):
    if not isinstance(payload, dict):
        return payload
    updated = dict(payload)
    timings = dict(updated.get("timings") if isinstance(updated.get("timings"), dict) else {})
    translation_seconds = max(0.0, float(translation_seconds or 0.0))
    if translation_seconds > 0:
        timings["translate"] = max(float(timings.get("translate", 0.0) or 0.0), translation_seconds)

    stage_total = 0.0
    for field in ("detect", "ocr", "color", "translate", "inpaint", "render"):
        try:
            stage_total += max(0.0, float(timings.get(field, 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    if stage_total > 0:
        timings["total"] = max(float(timings.get("total", 0.0) or 0.0), stage_total)
    updated["timings"] = timings
    return updated


def _has_translation_context(context_snapshot):
    if not isinstance(context_snapshot, dict):
        return False
    if context_snapshot.get("confirmedTranslations") or context_snapshot.get("glossary"):
        return True
    for key in ("mangaContext", "sourceLanguage", "promptPreset", "promptProfile", "readingOrder"):
        if str(context_snapshot.get(key) or "").strip():
            return True
    return False


def _usage_share(usage, weight, total_weight):
    usage = dict(usage or _empty_usage())
    if total_weight <= 0:
        return usage

    ratio = weight / total_weight
    return {
        "inputTokens": int(round((usage.get("inputTokens", 0) or 0) * ratio)),
        "outputTokens": int(round((usage.get("outputTokens", 0) or 0) * ratio)),
        "totalTokens": int(round((usage.get("totalTokens", 0) or 0) * ratio)),
        "estimated": bool(usage.get("estimated")),
    }


def _slice_translation_payload(payload, start, count, weight, total_weight):
    normalized = _normalize_translation_payload(payload)
    rounds = []
    for item in normalized.get("rounds") or []:
        rounds.append(
            {
                "name": item.get("name") or "final",
                "translatedTexts": list((item.get("translatedTexts") or [])[start : start + count]),
                "usage": _usage_share(item.get("usage"), weight, total_weight),
            }
        )

    return {
        "translatedTexts": list((normalized.get("translatedTexts") or [])[start : start + count]),
        "rounds": rounds,
        "tokenUsage": _usage_share(normalized.get("tokenUsage"), weight, total_weight),
        "ocrRetry": dict(normalized.get("ocrRetry") or _default_ocr_retry_state()),
    }


def _translate_batch(prepared_pages, model, base_url, api_key, context_snapshot):
    pending_pages = [item for item in prepared_pages if item.translated_texts is None]
    if not pending_pages:
        return {}

    base_translate_kwargs = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }

    translated_by_page = {}
    for item in pending_pages:
        page_plan = _build_page_translation_plan(item.preprocessed_payload, item.source_path)
        page_context_snapshot = _build_page_known_term_context(context_snapshot, page_plan)
        translate_kwargs = dict(base_translate_kwargs)
        if _has_translation_context(page_context_snapshot):
            translate_kwargs["context_snapshot"] = page_context_snapshot
        if not page_plan["texts"]:
            translated_by_page[item.page["id"]] = {
                "translatedTexts": [""] * page_plan["count"],
                "rounds": [],
                "tokenUsage": _empty_usage(),
                "ocrRetry": _default_ocr_retry_state(),
            }
            continue
        page_payload = _expand_translation_payload_to_page(
            _call_translate_texts_multi_round(texts=page_plan["texts"], **translate_kwargs),
            page_plan,
        )
        if _translation_payload_has_failure(page_payload):
            page_payload = _expand_translation_payload_to_page(
                _call_translate_texts_multi_round(texts=page_plan["texts"], **translate_kwargs),
                page_plan,
            )
        if _translation_payload_has_suspicious_latin(page_plan, page_payload, context_snapshot):
            retry_kwargs = dict(translate_kwargs)
            retry_context = _build_latin_retry_context(page_context_snapshot, page_plan, page_payload)
            if _has_translation_context(retry_context):
                retry_kwargs["context_snapshot"] = retry_context
            page_payload = _expand_translation_payload_to_page(
                _call_translate_texts_multi_round(texts=page_plan["texts"], **retry_kwargs),
                page_plan,
            )
        page_payload = _apply_known_japanese_term_translations(page_plan, page_payload)
        translated_by_page[item.page["id"]] = page_payload
    return translated_by_page


def _translation_payload_has_failure(payload):
    normalized = _normalize_translation_payload(payload)
    retry_state = normalized.get("ocrRetry") if isinstance(normalized.get("ocrRetry"), dict) else {}
    if any(str(reason or "").strip() == "translation_failed" for reason in (retry_state.get("reasons") or [])):
        return True

    texts = list(normalized.get("translatedTexts") or [])
    for round_payload in normalized.get("rounds") or []:
        if isinstance(round_payload, dict):
            texts.extend(round_payload.get("translatedTexts") or [])
    return any(is_translation_failure_text(text) for text in texts)


def _is_japanese_translation_context(context_snapshot):
    if not isinstance(context_snapshot, dict):
        return True
    source_language = str(context_snapshot.get("sourceLanguage") or "japanese").strip().lower()
    prompt_profile = str(context_snapshot.get("promptPreset") or context_snapshot.get("promptProfile") or "").strip().lower()
    return source_language != "english" and prompt_profile != "english"


def _has_latin_word(text):
    for match in _LATIN_WORD_RE.finditer(str(text or "")):
        value = match.group(0)
        if value.isupper():
            continue
        return True
    return False


def _translation_payload_has_suspicious_latin(page_plan, payload, context_snapshot):
    if not _is_japanese_translation_context(context_snapshot):
        return False
    indexes = list((page_plan or {}).get("indexes") or [])
    source_texts = list((page_plan or {}).get("texts") or [])
    translated_texts = list((_normalize_translation_payload(payload).get("translatedTexts") or []))
    for slot, bubble_index in enumerate(indexes):
        source = source_texts[slot] if slot < len(source_texts) else ""
        translated = translated_texts[bubble_index] if bubble_index < len(translated_texts) else ""
        if _JAPANESE_SCRIPT_RE.search(str(source or "")) and _has_latin_word(translated):
            return True
    return False


def _known_term_glossary_for_page(page_plan):
    texts = "\n".join(str(text or "") for text in (page_plan or {}).get("texts") or [])
    return {
        term: translated
        for term, translated in _KNOWN_JAPANESE_TERM_TRANSLATIONS.items()
        if term in texts
    }


def _build_page_known_term_context(context_snapshot, page_plan):
    glossary_additions = _known_term_glossary_for_page(page_plan)
    if not glossary_additions:
        return context_snapshot
    snapshot = dict(context_snapshot or {})
    glossary = dict(snapshot.get("glossary") or {})
    glossary.update(glossary_additions)
    snapshot["glossary"] = glossary
    return snapshot


def _build_latin_retry_context(context_snapshot, page_plan, payload):
    snapshot = dict(context_snapshot or {})
    glossary = dict(snapshot.get("glossary") or {})
    glossary.update(_known_term_glossary_for_page(page_plan))
    snapshot["glossary"] = glossary

    translated_texts = _normalize_translation_payload(payload).get("translatedTexts") or []
    latin_examples = []
    for text in translated_texts:
        match = _LATIN_WORD_RE.search(str(text or ""))
        if match:
            latin_examples.append(match.group(0))
    examples = "、".join(dict.fromkeys(latin_examples[:3]))
    retry_note = "质量修正规则: 上轮译文保留了日文词的罗马字。日文术语、假名词和专有表达必须译成中文，不要输出罗马字。"
    if examples:
        retry_note += f" 需要改掉的罗马字示例: {examples}。"
    if glossary:
        retry_note += " 已给出的术语映射必须优先遵守。"

    manga_context = str(snapshot.get("mangaContext") or "").strip()
    snapshot["mangaContext"] = f"{manga_context}\n\n{retry_note}".strip()
    return snapshot


def _replace_known_term_in_text(source_text, translated_text):
    result = str(translated_text or "")
    source = str(source_text or "")
    forced_sound_effect = _KNOWN_JAPANESE_SOUND_EFFECT_FORCE_TRANSLATIONS.get(source.strip())
    if forced_sound_effect is not None:
        return forced_sound_effect
    for term, replacement in _KNOWN_JAPANESE_TERM_TRANSLATIONS.items():
        if term not in source:
            continue
        result = result.replace(term, replacement)
        romaji_pattern = _KNOWN_JAPANESE_TERM_ROMAJI.get(term)
        if romaji_pattern is not None:
            result = romaji_pattern.sub(replacement, result)
    for sound_effect, replacement in _KNOWN_JAPANESE_SOUND_EFFECT_TRANSLATIONS.items():
        if sound_effect not in source:
            continue
        result = result.replace(sound_effect, replacement)
        for variant in _KNOWN_JAPANESE_SOUND_EFFECT_TRANSLITERATIONS.get(sound_effect, ()):
            result = result.replace(variant, replacement)
    return result


def _apply_known_japanese_term_translations(page_plan, payload):
    normalized = _normalize_translation_payload(payload)
    indexes = list((page_plan or {}).get("indexes") or [])
    source_texts = list((page_plan or {}).get("texts") or [])

    def apply_to_full_page_texts(texts):
        updated = list(texts or [])
        for slot, bubble_index in enumerate(indexes):
            if bubble_index >= len(updated):
                continue
            source = source_texts[slot] if slot < len(source_texts) else ""
            updated[bubble_index] = _replace_known_term_in_text(source, updated[bubble_index])
        return updated

    normalized["translatedTexts"] = apply_to_full_page_texts(normalized.get("translatedTexts") or [])
    rounds = []
    for round_payload in normalized.get("rounds") or []:
        if not isinstance(round_payload, dict):
            continue
        updated_round = dict(round_payload)
        updated_round["translatedTexts"] = apply_to_full_page_texts(round_payload.get("translatedTexts") or [])
        rounds.append(updated_round)
    normalized["rounds"] = rounds
    return normalized


def _copy_original_page(source_path, target_path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)


def _normalize_target_page_names(page_names):
    normalized = []
    seen = set()
    for name in page_names or []:
        value = str(name or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _build_page_translation_plan(preprocessed_payload, source_path):
    detection = {
        "bubbleCoords": preprocessed_payload.get("bubbleCoords", []) or [],
        "textlinesPerBubble": preprocessed_payload.get("textlinesPerBubble", []) or [],
        "bubbleColors": preprocessed_payload.get("bubbleColors", []) or [],
        "bubbleLayoutHints": preprocessed_payload.get("bubbleLayoutHints", []) or [],
    }
    ocr = {
        "originalTexts": preprocessed_payload.get("originalTexts", []) or [],
        "ocrResults": preprocessed_payload.get("ocrResults", []) or [],
    }
    profiles = build_bubble_text_profiles(detection, ocr, image_size=load_image_size(source_path))
    texts = []
    indexes = []
    for index, profile in enumerate(profiles):
        source_text = str((profile or {}).get("sourceText") or "").strip()
        if (profile or {}).get("suppressTranslation") or not source_text:
            continue
        indexes.append(index)
        texts.append(source_text)
    return {
        "profiles": profiles,
        "indexes": indexes,
        "texts": texts,
        "bubbleCoords": list(detection.get("bubbleCoords", []) or []),
        "count": len(ocr["originalTexts"]),
    }


def _normalize_render_text(text):
    lines = [line.strip() for line in str(text or "").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _normalize_long_narration_translation_text(text):
    normalized = _normalize_render_text(text)
    if not normalized:
        return ""
    normalized = normalized.replace("...", "……").replace("..", "……")
    normalized = normalized.translate(_LONG_NARRATION_ASCII_PUNCT_TRANSLATION)
    normalized = _CJK_PERIOD_RE.sub("。", normalized)
    return normalized


def _normalize_vertical_long_narration_translation_text(text):
    normalized = _normalize_long_narration_translation_text(text)
    if not normalized:
        return ""
    return re.sub(r"\s*\n+\s*", "", normalized)


def _estimate_long_narration_line_width(text, coords):
    width = 0
    height = 0
    if isinstance(coords, (list, tuple)) and len(coords) >= 4:
        width = max(0, int(coords[2]) - int(coords[0]))
        height = max(0, int(coords[3]) - int(coords[1]))
    compact_length = len(str(text or "").replace("\n", ""))
    if compact_length <= 0:
        return 0
    target_lines = max(6, min(20, int(round(height / 34.0)) or 0))
    chars_from_height = max(18, -(-compact_length // max(1, target_lines)))
    chars_from_width = max(18, min(36, int(width / 18) if width > 0 else 24))
    return max(18, min(36, min(chars_from_height, chars_from_width)))


def _estimate_long_narration_line_capacity(coords):
    height = 0
    if isinstance(coords, (list, tuple)) and len(coords) >= 4:
        height = max(0, int(coords[3]) - int(coords[1]))
    return max(8, int(height / 28) if height > 0 else 12)


def _split_long_narration_units(text):
    normalized = _normalize_long_narration_translation_text(text)
    if not normalized:
        return []
    paragraphs = [item.strip() for item in normalized.split("\n") if item.strip()]
    units = []
    for paragraph in paragraphs:
        strong_parts = [part.strip() for part in _LONG_NARRATION_STRONG_BREAK_RE.split(paragraph) if part.strip()]
        for strong_part in strong_parts:
            if len(strong_part) <= 36:
                units.append(strong_part)
                continue
            soft_parts = [part.strip() for part in _LONG_NARRATION_SOFT_BREAK_RE.split(strong_part) if part.strip()]
            if soft_parts:
                units.extend(soft_parts)
            else:
                units.append(strong_part)
    return units


def _starts_new_long_narration_paragraph(unit):
    stripped = str(unit or "").lstrip("“\"'（(")
    return any(stripped.startswith(marker) for marker in _LONG_NARRATION_PARAGRAPH_MARKERS)


def _group_long_narration_units(units, target_width):
    paragraphs = []
    current = []
    current_length = 0
    for unit in units:
        unit_length = len(unit)
        should_break = False
        if current and _starts_new_long_narration_paragraph(unit) and current_length >= max(16, int(target_width * 0.75)):
            should_break = True
        if not should_break and current:
            if current_length >= int(target_width * 1.45):
                should_break = True
            elif len(current) >= 2 and current_length >= target_width:
                should_break = True
        if should_break:
            paragraphs.append(list(current))
            current = []
            current_length = 0
        current.append(unit)
        current_length += unit_length
    if current:
        paragraphs.append(list(current))
    return paragraphs


def _wrap_long_narration_units(units, target_width):
    lines = []
    current = ""
    overflow_tolerance = max(6, int(target_width * 0.35))
    for unit in units:
        candidate = f"{current}{unit}" if current else unit
        if len(candidate) <= target_width or (current and len(candidate) <= target_width + overflow_tolerance):
            current = candidate
            continue
        if current:
            lines.append(current)
        if len(unit) <= target_width + overflow_tolerance:
            current = unit
            continue
        start = 0
        while start < len(unit):
            chunk = unit[start : start + target_width]
            if len(chunk) == target_width:
                lines.append(chunk)
            else:
                current = chunk
            start += target_width
        if len(unit) % target_width == 0:
            current = ""
    if current:
        lines.append(current)
    merged_lines = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if len(line) <= 6 and index + 1 < len(lines):
            candidate = f"{line}{lines[index + 1]}"
            if len(candidate) <= target_width + (overflow_tolerance * 2):
                merged_lines.append(candidate)
                index += 2
                continue
        merged_lines.append(line)
        index += 1
    return [line for line in merged_lines if line]


def _reflow_long_narration_text(text, coords):
    normalized = _normalize_long_narration_translation_text(text)
    target_width = _estimate_long_narration_line_width(normalized, coords)
    if target_width <= 0 or len(normalized.replace("\n", "")) <= target_width:
        return normalized

    units = _split_long_narration_units(normalized)
    if not units:
        return normalized
    paragraphs = _group_long_narration_units(units, target_width)
    wrapped_paragraphs = [_wrap_long_narration_units(paragraph_units, target_width) for paragraph_units in paragraphs]
    wrapped_paragraphs = [paragraph for paragraph in wrapped_paragraphs if paragraph]
    if not wrapped_paragraphs:
        return normalized

    gap_budget = 0
    if isinstance(coords, (list, tuple)) and len(coords) >= 4:
        height = max(0, int(coords[3]) - int(coords[1]))
        line_capacity = _estimate_long_narration_line_capacity(coords)
        line_count = sum(len(paragraph) for paragraph in wrapped_paragraphs)
        gap_count = max(0, len(wrapped_paragraphs) - 1)
        if height >= 320 and gap_count > 0:
            gap_budget = max(0, int(line_capacity * 1.15) - line_count)

    paragraph_texts = ["\n".join(paragraph) for paragraph in wrapped_paragraphs]
    if gap_budget <= 0:
        return "\n".join(paragraph_texts)

    preferred_gap_indexes = []
    for index in range(1, len(paragraphs)):
        if _starts_new_long_narration_paragraph(paragraphs[index][0]):
            preferred_gap_indexes.append(index)
    for index in range(1, len(paragraphs)):
        if index not in preferred_gap_indexes:
            preferred_gap_indexes.append(index)

    gap_indexes = set(preferred_gap_indexes[:gap_budget])
    chunks = [paragraph_texts[0]]
    for index, paragraph_text in enumerate(paragraph_texts[1:], start=1):
        chunks.append(("\n\n" if index in gap_indexes else "\n") + paragraph_text)
    return "".join(chunks)


def _format_translated_text_for_profile(text, profile, coords):
    role = str((profile or {}).get("role") or "").strip()
    normalized = _normalize_render_text(text)
    if role != "long_narration":
        return normalized
    if str((profile or {}).get("directionOverride") or "").strip() == "vertical":
        return _normalize_vertical_long_narration_translation_text(normalized)
    return _reflow_long_narration_text(normalized, coords)


def _format_translated_texts_for_page(page_plan, translated_texts):
    page_plan = page_plan or {}
    profiles = list(page_plan.get("profiles") or [])
    bubble_coords = list(page_plan.get("bubbleCoords") or [])
    formatted = [""] * len(list(translated_texts or []))
    for index, text in enumerate(translated_texts or []):
        profile = profiles[index] if index < len(profiles) else {}
        coords = bubble_coords[index] if index < len(bubble_coords) else []
        formatted[index] = _format_translated_text_for_profile(text, profile, coords)
    return formatted


def _sanitize_round_failure_placeholders(round_texts, final_texts):
    sanitized = []
    final_texts = list(final_texts or [])
    for index, text in enumerate(round_texts or []):
        value = str(text or "").strip()
        final_value = str(final_texts[index] if index < len(final_texts) else "").strip()
        if is_translation_failure_text(value) and final_value and not is_translation_failure_text(final_value):
            sanitized.append(final_texts[index])
        else:
            sanitized.append(text)
    return sanitized


def _expand_translation_payload_to_page(raw_payload, page_plan):
    normalized = _normalize_translation_payload(raw_payload)
    total_count = int((page_plan or {}).get("count") or 0)
    translated_indexes = list((page_plan or {}).get("indexes") or [])
    translated_texts = [""] * total_count
    for slot, bubble_index in enumerate(translated_indexes):
        if slot >= len(normalized.get("translatedTexts") or []):
            break
        translated_texts[bubble_index] = normalized["translatedTexts"][slot]
    translated_texts = _format_translated_texts_for_page(page_plan, translated_texts)

    rounds = []
    for round_payload in normalized.get("rounds") or []:
        round_texts = [""] * total_count
        round_translated = list((round_payload or {}).get("translatedTexts") or [])
        for slot, bubble_index in enumerate(translated_indexes):
            if slot >= len(round_translated):
                break
            round_texts[bubble_index] = round_translated[slot]
        round_texts = _format_translated_texts_for_page(page_plan, round_texts)
        round_texts = _sanitize_round_failure_placeholders(round_texts, translated_texts)
        rounds.append(
            {
                "name": round_payload.get("name") or "final",
                "translatedTexts": round_texts,
                "usage": dict(round_payload.get("usage") or _empty_usage()),
            }
        )

    return {
        "translatedTexts": translated_texts,
        "rounds": rounds,
        "tokenUsage": dict(normalized.get("tokenUsage") or _empty_usage()),
        "ocrRetry": dict(normalized.get("ocrRetry") or _default_ocr_retry_state()),
    }


def _translate_pages_individually(prepared_pages, model, base_url, api_key, context_snapshot, reporter):
    translated_by_page = {}
    failures = {}

    for item in prepared_pages:
        if item.translated_texts is not None:
            translated_by_page[item.page["id"]] = item.translation_payload or _build_legacy_translation_payload(item.translated_texts)
            continue

        reporter.log(f"TRANSLATE retry-single {item.page['fileName']}")
        try:
            translated_by_page.update(_translate_batch([item], model, base_url, api_key, context_snapshot))
        except Exception as error:
            reporter.log(f"TRANSLATE retry-single fail {item.page['fileName']} error={error}")
            try:
                translated_by_page[item.page["id"]] = _translate_page_lightweight(
                    item,
                    model,
                    base_url,
                    api_key,
                    context_snapshot,
                    reporter,
                )
            except Exception as fallback_error:
                failures[item.page["id"]] = fallback_error
                reporter.log(f"TRANSLATE fallback-light fail {item.page['fileName']} error={fallback_error}")

    return translated_by_page, failures


def _translate_page_lightweight(item, model, base_url, api_key, context_snapshot, reporter):
    reporter.log(f"TRANSLATE fallback-light {item.page['fileName']}")
    page_plan = _build_page_translation_plan(item.preprocessed_payload, item.source_path)
    if not page_plan["texts"]:
        return {
            "translatedTexts": [""] * page_plan["count"],
            "rounds": [],
            "tokenUsage": _empty_usage(),
            "ocrRetry": _default_ocr_retry_state(),
        }
    texts = page_plan["texts"]
    lightweight_context = context_snapshot if _has_translation_context(context_snapshot) else None
    attempts = [
        {
            "texts": texts,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "context_snapshot": lightweight_context,
        },
        {
            "texts": texts,
            "model": model,
            "base_url": base_url,
            "context_snapshot": lightweight_context,
        },
        {
            "texts": texts,
            "model": model,
            "base_url": base_url,
        },
    ]
    last_error = None
    translated = None
    for kwargs in attempts:
        try:
            translated = translate_texts(**kwargs)
            break
        except TypeError as error:
            last_error = error
            error_text = str(error)
            if "unexpected keyword argument" not in error_text and "required keyword-only argument" not in error_text:
                raise
        except Exception as error:
            last_error = error
            break

    if translated is None:
        raise last_error or RuntimeError("lightweight translation failed")

    return _expand_translation_payload_to_page(_build_legacy_translation_payload(translated), page_plan)


def _prepare_batch(
    pages,
    start_index,
    output_dir,
    numeric_output_width,
    overwrite_existing,
    final_debug_records,
    reporter,
    counters,
    started_at,
    stage_cache,
    saber_session,
    debug_writer,
    manga_context_payload,
    skip_frontmatter,
    translate_batch_size,
    translate_batch_max_chars,
    ocr_options=None,
    style_profile=None,
    settings=None,
    force_retranslate=False,
    debug_total_pages=None,
    debug_records_by_source=None,
):
    prepared_pages = []
    batch_chars = 0
    record_total_pages = int(debug_total_pages or len(pages))

    while start_index < len(pages) and len(prepared_pages) < translate_batch_size:
        page = pages[start_index]
        current_index = start_index + 1
        page_index = int(page.get("pageIndex") or current_index)
        start_index += 1

        source_path = Path(page["sourcePath"])
        target_path = build_output_path(source_path, output_dir, numeric_width=numeric_output_width)
        cached_stage = stage_cache.load_best(source_path)
        if cached_stage is not None and not _preprocessed_payload_matches_ocr_options(
            cached_stage.get("preprocessed"),
            ocr_options,
        ):
            cached_stage = None
        reporter.update(
            current_index=current_index,
            total_count=len(pages),
            current_name=page["fileName"],
            succeeded=counters["succeeded"],
            skipped=counters["skipped"],
            failed=counters["failed"],
            elapsed_seconds=perf_counter() - started_at,
        )

        if target_path.exists() and not overwrite_existing and cached_stage is None:
            debug_record = (debug_records_by_source or {}).get(page["fileName"])
            preprocessed_payload = _debug_record_to_preprocessed_payload(debug_record)
            translated_texts = _debug_record_translated_texts(debug_record) if debug_record else None
            translation_payload = (debug_record or {}).get("translation") if isinstance(debug_record, dict) else None
            classification = None
            if preprocessed_payload is not None:
                classification = classify_preprocessed_page(
                    page_index=page_index,
                    total_pages=record_total_pages,
                    image_size=load_image_size(source_path),
                    preprocessed_payload=preprocessed_payload,
                    skip_frontmatter=skip_frontmatter,
                )
            counters["skipped"] += 1
            record = debug_writer.record_page(
                page=page,
                page_index=page_index,
                total_pages=record_total_pages,
                source_path=source_path,
                target_path=target_path,
                status="skipped-existing",
                preprocessed_payload=preprocessed_payload,
                translated_texts=translated_texts,
                translation_payload=translation_payload,
                classification=classification,
                manga_context=manga_context_payload,
            )
            final_debug_records[page["id"]] = record
            reporter.log(f"SKIP {page['fileName']} -> {target_path.name} (already exists)")
            continue

        if cached_stage is not None:
            preprocessed_payload = cached_stage["preprocessed"]
            translated_texts = cached_stage.get("translatedTexts")
            translation_payload = cached_stage.get("translationPayload")
            if force_retranslate and cached_stage.get("stage") == "translated":
                translated_texts = None
                translation_payload = None
            reporter.log(
                f"PREP-CACHE {page['fileName']} "
                f"stage={cached_stage.get('stage', 'preprocessed')} "
                f"texts={_count_page_texts(preprocessed_payload)} "
                f"chars={_count_page_chars(preprocessed_payload)}"
            )
        else:
            preprocessed_payload = None
            if force_retranslate and debug_records_by_source:
                preprocessed_payload = _debug_record_to_preprocessed_payload(
                    debug_records_by_source.get(page["fileName"])
                )
                if not _preprocessed_payload_matches_ocr_options(preprocessed_payload, ocr_options):
                    preprocessed_payload = None
            if preprocessed_payload is not None:
                stage_cache.save_preprocessed(source_path, preprocessed_payload)
                translated_texts = None
                translation_payload = None
                reporter.log(
                    f"PREP-DEBUG {page['fileName']} "
                    f"texts={_count_page_texts(preprocessed_payload)} "
                    f"chars={_count_page_chars(preprocessed_payload)}"
                )
            else:
                reporter.log(f"PREP {page['fileName']} start")
                try:
                    preprocessed_payload = _call_preprocess_page(
                        page["sourcePath"],
                        saber_session=saber_session,
                        ocr_options=ocr_options,
                    )
                except Exception as error:
                    _copy_original_page(source_path, target_path)
                    counters["failed"] += 1
                    record = debug_writer.record_page(
                        page=page,
                        page_index=page_index,
                        total_pages=record_total_pages,
                        source_path=source_path,
                        target_path=target_path,
                        status="failed",
                        preprocessed_payload=None,
                        translated_texts=[],
                        translation_payload=None,
                        classification=None,
                        manga_context=manga_context_payload,
                        error=error,
                    )
                    final_debug_records[page["id"]] = record
                    reporter.log(f"FAIL-PREP {page['fileName']} -> {target_path.name} ({error})")
                    continue
                stage_cache.save_preprocessed(source_path, preprocessed_payload)
                translated_texts = None
                translation_payload = None
                timings = preprocessed_payload.get("timings", {}) if isinstance(preprocessed_payload.get("timings"), dict) else {}
                prep_seconds = float(timings.get("total", 0.0) or 0.0)
                reporter.log(
                    f"PREP {page['fileName']} done "
                    f"bubbles={len(preprocessed_payload.get('bubbleCoords', []) or [])} "
                    f"texts={_count_page_texts(preprocessed_payload)} "
                    f"chars={_count_page_chars(preprocessed_payload)} "
                    f"({format_seconds(prep_seconds) if prep_seconds > 0 else 'n/a'})"
                )

        classification = None
        page_translation_plan = None
        if preprocessed_payload is not None:
            assisted_payload = _apply_layout_assist_to_preprocessed(
                source_path,
                preprocessed_payload,
                style_profile=style_profile,
                settings=settings,
            )
            if assisted_payload is not preprocessed_payload:
                preprocessed_payload = assisted_payload
                stage_cache.save_preprocessed(source_path, preprocessed_payload)
            classification = classify_preprocessed_page(
                page_index=page_index,
                total_pages=record_total_pages,
                image_size=load_image_size(source_path),
                preprocessed_payload=preprocessed_payload,
                skip_frontmatter=skip_frontmatter,
            )
            page_translation_plan = _build_page_translation_plan(preprocessed_payload, source_path)
            if not page_translation_plan["texts"]:
                classification = {
                    **classification,
                    "should_translate": False,
                    "skip_reason": "bubble_filtered",
                }
            if translated_texts is not None and (overwrite_existing or not target_path.exists()):
                translated_texts = _format_translated_texts_for_page(page_translation_plan, translated_texts)

        if target_path.exists() and not overwrite_existing:
            counters["skipped"] += 1
            record = debug_writer.record_page(
                page=page,
                page_index=page_index,
                total_pages=record_total_pages,
                source_path=source_path,
                target_path=target_path,
                status="skipped-existing",
                preprocessed_payload=preprocessed_payload,
                translated_texts=translated_texts,
                translation_payload=translation_payload,
                classification=classification,
                manga_context=manga_context_payload,
            )
            final_debug_records[page["id"]] = record
            reporter.log(f"SKIP {page['fileName']} -> {target_path.name} (already exists)")
            continue
        if target_path.exists() and overwrite_existing:
            reporter.log(f"OVERWRITE {page['fileName']} -> {target_path.name}")

        if not classification.get("should_translate", True):
            _copy_original_page(source_path, target_path)
            counters["succeeded"] += 1
            record = debug_writer.record_page(
                page=page,
                page_index=page_index,
                total_pages=record_total_pages,
                source_path=source_path,
                target_path=target_path,
                status="copied",
                preprocessed_payload=preprocessed_payload,
                translated_texts=[],
                translation_payload=None,
                classification=classification,
                manga_context=manga_context_payload,
            )
            final_debug_records[page["id"]] = record
            reporter.log(
                f"COPY {page['fileName']} -> {target_path.name} ({classification.get('skip_reason') or classification.get('page_type')})"
            )
            continue

        prepared_pages.append(
            PreparedPage(
                page=page,
                source_path=source_path,
                target_path=target_path,
                preprocessed_payload=preprocessed_payload,
                classification=classification,
                translated_texts=translated_texts,
                translation_payload=translation_payload,
            )
        )
        batch_chars += _count_page_chars(preprocessed_payload)
        if batch_chars >= translate_batch_max_chars:
            break

    return prepared_pages, start_index


def _all_page_outputs_exist(pages, output_dir, numeric_output_width):
    for page in pages:
        source_path = Path(page["sourcePath"])
        target_path = build_output_path(source_path, output_dir, numeric_width=numeric_output_width)
        if not target_path.exists():
            return False
    return True


def _record_existing_output_skips(
    pages,
    output_dir,
    numeric_output_width,
    final_debug_records,
    reporter,
    counters,
    started_at,
    stage_cache,
    debug_writer,
    manga_context_payload,
    skip_frontmatter,
    debug_records_by_source=None,
):
    record_total_pages = len(pages)
    for index, page in enumerate(pages, start=1):
        page_index = int(page.get("pageIndex") or index)
        source_path = Path(page["sourcePath"])
        target_path = build_output_path(source_path, output_dir, numeric_width=numeric_output_width)
        cached_stage = stage_cache.load_best(source_path)
        preprocessed_payload = cached_stage.get("preprocessed") if cached_stage is not None else None
        translated_texts = cached_stage.get("translatedTexts") if cached_stage is not None else None
        translation_payload = cached_stage.get("translationPayload") if cached_stage is not None else None
        if cached_stage is None and debug_records_by_source:
            debug_record = debug_records_by_source.get(page["fileName"])
            preprocessed_payload = _debug_record_to_preprocessed_payload(debug_record)
            if preprocessed_payload is not None:
                translated_texts = list((debug_record or {}).get("translatedTexts") or [])
                translation_payload = (debug_record or {}).get("translation")
        classification = None
        if preprocessed_payload is not None:
            classification = classify_preprocessed_page(
                page_index=page_index,
                total_pages=record_total_pages,
                image_size=load_image_size(source_path),
                preprocessed_payload=preprocessed_payload,
                skip_frontmatter=skip_frontmatter,
            )

        reporter.update(
            current_index=index,
            total_count=len(pages),
            current_name=page["fileName"],
            succeeded=counters["succeeded"],
            skipped=counters["skipped"],
            failed=counters["failed"],
            elapsed_seconds=perf_counter() - started_at,
        )
        counters["skipped"] += 1
        record = debug_writer.record_page(
            page=page,
            page_index=page_index,
            total_pages=record_total_pages,
            source_path=source_path,
            target_path=target_path,
            status="skipped-existing",
            preprocessed_payload=preprocessed_payload,
            translated_texts=translated_texts,
            translation_payload=translation_payload,
            classification=classification,
            manga_context=manga_context_payload,
        )
        final_debug_records[page["id"]] = record
        reporter.log(f"SKIP {page['fileName']} -> {target_path.name} (already exists)")


def run_batch_translation(
    input_dir=None,
    output_dir=None,
    workspace_root=None,
    reporter=None,
    model=None,
    base_url=None,
    api_key=None,
    cache_root=None,
    overwrite_existing=None,
    layout_mode=None,
    style_id=None,
    launch_mode="args",
    retry_review_pages=False,
    retry_quality_review_pages=False,
    target_page_names=None,
):
    cli_config = _resolve_cli_settings()
    translation_config = cli_config["translation"]
    ocr_config = cli_config["ocr"]
    pipeline_config = cli_config["pipeline"]
    path_config = cli_config["paths"]
    render_config = cli_config["render"]

    input_dir = input_dir or path_config["input_dir"]
    output_dir = output_dir or path_config["output_dir"]
    if input_dir is None or output_dir is None:
        raise ValueError("Input folder and output folder must be provided either by arguments or config.")

    model = model or translation_config["model"]
    base_url = base_url or translation_config["base_url"]
    if api_key is None:
        api_key = translation_config["api_key"]
    if overwrite_existing is None:
        overwrite_existing = pipeline_config["overwrite_existing"]
    translation_quality = pipeline_config.get("translation_quality", "high")
    workspace_root = workspace_root or path_config["workspace_root"]
    cache_root = cache_root or path_config["cache_root"]
    style_profile = resolve_style_profile(style_id, layout_mode=layout_mode or render_config["layout_mode"])
    layout_mode = style_profile["layout_mode"]
    style_ocr_config = _build_style_ocr_config(ocr_config, style_profile=style_profile)
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    reporter = reporter or BatchProgressReporter()
    all_image_paths = scan_input_images(input_dir)
    if not all_image_paths:
        raise ValueError("No supported image files found in input folder.")
    all_pages = _build_pages(all_image_paths)
    image_paths = list(all_image_paths)
    pages = list(all_pages)
    existing_debug_records = {}
    numeric_output_width = _resolve_numeric_output_width(all_image_paths)

    selected_page_names = set()
    explicit_target_page_names = _normalize_target_page_names(target_page_names)
    if retry_review_pages:
        selected_page_names = _load_retry_review_page_names(
            output_dir,
            image_paths=all_image_paths,
            numeric_width=numeric_output_width,
            include_quality_review=retry_quality_review_pages,
        )
        if not selected_page_names:
            raise ValueError(f"No review pages found in: {output_dir / '_debug'}")
    if explicit_target_page_names:
        if selected_page_names:
            selected_page_names = selected_page_names.intersection(explicit_target_page_names)
        else:
            selected_page_names = set(explicit_target_page_names)
    if selected_page_names:
        pages = [page for page in all_pages if page["fileName"] in selected_page_names]
        image_paths = [Path(page["sourcePath"]) for page in pages]
        if not pages:
            raise ValueError("Selected page list does not match any source image in input folder.")
        overwrite_existing = True
        existing_debug_records = _load_existing_debug_records(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    existing_debug_records = _load_existing_debug_records(output_dir)
    run_options = _build_run_options(
        input_dir=input_dir,
        output_dir=output_dir,
        layout_mode=layout_mode,
        overwrite_existing=overwrite_existing,
        launch_mode=launch_mode,
        model=model,
        ocr_config=style_ocr_config,
        retry_review_pages=retry_review_pages,
        target_page_names=[page["fileName"] for page in pages] if selected_page_names else None,
        style_profile=style_profile,
        translation_quality=translation_quality,
    )
    started_at = perf_counter()
    counters = {
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
    }
    final_debug_records = {}
    debug_total_pages = len(all_pages) if selected_page_names else len(pages)

    manga_context_payload = None
    should_fast_skip_existing = (
        not selected_page_names
        and not overwrite_existing
        and _all_page_outputs_exist(pages, output_dir, numeric_output_width)
    )
    if not should_fast_skip_existing:
        try:
            manga_context_payload = load_or_generate_manga_context(
                input_dir,
                auto_generate=pipeline_config.get("auto_generate_manga_context", True),
                pipeline_config=pipeline_config,
            )
        except Exception:
            manga_context_payload = None

    stage_cache = BatchStageCache(
        cache_root=cache_root or _default_cache_root(),
        input_dir=input_dir,
        model=model,
        base_url=base_url,
        translation_signature=_build_translation_signature(
            cli_config["settings"],
            style_profile=style_profile,
            manga_context_payload=manga_context_payload,
            translation_quality=translation_quality,
        ),
        preprocess_signature=_build_preprocess_signature(cli_config["settings"], style_profile=style_profile),
    )
    debug_writer = (
        BatchDebugArtifactWriter(
            output_dir,
            run_options=run_options,
            flush_interval=pipeline_config.get("debug_flush_interval", 25),
        )
        if pipeline_config["debug_output"]
        else NullBatchDebugArtifactWriter()
    )

    if should_fast_skip_existing:
        _record_existing_output_skips(
            pages,
            output_dir,
            numeric_output_width,
            final_debug_records,
            reporter,
            counters,
            started_at,
            stage_cache,
            debug_writer,
            manga_context_payload,
            pipeline_config["skip_frontmatter"],
            debug_records_by_source=existing_debug_records,
        )
        total_elapsed = perf_counter() - started_at
        summary = {
            "total": len(pages),
            "succeeded": counters["succeeded"],
            "skipped": counters["skipped"],
            "failed": counters["failed"],
            "elapsedSeconds": total_elapsed,
        }
        debug_writer.finish(summary, records=final_debug_records, run_options=run_options)
        reporter.finish(
            total_count=len(pages),
            succeeded=counters["succeeded"],
            skipped=counters["skipped"],
            failed=counters["failed"],
            elapsed_seconds=total_elapsed,
        )
        return summary

    temp_kwargs = {"prefix": "translate-manga-cli-"}
    if workspace_root is not None:
        workspace_parent = Path(workspace_root)
        workspace_parent.mkdir(parents=True, exist_ok=True)
        temp_kwargs["dir"] = str(workspace_parent)

    with tempfile.TemporaryDirectory(**temp_kwargs) as data_root:
        runtime = PipelineRuntime(
            data_root,
            layout_mode=layout_mode,
            style_id=style_profile["style_id"],
            source_language=style_profile.get("source_language"),
            prompt_profile=style_profile.get("prompt_profile"),
            reading_order=style_profile.get("reading_order"),
            ocr_options=style_ocr_config,
            font_family=style_profile.get("font_family"),
        )
        runtime.seed_pages(all_pages if selected_page_names else pages)
        if selected_page_names:
            _seed_runtime_context_from_debug(runtime, all_pages, existing_debug_records, selected_page_names)

        next_index = 0
        with SaberWorkerSession() as saber_session, ThreadPoolExecutor(max_workers=1) as executor:
            current_batch, next_index = _prepare_batch(
                pages,
                next_index,
                output_dir,
                numeric_output_width,
                overwrite_existing,
                final_debug_records,
                reporter,
                counters,
                started_at,
                stage_cache,
                saber_session,
                debug_writer,
                manga_context_payload,
                pipeline_config["skip_frontmatter"],
                pipeline_config["translate_batch_size"],
                pipeline_config["translate_batch_max_chars"],
                force_retranslate=bool(selected_page_names),
                debug_total_pages=debug_total_pages,
                debug_records_by_source=existing_debug_records,
                ocr_options=style_ocr_config,
                style_profile=style_profile,
                settings=cli_config["settings"],
            )

            while current_batch:
                batch_context_snapshot = _build_translation_context(runtime, current_batch[0].page["id"])
                if selected_page_names:
                    batch_context_snapshot = _augment_context_with_debug_neighbors(
                        batch_context_snapshot,
                        all_pages,
                        current_batch[0].page["id"],
                        existing_debug_records,
                        selected_page_names,
                    )
                batch_context_snapshot = {
                    **batch_context_snapshot,
                    "mangaContext": str((manga_context_payload or {}).get("content") or "").strip(),
                    "sourceLanguage": style_profile.get("source_language", "japanese"),
                    "promptPreset": style_profile.get("prompt_profile", "default"),
                    "readingOrder": style_profile.get("reading_order"),
                    "translationQuality": translation_quality,
                }
                translation_future = None
                translation_started_at = None
                pending_items = [item for item in current_batch if item.translated_texts is None]
                pending_names = [item.page["fileName"] for item in pending_items]
                if pending_items:
                    translation_started_at = perf_counter()
                    reporter.log(
                        f"TRANSLATE start pages={', '.join(pending_names)} "
                        f"texts={sum(_count_page_texts(item.preprocessed_payload) for item in pending_items)} "
                        f"chars={sum(_count_page_chars(item.preprocessed_payload) for item in pending_items)}"
                    )
                    translation_future = executor.submit(
                        _translate_batch,
                        current_batch,
                        model,
                        base_url,
                        api_key,
                        batch_context_snapshot,
                    )

                next_batch, next_index = _prepare_batch(
                    pages,
                    next_index,
                    output_dir,
                    numeric_output_width,
                    overwrite_existing,
                    final_debug_records,
                    reporter,
                    counters,
                    started_at,
                    stage_cache,
                    saber_session,
                    debug_writer,
                    manga_context_payload,
                    pipeline_config["skip_frontmatter"],
                    pipeline_config["translate_batch_size"],
                    pipeline_config["translate_batch_max_chars"],
                    force_retranslate=bool(selected_page_names),
                    debug_total_pages=debug_total_pages,
                    debug_records_by_source=existing_debug_records,
                    ocr_options=style_ocr_config,
                    style_profile=style_profile,
                    settings=cli_config["settings"],
                )

                translated_by_page = {}
                translation_failures = {}
                if translation_future is not None:
                    try:
                        translated_by_page = translation_future.result()
                        translation_elapsed = perf_counter() - translation_started_at
                        _assign_batch_translation_seconds(pending_items, translation_elapsed)
                        reporter.log(
                            f"TRANSLATE done pages={', '.join(pending_names)} "
                            f"({format_seconds(translation_elapsed)})"
                        )
                    except Exception as error:
                        translation_elapsed = perf_counter() - translation_started_at
                        reporter.log(
                            f"TRANSLATE fail pages={', '.join(pending_names)} "
                            f"({format_seconds(translation_elapsed)}) "
                            f"error={error}"
                        )
                        translated_by_page, translation_failures = _translate_pages_individually(
                            current_batch,
                            model,
                            base_url,
                            api_key,
                            batch_context_snapshot,
                            reporter,
                        )
                        _assign_batch_translation_seconds(
                            pending_items,
                            perf_counter() - translation_started_at,
                        )

                for item in current_batch:
                    page_started_at = perf_counter()
                    reporter.log(f"RENDER {item.page['fileName']} start")

                    if item.translated_texts is None:
                        if item.page["id"] in translation_failures:
                            _copy_original_page(item.source_path, item.target_path)
                            counters["failed"] += 1
                            record = debug_writer.record_page(
                                page=item.page,
                                page_index=int(item.page.get("pageIndex") or str(item.page["id"]).split("-")[-1]),
                                total_pages=debug_total_pages,
                                source_path=item.source_path,
                                target_path=item.target_path,
                                status="failed",
                                preprocessed_payload=_with_batch_translation_timing(
                                    item.preprocessed_payload,
                                    item.translation_seconds,
                                ),
                                translated_texts=[],
                                translation_payload=item.translation_payload,
                                classification=item.classification,
                                manga_context=manga_context_payload,
                                error=translation_failures[item.page["id"]],
                            )
                            final_debug_records[item.page["id"]] = record
                            reporter.log(
                                f"FALLBACK-COPY {item.page['fileName']} -> {item.target_path.name} "
                                f"(translate failed: {translation_failures[item.page['id']]})"
                            )
                            continue

                        item.translation_payload = _normalize_translation_payload(
                            translated_by_page.get(item.page["id"], [])
                        )
                        item.translated_texts = item.translation_payload.get("translatedTexts") or []
                        stage_cache.save_translated(
                            item.source_path,
                            item.preprocessed_payload,
                            item.translated_texts,
                            item.translation_payload,
                        )

                    try:
                        result = _call_run_page_pipeline(
                            runtime,
                            item.page["id"],
                            item.page["sourcePath"],
                            model=model,
                            base_url=base_url,
                            api_key=api_key,
                            preprocessed_payload=item.preprocessed_payload,
                            translated_texts=item.translated_texts,
                            context_snapshot=batch_context_snapshot,
                            saber_session=saber_session,
                            translation_payload=item.translation_payload,
                        )
                        result = _with_batch_translation_timing(result, item.translation_seconds)
                        if item.translation_payload is not None and not isinstance(result.get("translation"), dict):
                            result = dict(result)
                            result["translation"] = item.translation_payload
                            result["ocrRetry"] = dict(item.translation_payload.get("ocrRetry") or _default_ocr_retry_state())
                        runtime.save_result(item.page["id"], result)
                        runtime.update_translated_path(item.page["id"], result["translatedImagePath"])
                        shutil.copyfile(result["translatedImagePath"], item.target_path)
                        counters["succeeded"] += 1
                        record = debug_writer.record_page(
                            page=item.page,
                            page_index=int(item.page.get("pageIndex") or str(item.page["id"]).split("-")[-1]),
                            total_pages=debug_total_pages,
                            source_path=item.source_path,
                            target_path=item.target_path,
                            status="translated",
                            preprocessed_payload=item.preprocessed_payload,
                            translated_texts=item.translated_texts,
                            translation_payload=item.translation_payload,
                            classification=item.classification,
                            manga_context=manga_context_payload,
                            result=result,
                        )
                        final_debug_records[item.page["id"]] = record
                        reporter.log(
                            f"OK   {item.page['fileName']} -> {item.target_path.name} "
                            f"({format_seconds(perf_counter() - page_started_at)})"
                        )
                    except Exception as error:
                        counters["failed"] += 1
                        record = debug_writer.record_page(
                            page=item.page,
                            page_index=int(item.page.get("pageIndex") or str(item.page["id"]).split("-")[-1]),
                            total_pages=debug_total_pages,
                            source_path=item.source_path,
                            target_path=item.target_path,
                            status="failed",
                            preprocessed_payload=item.preprocessed_payload,
                            translated_texts=item.translated_texts,
                            translation_payload=item.translation_payload,
                            classification=item.classification,
                            manga_context=manga_context_payload,
                            error=error,
                        )
                        final_debug_records[item.page["id"]] = record
                        reporter.log(f"FAIL {item.page['fileName']} ({error})")

                current_batch = next_batch

    total_elapsed = perf_counter() - started_at
    summary = {
        "total": len(pages),
        "succeeded": counters["succeeded"],
        "skipped": counters["skipped"],
        "failed": counters["failed"],
        "elapsedSeconds": total_elapsed,
    }
    records_for_finish = final_debug_records
    if selected_page_names:
        merged_records = dict(existing_debug_records)
        for record in final_debug_records.values():
            source_name = str(record.get("sourceName") or "").strip()
            if source_name:
                merged_records[source_name] = record
        records_for_finish = list(merged_records.values())
    debug_writer.finish(summary, records=records_for_finish, run_options=run_options)
    reporter.finish(
        total_count=len(pages),
        succeeded=counters["succeeded"],
        skipped=counters["skipped"],
        failed=counters["failed"],
        elapsed_seconds=total_elapsed,
    )
    return summary
