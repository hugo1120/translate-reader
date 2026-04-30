import json
import shutil
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from src.app import create_app
from src.cli.cache import BatchStageCache
from src.cli.debug_artifacts import BatchDebugArtifactWriter
from src.config.settings import load_settings, resolve_ocr_config, resolve_path_value, resolve_pipeline_config, resolve_translation_config
from src.core.context.manga_context import load_or_generate_manga_context
from src.core.natural_sort import natural_sort_key
from src.core.pipeline.page_classifier import classify_preprocessed_page
from src.core.pipeline.service import (
    _build_translation_context,
    preprocess_page,
    run_page_pipeline,
    translate_texts as pipeline_translate_texts,
    translate_texts_multi_round as pipeline_translate_texts_multi_round,
)
from src.core.pipeline.filtering import load_image_size
from src.core.translate.openai_compatible import TRANSLATION_PROMPT_SIGNATURE
from src.integrations.saber_loader import SaberWorkerSession
from src.storage.cache_store import CacheStore
from src.storage.library_store import IMAGE_EXTENSIONS, LibraryStore


@dataclass
class PreparedPage:
    page: dict
    source_path: Path
    target_path: Path
    preprocessed_payload: dict
    classification: dict | None = None
    translated_texts: list[str] | None = None
    translation_payload: dict | None = None


def _empty_usage():
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "estimated": False,
    }


def _default_ocr_retry_state():
    return {
        "shouldRetry": False,
        "reasons": [],
        "attempted": False,
        "applied": False,
    }


def _build_legacy_translation_payload(translated_texts):
    texts = list(translated_texts or [])
    return {
        "translatedTexts": texts,
        "rounds": [
            {
                "name": "final",
                "translatedTexts": texts,
                "usage": _empty_usage(),
            }
        ],
        "tokenUsage": _empty_usage(),
        "ocrRetry": _default_ocr_retry_state(),
    }


def _normalize_translation_payload(payload):
    if not isinstance(payload, dict):
        return _build_legacy_translation_payload(payload or [])

    translated_texts = list(payload.get("translatedTexts") or [])
    rounds = []
    for item in payload.get("rounds") or []:
        if not isinstance(item, dict):
            continue
        rounds.append(
            {
                "name": item.get("name") or "final",
                "translatedTexts": list(item.get("translatedTexts") or []),
                "usage": dict(item.get("usage") or _empty_usage()),
            }
        )
    if not rounds:
        rounds = [
            {
                "name": "final",
                "translatedTexts": translated_texts,
                "usage": _empty_usage(),
            }
        ]

    return {
        "translatedTexts": translated_texts,
        "rounds": rounds,
        "tokenUsage": dict(payload.get("tokenUsage") or _empty_usage()),
        "ocrRetry": dict(payload.get("ocrRetry") or _default_ocr_retry_state()),
    }


def translate_texts(texts, model, base_url, api_key=None, context_snapshot=None):
    return pipeline_translate_texts(
        texts=texts,
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_snapshot=context_snapshot,
    )


_DEFAULT_TRANSLATE_TEXTS = translate_texts


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

    def finish(self, summary=None, records=None):
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


def _build_pages(image_paths):
    pages = []
    for index, image_path in enumerate(image_paths, start=1):
        pages.append(
            {
                "id": f"page-{index:04d}",
                "fileName": image_path.name,
                "sourcePath": str(image_path),
                "translatedPath": None,
                "status": "idle",
                "cacheKey": str(uuid.uuid4()),
            }
        )
    return pages


def _default_cache_root():
    return Path(__file__).resolve().parents[2] / ".cache" / "translate_manga_cli"


def _build_preprocess_signature(settings):
    payload = {
        "version": "preprocess-v1",
        "ocr": resolve_ocr_config(settings=settings),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _resolve_cli_settings():
    settings = load_settings()
    translation = resolve_translation_config(settings=settings)
    paths = settings.get("paths") or {}
    pipeline = resolve_pipeline_config(settings=settings)
    render = settings.get("render") or {}
    return {
        "translation": translation,
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
        "preprocess_signature": _build_preprocess_signature(settings),
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
    app,
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
                app,
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


def _count_page_chars(preprocessed_payload):
    texts = preprocessed_payload.get("originalTexts", []) or []
    return sum(len((text or "").strip()) for text in texts)


def _count_page_texts(preprocessed_payload):
    return len(preprocessed_payload.get("originalTexts", []) or [])


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

    flat_texts = []
    spans = []
    weights = []
    for item in pending_pages:
        texts = item.preprocessed_payload.get("originalTexts", []) or []
        spans.append((item.page["id"], len(flat_texts), len(texts)))
        weights.append(max(1, _count_page_chars(item.preprocessed_payload) or len(texts) or 1))
        flat_texts.extend(texts)

    translate_kwargs = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
    if (
        context_snapshot.get("confirmedTranslations")
        or context_snapshot.get("glossary")
        or str(context_snapshot.get("mangaContext") or "").strip()
    ):
        translate_kwargs["context_snapshot"] = context_snapshot

    translated_flat_payload = _normalize_translation_payload(
        _call_translate_texts_multi_round(texts=flat_texts, **translate_kwargs)
    )
    translated_by_page = {}
    total_weight = sum(weights)
    for index, (page_id, start, count) in enumerate(spans):
        translated_by_page[page_id] = _slice_translation_payload(
            translated_flat_payload,
            start,
            count,
            weights[index],
            total_weight,
        )
    return translated_by_page


def _copy_original_page(source_path, target_path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)


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
                translated_by_page[item.page["id"]] = _translate_page_lightweight(item, model, base_url, api_key, reporter)
            except Exception as fallback_error:
                failures[item.page["id"]] = fallback_error
                reporter.log(f"TRANSLATE fallback-light fail {item.page['fileName']} error={fallback_error}")

    return translated_by_page, failures


def _translate_page_lightweight(item, model, base_url, api_key, reporter):
    reporter.log(f"TRANSLATE fallback-light {item.page['fileName']}")
    texts = item.preprocessed_payload.get("originalTexts", []) or []
    attempts = [
        {
            "texts": texts,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "context_snapshot": None,
        },
        {
            "texts": texts,
            "model": model,
            "base_url": base_url,
            "context_snapshot": None,
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

    return _build_legacy_translation_payload(translated)


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
):
    prepared_pages = []
    batch_chars = 0

    while start_index < len(pages) and len(prepared_pages) < translate_batch_size:
        page = pages[start_index]
        current_index = start_index + 1
        start_index += 1

        source_path = Path(page["sourcePath"])
        target_path = build_output_path(source_path, output_dir, numeric_width=numeric_output_width)
        cached_stage = stage_cache.load_best(source_path)
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
            counters["skipped"] += 1
            record = debug_writer.record_page(
                page=page,
                page_index=current_index,
                total_pages=len(pages),
                source_path=source_path,
                target_path=target_path,
                status="skipped-existing",
                preprocessed_payload=None,
                translated_texts=None,
                translation_payload=None,
                classification=None,
                manga_context=manga_context_payload,
            )
            final_debug_records[page["id"]] = record
            reporter.log(f"SKIP {page['fileName']} -> {target_path.name} (already exists)")
            continue

        if cached_stage is not None:
            preprocessed_payload = cached_stage["preprocessed"]
            translated_texts = cached_stage.get("translatedTexts")
            translation_payload = cached_stage.get("translationPayload")
            reporter.log(
                f"PREP-CACHE {page['fileName']} "
                f"stage={cached_stage.get('stage', 'preprocessed')} "
                f"texts={_count_page_texts(preprocessed_payload)} "
                f"chars={_count_page_chars(preprocessed_payload)}"
            )
        else:
            reporter.log(f"PREP {page['fileName']} start")
            preprocessed_payload = preprocess_page(page["sourcePath"], saber_session=saber_session)
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
        if preprocessed_payload is not None:
            classification = classify_preprocessed_page(
                page_index=current_index,
                total_pages=len(pages),
                image_size=load_image_size(source_path),
                preprocessed_payload=preprocessed_payload,
                skip_frontmatter=skip_frontmatter,
            )

        if target_path.exists() and not overwrite_existing:
            counters["skipped"] += 1
            record = debug_writer.record_page(
                page=page,
                page_index=current_index,
                total_pages=len(pages),
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
                page_index=current_index,
                total_pages=len(pages),
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
):
    cli_config = _resolve_cli_settings()
    translation_config = cli_config["translation"]
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
    workspace_root = workspace_root or path_config["workspace_root"]
    cache_root = cache_root or path_config["cache_root"]
    layout_mode = str(layout_mode or render_config["layout_mode"]).strip() or "vertical"

    reporter = reporter or BatchProgressReporter()
    image_paths = scan_input_images(input_dir)
    if not image_paths:
        raise ValueError("No supported image files found in input folder.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manga_context_payload = None
    try:
        manga_context_payload = load_or_generate_manga_context(
            input_dir,
            auto_generate=pipeline_config.get("auto_generate_manga_context", True),
            pipeline_config=pipeline_config,
        )
    except Exception:
        manga_context_payload = None

    started_at = perf_counter()
    counters = {
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
    }
    final_debug_records = {}
    pages = _build_pages(image_paths)
    numeric_output_width = _resolve_numeric_output_width(image_paths)
    stage_cache = BatchStageCache(
        cache_root=cache_root or _default_cache_root(),
        input_dir=input_dir,
        model=model,
        base_url=base_url,
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
        preprocess_signature=cli_config["preprocess_signature"],
    )
    debug_writer = BatchDebugArtifactWriter(output_dir) if pipeline_config["debug_output"] else NullBatchDebugArtifactWriter()

    temp_kwargs = {"prefix": "translate-manga-cli-"}
    if workspace_root is not None:
        workspace_parent = Path(workspace_root)
        workspace_parent.mkdir(parents=True, exist_ok=True)
        temp_kwargs["dir"] = str(workspace_parent)

    with tempfile.TemporaryDirectory(**temp_kwargs) as data_root:
        app = create_app({"DATA_ROOT": data_root, "TESTING": True})
        app.config["CLI_LAYOUT_MODE_OVERRIDE"] = layout_mode
        with app.app_context():
            library_store = LibraryStore(app)
            library_store.seed_pages(pages)
            cache_store = CacheStore(app)

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
                )

                while current_batch:
                    batch_context_snapshot = _build_translation_context(app, current_batch[0].page["id"])
                    batch_context_snapshot = {
                        **batch_context_snapshot,
                        "mangaContext": str((manga_context_payload or {}).get("content") or "").strip(),
                    }
                    translation_future = None
                    translation_started_at = None
                    pending_names = [item.page["fileName"] for item in current_batch if item.translated_texts is None]
                    if any(item.translated_texts is None for item in current_batch):
                        translation_started_at = perf_counter()
                        reporter.log(
                            f"TRANSLATE start pages={', '.join(pending_names)} "
                            f"texts={sum(_count_page_texts(item.preprocessed_payload) for item in current_batch if item.translated_texts is None)} "
                            f"chars={sum(_count_page_chars(item.preprocessed_payload) for item in current_batch if item.translated_texts is None)}"
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
                    )

                    translated_by_page = {}
                    translation_failures = {}
                    if translation_future is not None:
                        try:
                            translated_by_page = translation_future.result()
                            reporter.log(
                                f"TRANSLATE done pages={', '.join(pending_names)} "
                                f"({format_seconds(perf_counter() - translation_started_at)})"
                            )
                        except Exception as error:
                            reporter.log(
                                f"TRANSLATE fail pages={', '.join(pending_names)} "
                                f"({format_seconds(perf_counter() - translation_started_at)}) "
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

                    for item in current_batch:
                        page_started_at = perf_counter()
                        reporter.log(f"RENDER {item.page['fileName']} start")

                        if item.translated_texts is None:
                            if item.page["id"] in translation_failures:
                                _copy_original_page(item.source_path, item.target_path)
                                counters["failed"] += 1
                                record = debug_writer.record_page(
                                    page=item.page,
                                    page_index=int(str(item.page["id"]).split("-")[-1]),
                                    total_pages=len(pages),
                                    source_path=item.source_path,
                                    target_path=item.target_path,
                                    status="failed",
                                    preprocessed_payload=item.preprocessed_payload,
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
                                app,
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
                            if item.translation_payload is not None and not isinstance(result.get("translation"), dict):
                                result = dict(result)
                                result["translation"] = item.translation_payload
                                result["ocrRetry"] = dict(item.translation_payload.get("ocrRetry") or _default_ocr_retry_state())
                            cache_store.save_result(item.page["id"], result)
                            library_store.update_translated_path(item.page["id"], result["translatedImagePath"])
                            shutil.copyfile(result["translatedImagePath"], item.target_path)
                            counters["succeeded"] += 1
                            record = debug_writer.record_page(
                                page=item.page,
                                page_index=int(str(item.page["id"]).split("-")[-1]),
                                total_pages=len(pages),
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
                                page_index=int(str(item.page["id"]).split("-")[-1]),
                                total_pages=len(pages),
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
    debug_writer.finish(summary, records=final_debug_records)
    reporter.finish(
        total_count=len(pages),
        succeeded=counters["succeeded"],
        skipped=counters["skipped"],
        failed=counters["failed"],
        elapsed_seconds=total_elapsed,
    )
    return summary
