import csv
import json
from pathlib import Path
import sys

from translate_manga.cli.service import (
    BatchProgressReporter,
    find_missing_output_page_names,
    find_translation_failure_text_page_names,
    run_batch_translation,
    scan_input_images,
)
from translate_manga.cli.quality_review import (
    clear_quality_review_entries,
    read_quality_review_entries,
    run_quality_review,
)
from translate_manga.config.paths import find_project_root
from translate_manga.config.settings import (
    load_session_state,
    load_settings,
    resolve_path_value,
    resolve_scan_fix_translation_config,
    save_session_state,
)
from translate_manga.core.context.book_profile import split_pasted_paths
from translate_manga.core.natural_sort import natural_sort_key
from translate_manga.core.styles import normalize_style_id, resolve_style_profile
from translate_manga.core.translate.openai_compatible import is_translation_failure_text


_MAX_RETRY_ROUNDS = 5
_SKIPPED_EXISTING_CACHE_ONLY_REASONS = {
    "missing_cached_texts",
    "missing_ocr_text",
    "missing_translation_text",
    "translation_count_mismatch",
}
_STYLE_LABELS = {
    "style1": "Style 1 horizontal JP",
    "style2": "Style 2 vertical JP",
    "style3": "Style 3 horizontal EN",
    "auto": "Auto layout JP",
    "style_mm": "多模态AI辅助",
}
_STYLE_INPUT_ALIASES = {
    "1": "style1",
    "style1": "style1",
    "style_1": "style1",
    "horizontal": "style1",
    "2": "style2",
    "style2": "style2",
    "style_2": "style2",
    "vertical": "style2",
    "a": "auto",
    "auto": "auto",
    "style_auto": "auto",
    "3": "style3",
    "style3": "style3",
    "style_3": "style3",
    "m": "style_mm",
    "mm": "style_mm",
    "multimodal": "style_mm",
    "multi_modal": "style_mm",
    "style_mm": "style_mm",
    "style_multimodal": "style_mm",
    "多模态": "style_mm",
    "多模态ai辅助": "style_mm",
}


class _MemoryStream:
    def __init__(self, buffer):
        self._buffer = buffer

    def write(self, text):
        self._buffer.append(str(text))
        return len(str(text))

    def flush(self):
        return None


def _resolve_project_root(project_root=None):
    return Path(project_root) if project_root is not None else find_project_root(__file__)


def _clean_path_text(value):
    candidate = str(value or "").strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1].strip()
    return candidate


def _normalize_optional_path(value):
    candidate = _clean_path_text(value)
    if not candidate:
        return None
    return Path(candidate)


def _normalize_layout_mode(value, default="vertical"):
    candidate = str(value or "").strip()
    if candidate in {"horizontal", "vertical", "auto"}:
        return candidate
    return default


def _resolve_task_style_profile(task):
    task = task or {}
    return resolve_style_profile(task.get("style_id"), layout_mode=task.get("layout_mode"))


def _style_id_from_layout(layout_mode, default="style2"):
    candidate = _normalize_layout_mode(layout_mode, default=resolve_style_profile(default)["layout_mode"])
    return normalize_style_id(layout_mode=candidate)


def _resolve_default_task(project_root):
    settings = load_settings(project_root=project_root)
    paths = settings.get("paths") or {}
    render = settings.get("render") or {}
    pipeline = settings.get("pipeline") or {}
    input_dir = _normalize_optional_path(resolve_path_value(paths.get("input_dir"), project_root=project_root))
    style_profile = resolve_style_profile(render.get("style_id"), layout_mode=render.get("layout_mode") or "vertical")
    return {
        "input_dirs": [input_dir] if input_dir else [],
        "layout_mode": style_profile["layout_mode"],
        "style_id": style_profile["style_id"],
        "overwrite_existing": bool(pipeline.get("overwrite_existing", False)),
    }


def _resolve_current_task(project_root):
    task = _resolve_default_task(project_root)
    session = load_session_state(project_root=project_root)

    session_input_dirs = []
    for item in session.get("last_input_dirs") or []:
        candidate = _normalize_optional_path(item)
        if candidate:
            session_input_dirs.append(candidate)
    if not session_input_dirs and session.get("last_input_dir"):
        candidate = _normalize_optional_path(session.get("last_input_dir"))
        if candidate:
            session_input_dirs.append(candidate)

    if session_input_dirs:
        task["input_dirs"] = session_input_dirs
    if session.get("last_style_id"):
        style_profile = resolve_style_profile(session.get("last_style_id"), layout_mode=session.get("last_layout_mode"))
        task["style_id"] = style_profile["style_id"]
        task["layout_mode"] = style_profile["layout_mode"]
    elif session.get("last_layout_mode"):
        task["style_id"] = _style_id_from_layout(session.get("last_layout_mode"), default=task.get("style_id") or "style2")
        task["layout_mode"] = resolve_style_profile(task["style_id"])["layout_mode"]
    if isinstance(session.get("last_overwrite_existing"), bool):
        task["overwrite_existing"] = session["last_overwrite_existing"]
    return task


def _style_label(style_id=None, *, layout_mode=None):
    style_profile = resolve_style_profile(style_id, layout_mode=layout_mode)
    return _STYLE_LABELS.get(style_profile["style_id"], style_profile["style_id"])


def _overwrite_label(overwrite_existing):
    return "覆盖已输出" if overwrite_existing else "跳过已输出"


def _task_output_dir(input_dir):
    return Path(input_dir) / "out"


def _write_line(stream, text=""):
    stream.write(f"{text}\n")
    stream.flush()


def _render_menu(stream, task):
    input_dirs = task.get("input_dirs") or []
    _write_line(stream, "Translate Manga V2")
    if input_dirs:
        _write_line(stream, f"当前任务: {len(input_dirs)} 个目录")
        for input_dir in input_dirs[:5]:
            _write_line(stream, f"  - {input_dir} -> {_task_output_dir(input_dir)}")
        if len(input_dirs) > 5:
            _write_line(stream, f"  - ... 还有 {len(input_dirs) - 5} 个目录")
    else:
        _write_line(stream, "当前任务: (未设置)")
    _write_line(stream, f"当前样式: {_style_label(task.get('style_id'), layout_mode=task.get('layout_mode'))}")
    _write_line(stream, f"当前输出策略: {_overwrite_label(bool(task.get('overwrite_existing', False)))}")
    _write_line(stream, "1. 继续上次任务")
    _write_line(stream, "2. 新建任务")
    _write_line(stream, "3. 扫描并纠正错误")
    _write_line(stream, "4. 退出")


def _prompt_input_dirs(input_func, stream):
    _write_line(stream, "输入漫画目录，一行一个，直接回车结束。输出固定为每个目录下的 out。")
    directories = []
    while True:
        raw_value = input_func("输入目录: ").strip()
        if not raw_value:
            if directories:
                return directories
            _write_line(stream, "至少需要一个输入目录。")
            continue

        added = False
        for raw_path in split_pasted_paths(raw_value):
            candidate = _normalize_optional_path(raw_path)
            if candidate is None or not candidate.exists() or not candidate.is_dir():
                _write_line(stream, f"输入目录不存在: {candidate}")
                continue
            if candidate not in directories:
                directories.append(candidate)
                added = True
        if added:
            _write_line(stream, f"已加入 {len(directories)} 个目录。")


def _prompt_style_id(input_func, stream, default_style_id="style2"):
    default_profile = resolve_style_profile(default_style_id)
    default_choice = "M" if default_profile["style_id"] == "style_mm" else default_profile["style_id"].replace("style", "")
    while True:
        raw_value = input_func(
            "选择样式 "
            "[1=Style 1 horizontal JP / 2=Style 2 vertical JP / A=Auto JP / 3=Style 3 horizontal EN / M=多模态AI辅助 "
            f"/ 回车=上次({default_choice})]: "
        ).strip()
        if not raw_value:
            return default_profile["style_id"]
        style_id = _STYLE_INPUT_ALIASES.get(raw_value.lower())
        if style_id:
            return style_id
        _write_line(stream, "样式只能选 1、2、A、3 或 M。")


def _prompt_overwrite_existing(input_func, stream, default_overwrite_existing=False):
    default_value = bool(default_overwrite_existing)
    default_label = "覆盖" if default_value else "跳过"
    while True:
        raw_value = input_func(
            "输出策略 "
            f"[1=跳过已输出 / 2=覆盖已输出 / 回车=上次({default_label})]: "
        ).strip()
        if not raw_value:
            return default_value
        if raw_value == "1":
            return False
        if raw_value == "2":
            return True
        _write_line(stream, "输出策略只能选 1 或 2。")


def _prompt_layout_mode(input_func, stream, default_layout_mode="vertical"):
    style_id = _prompt_style_id(input_func, stream, _style_id_from_layout(default_layout_mode))
    return resolve_style_profile(style_id)["layout_mode"]


def _prompt_scan_task(input_func, stream, current_task):
    if _can_reuse(current_task):
        while True:
            raw_value = input_func("扫描范围 [1=使用上次任务 / 2=重新输入]: ").strip()
            if raw_value == "1":
                return current_task
            if raw_value == "2":
                break
            _write_line(stream, "扫描范围只能选 1 或 2。")
    else:
        _write_line(stream, "当前没有可复用任务，请输入要扫描的目录。")

    input_dirs = _prompt_input_dirs(input_func, stream)
    style_id = _prompt_style_id(input_func, stream, current_task.get("style_id") or _style_id_from_layout(current_task.get("layout_mode")))
    style_profile = resolve_style_profile(style_id)
    return {
        "input_dirs": input_dirs,
        "layout_mode": style_profile["layout_mode"],
        "style_id": style_profile["style_id"],
        "overwrite_existing": bool(current_task.get("overwrite_existing", False)),
    }


def _can_reuse(task):
    input_dirs = task.get("input_dirs") or []
    return bool(input_dirs) and all(Path(input_dir).exists() and Path(input_dir).is_dir() for input_dir in input_dirs)


def _save_task_session(task, project_root):
    input_dirs = list(task.get("input_dirs") or [])
    if not input_dirs:
        return
    first_input_dir = Path(input_dirs[0])
    style_profile = _resolve_task_style_profile(task)
    save_session_state(
        last_input_dirs=input_dirs,
        last_input_dir=first_input_dir,
        last_output_dir=_task_output_dir(first_input_dir),
        last_style_id=style_profile["style_id"],
        last_layout_mode=style_profile["layout_mode"],
        last_overwrite_existing=bool(task.get("overwrite_existing", False)),
        project_root=project_root,
    )


def _write_summary(stream, summary):
    _write_line(
        stream,
        "Summary: "
        f"total={summary['total']} "
        f"ok={summary['succeeded']} "
        f"skip={summary['skipped']} "
        f"fail={summary['failed']}",
    )


def _run_translation(input_dir, layout_mode, stream, *, launch_mode, style_id=None, overwrite_existing=False):
    summary = run_batch_translation(
        input_dir=Path(input_dir),
        output_dir=_task_output_dir(input_dir),
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=overwrite_existing,
        layout_mode=layout_mode,
        style_id=style_id,
        launch_mode=launch_mode,
        retry_review_pages=False,
    )
    _write_summary(stream, summary)
    return summary


def _run_retry_translation(
    input_dir,
    layout_mode,
    stream,
    *,
    launch_mode,
    style_id=None,
    retry_quality_review_pages=False,
    translation_config=None,
):
    translation_config = translation_config or {}
    summary = run_batch_translation(
        input_dir=Path(input_dir),
        output_dir=_task_output_dir(input_dir),
        reporter=BatchProgressReporter(stream=stream),
        model=translation_config.get("model"),
        base_url=translation_config.get("base_url"),
        api_key=translation_config.get("api_key"),
        overwrite_existing=True,
        layout_mode=layout_mode,
        style_id=style_id,
        launch_mode=launch_mode,
        retry_review_pages=True,
        retry_quality_review_pages=retry_quality_review_pages,
    )
    _write_summary(stream, summary)
    return summary


def _read_failed_translations(debug_root):
    failed_tsv_path = Path(debug_root) / "failed-translations.tsv"
    if not failed_tsv_path.exists():
        return None

    entries = []
    try:
        with failed_tsv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                source_name = str((row or {}).get("sourceName") or "").strip()
                if not source_name:
                    continue
                reasons = [
                    reason.strip()
                    for reason in str((row or {}).get("reasons") or "").split(",")
                    if reason.strip()
                ]
                entries.append(
                    {
                        "sourceName": source_name,
                        "reviewReasons": reasons,
                        "status": str((row or {}).get("status") or "").strip(),
                    }
                )
    except (OSError, csv.Error, UnicodeDecodeError):
        return []
    return entries


def _read_review_pages(debug_root):
    review_pages_path = Path(debug_root) / "review-pages.txt"
    if not review_pages_path.exists():
        return None

    entries = []
    try:
        for line in review_pages_path.read_text(encoding="utf-8").splitlines():
            source_name, _, raw_reasons = line.partition("\t")
            source_name = source_name.strip()
            if not source_name:
                continue
            reasons = [reason.strip() for reason in raw_reasons.split(",") if reason.strip()]
            entries.append({"sourceName": source_name, "reviewReasons": reasons})
    except (OSError, UnicodeDecodeError):
        return []
    return entries


def _read_quality_review_pages(output_dir):
    entries = []
    for entry in read_quality_review_entries(output_dir):
        source_name = str((entry or {}).get("sourceName") or "").strip()
        if not source_name:
            continue
        entries.append(
            {
                "sourceName": source_name,
                "reviewReasons": list((entry or {}).get("reviewReasons") or []),
            }
        )
    return entries


def _record_needs_review(record):
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


def _scan_page_debug_records(debug_root):
    pages_root = Path(debug_root) / "pages"
    if not pages_root.exists():
        return []

    entries = []
    for page_json_path in sorted(pages_root.glob("*.json")):
        try:
            record = json.loads(page_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not _record_needs_review(record):
            continue
        source_name = str(record.get("sourceName") or "").strip()
        if not source_name:
            continue
        entries.append(
            {
                "sourceName": source_name,
                "reviewReasons": list(record.get("reviewReasons") or []),
                "status": str(record.get("status") or "").strip(),
            }
        )
    return entries


def _scan_page_debug_source_names(debug_root):
    pages_root = Path(debug_root) / "pages"
    if not pages_root.exists():
        return set()

    names = set()
    for page_json_path in pages_root.glob("*.json"):
        try:
            record = json.loads(page_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        source_name = str(record.get("sourceName") or "").strip()
        if source_name:
            names.add(source_name)
    return names


def _collect_translation_text_failure_entries(input_dir, output_dir):
    debug_root = Path(output_dir) / "_debug"
    try:
        image_paths = scan_input_images(input_dir)
    except ValueError:
        return []
    names = find_translation_failure_text_page_names(
        image_paths,
        output_dir,
        existing_debug_page_names=_scan_page_debug_source_names(debug_root),
    )
    return [
        {"sourceName": source_name, "reviewReasons": ["translation_failure_placeholder"]}
        for source_name in sorted(names, key=natural_sort_key)
    ]


def _dedupe_review_entries(entries):
    deduped = []
    seen = set()
    for entry in entries or []:
        source_name = str((entry or {}).get("sourceName") or "").strip()
        if not source_name or source_name in seen:
            continue
        seen.add(source_name)
        deduped.append(
            {
                "sourceName": source_name,
                "reviewReasons": list((entry or {}).get("reviewReasons") or []),
            }
        )
    return deduped


def _record_has_cached_page_data(record):
    if not isinstance(record, dict):
        return False
    if record.get("originalTexts") or record.get("translatedTexts"):
        return True
    payload = record.get("preprocessedPayload")
    if isinstance(payload, dict) and (
        payload.get("bubbleCoords")
        or payload.get("originalTexts")
        or payload.get("ocrResults")
    ):
        return True
    translation = record.get("translation")
    if isinstance(translation, dict) and translation.get("translatedTexts"):
        return True
    return False


def _collect_cache_only_skipped_existing_sources(debug_root):
    pages_root = Path(debug_root) / "pages"
    if not pages_root.exists():
        return set()

    sources = set()
    for page_json_path in pages_root.glob("*.json"):
        try:
            record = json.loads(page_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if str(record.get("status") or "").strip().lower() != "skipped-existing":
            continue
        source_name = str(record.get("sourceName") or "").strip()
        if not source_name:
            continue
        reasons = {str(reason or "").strip() for reason in (record.get("reviewReasons") or []) if str(reason or "").strip()}
        if reasons and reasons.issubset(_SKIPPED_EXISTING_CACHE_ONLY_REASONS) and _record_has_cached_page_data(record):
            sources.add(source_name)
    return sources


def _is_cache_only_skipped_existing_entry(entry, skipped_existing_sources):
    source_name = str((entry or {}).get("sourceName") or "").strip()
    if source_name not in skipped_existing_sources:
        return False
    reasons = {str(reason or "").strip() for reason in ((entry or {}).get("reviewReasons") or []) if str(reason or "").strip()}
    if not reasons or not reasons.issubset(_SKIPPED_EXISTING_CACHE_ONLY_REASONS):
        return False
    status = str((entry or {}).get("status") or "").strip().lower()
    return not status or status == "skipped-existing"


def _collect_missing_output_entries(input_dir, output_dir):
    try:
        image_paths = scan_input_images(input_dir)
    except Exception:
        return []

    return [
        {"sourceName": source_name, "reviewReasons": ["missing_output"]}
        for source_name in sorted(find_missing_output_page_names(image_paths, output_dir), key=natural_sort_key)
    ]


def _collect_review_entry_source_counts(input_dir, output_dir, include_quality_review=False):
    debug_root = Path(output_dir) / "_debug"
    counts = {
        "failed": len(_dedupe_review_entries(_read_failed_translations(debug_root) or [])),
        "review": len(_dedupe_review_entries(_read_review_pages(debug_root) or [])),
        "debug": len(_dedupe_review_entries(_scan_page_debug_records(debug_root) or [])),
        "missing": len(_dedupe_review_entries(_collect_missing_output_entries(input_dir, output_dir) or [])),
    }
    if include_quality_review:
        counts["quality"] = len(_dedupe_review_entries(_read_quality_review_pages(output_dir)))
    return counts


def _format_review_entry_source_counts(counts):
    order = ["failed", "review", "debug", "missing", "quality"]
    return " ".join(f"{name}={int((counts or {}).get(name, 0))}" for name in order if name in (counts or {}))


def _collect_review_entries(input_dir, output_dir, include_quality_review=False):
    debug_root = Path(output_dir) / "_debug"
    entries = (
        list(_read_failed_translations(debug_root) or [])
        + list(_read_review_pages(debug_root) or [])
        + list(_scan_page_debug_records(debug_root) or [])
    )
    skipped_existing_sources = _collect_cache_only_skipped_existing_sources(debug_root)
    if skipped_existing_sources:
        entries = [
            entry
            for entry in entries
            if not _is_cache_only_skipped_existing_entry(entry, skipped_existing_sources)
        ]
    if include_quality_review:
        entries.extend(_read_quality_review_pages(output_dir))
    entries.extend(_collect_translation_text_failure_entries(input_dir, output_dir))
    entries.extend(_collect_missing_output_entries(input_dir, output_dir) or [])
    return _dedupe_review_entries(entries)


def _is_no_review_pages_error(error):
    return "No review pages found" in str(error)


def _classify_non_retryable_translation_error(error):
    normalized = str(error or "").strip().lower()
    if not normalized:
        return None
    if "insufficient balance" in normalized or "余额不足" in normalized:
        return "余额不足"
    if "error code: 402" in normalized or "status code: 402" in normalized or "http 402" in normalized:
        return "余额不足"
    return None


def _find_non_retryable_translation_error(output_dir, entries):
    source_names = {
        str((entry or {}).get("sourceName") or "").strip()
        for entry in entries or []
        if str((entry or {}).get("sourceName") or "").strip()
    }
    pages_dir = Path(output_dir) / "_debug" / "pages"
    if not pages_dir.exists():
        return None

    for page_path in sorted(pages_dir.glob("*.json"), key=lambda path: natural_sort_key(path.name)):
        try:
            record = json.loads(page_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        source_name = str((record or {}).get("sourceName") or "").strip()
        if source_names and source_name not in source_names:
            continue
        reason = _classify_non_retryable_translation_error((record or {}).get("error"))
        if reason:
            return {
                "sourceName": source_name or page_path.stem,
                "reason": reason,
            }
    return None


def _write_non_retryable_translation_error_report(stream, book_index, book_total, error_info):
    source_name = str((error_info or {}).get("sourceName") or "").strip() or "unknown"
    reason = str((error_info or {}).get("reason") or "").strip() or "不可重试错误"
    _write_line(
        stream,
        f"RETRY [{book_index}/{book_total}] stop: 翻译 API 返回{reason}，"
        f"停止后续重试 page={source_name}。请充值或更换可用接口后再扫描纠错。",
    )


def _write_remaining_report(stream, output_dir, entries):
    failed_tsv_path = Path(output_dir) / "_debug" / "failed-translations.tsv"
    _write_line(stream, f"仍有 {len(entries)} 页需要人工复查: {failed_tsv_path}")
    for entry in entries[:10]:
        reasons = ",".join(entry.get("reviewReasons") or []) or "unknown"
        _write_line(stream, f"  - {entry['sourceName']} ({reasons})")
    if len(entries) > 10:
        _write_line(stream, f"  - ... 还有 {len(entries) - 10} 页")


def _run_retry_rounds(
    input_dirs,
    layout_mode,
    stream,
    *,
    launch_mode,
    style_id=None,
    max_rounds=_MAX_RETRY_ROUNDS,
    include_quality_review=False,
    translation_config=None,
):
    remaining_by_output = {}
    book_total = len(input_dirs)
    for book_index, input_dir in enumerate(input_dirs, start=1):
        output_dir = _task_output_dir(input_dir)
        for round_index in range(1, max_rounds + 1):
            review_entries = _collect_review_entries(
                input_dir,
                output_dir,
                include_quality_review=include_quality_review,
            )
            if not review_entries:
                if round_index == 1:
                    _write_line(stream, f"RETRY [{book_index}/{book_total}] 没有需要纠正的页: {output_dir / '_debug'}")
                break

            _write_line(
                stream,
                f"RETRY [{book_index}/{book_total}] round={round_index}/{max_rounds} "
                f"review_pages={len(review_entries)} "
                f"sources={_format_review_entry_source_counts(_collect_review_entry_source_counts(input_dir, output_dir, include_quality_review=include_quality_review))} "
                f"output={output_dir}",
            )
            try:
                _run_retry_translation(
                    input_dir,
                    layout_mode,
                    stream,
                    launch_mode=launch_mode,
                    style_id=style_id,
                    retry_quality_review_pages=include_quality_review,
                    translation_config=translation_config,
                )
                if include_quality_review:
                    clear_quality_review_entries(
                        output_dir,
                        [entry.get("sourceName") for entry in review_entries],
                    )
                remaining_after_round = _collect_review_entries(
                    input_dir,
                    output_dir,
                    include_quality_review=include_quality_review,
                )
                if remaining_after_round:
                    non_retryable_error = _find_non_retryable_translation_error(output_dir, remaining_after_round)
                else:
                    non_retryable_error = None
                if non_retryable_error:
                    _write_non_retryable_translation_error_report(
                        stream,
                        book_index,
                        book_total,
                        non_retryable_error,
                    )
                    break
            except ValueError as error:
                if _is_no_review_pages_error(error):
                    break
                non_retryable_error = _classify_non_retryable_translation_error(error)
                if non_retryable_error:
                    _write_non_retryable_translation_error_report(
                        stream,
                        book_index,
                        book_total,
                        {"sourceName": None, "reason": non_retryable_error},
                    )
                    break
                _write_line(stream, f"RETRY [{book_index}/{book_total}] failed error={error}")
                break
            except Exception as error:
                non_retryable_error = _classify_non_retryable_translation_error(error)
                if non_retryable_error:
                    _write_non_retryable_translation_error_report(
                        stream,
                        book_index,
                        book_total,
                        {"sourceName": None, "reason": non_retryable_error},
                    )
                    break
                _write_line(stream, f"RETRY [{book_index}/{book_total}] failed error={error}")
                break

        remaining_entries = _collect_review_entries(
            input_dir,
            output_dir,
            include_quality_review=include_quality_review,
        )
        if remaining_entries:
            remaining_by_output[output_dir] = remaining_entries
            _write_remaining_report(stream, output_dir, remaining_entries)
        else:
            _write_line(stream, f"未发现遗留错误: {output_dir}")
    return remaining_by_output


def _run_full_task(task, stream, project_root):
    _save_task_session(task, project_root)
    input_dirs = list(task.get("input_dirs") or [])
    style_profile = _resolve_task_style_profile(task)
    layout_mode = style_profile["layout_mode"]
    style_id = style_profile["style_id"]
    overwrite_existing = bool(task.get("overwrite_existing", False))
    book_total = len(input_dirs)

    for book_index, input_dir in enumerate(input_dirs, start=1):
        _write_line(stream, f"BOOK [{book_index}/{book_total}] input={input_dir}")
        _write_line(stream, f"BOOK [{book_index}/{book_total}] output={_task_output_dir(input_dir)}")
        try:
            _run_translation(
                input_dir,
                layout_mode,
                stream,
                launch_mode="menu",
                style_id=style_id,
                overwrite_existing=overwrite_existing,
            )
        except Exception as error:
            _write_line(stream, f"BOOK [{book_index}/{book_total}] failed error={error}")
            continue
        _run_retry_rounds([input_dir], layout_mode, stream, launch_mode="menu-auto-retry", style_id=style_id)


def _write_quality_review_progress(stream, book_index, book_total, event):
    event_name = (event or {}).get("event")
    prefix = f"QUALITY REVIEW [{book_index}/{book_total}]"
    if event_name == "start":
        _write_line(
            stream,
            f"{prefix} pages={int((event or {}).get('totalPages') or 0)} "
            f"chunks={int((event or {}).get('totalChunks') or 0)}",
        )
        return
    if event_name == "chunk_start":
        _write_line(
            stream,
            f"{prefix} chunk={int((event or {}).get('currentChunk') or 0)}/"
            f"{int((event or {}).get('totalChunks') or 0)} "
            f"pages={int((event or {}).get('pageCount') or 0)} "
            f"range={(event or {}).get('firstSourceName') or '?'}..{(event or {}).get('lastSourceName') or '?'}",
        )
        return
    if event_name == "chunk_done":
        _write_line(
            stream,
            f"{prefix} chunk={int((event or {}).get('currentChunk') or 0)}/"
            f"{int((event or {}).get('totalChunks') or 0)} done "
            f"flagged_pages={int((event or {}).get('flaggedPages') or 0)}",
        )
        return
    if event_name == "done":
        _write_line(stream, f"{prefix} done flagged_pages={int((event or {}).get('flaggedPages') or 0)}")


def _run_quality_review_task(input_dirs, layout_mode, stream, *, style_id=None, project_root=None, translation_config=None):
    style_profile = resolve_style_profile(style_id, layout_mode=layout_mode)
    translation_config = translation_config or {}
    book_total = len(input_dirs)
    for book_index, input_dir in enumerate(input_dirs, start=1):
        output_dir = _task_output_dir(input_dir)
        _write_line(stream, f"QUALITY REVIEW [{book_index}/{book_total}] 通篇译文质检 start output={output_dir}")
        try:
            entries = run_quality_review(
                output_dir,
                model=translation_config.get("model"),
                base_url=translation_config.get("base_url"),
                api_key=translation_config.get("api_key"),
                style_profile=style_profile,
                project_root=project_root,
                progress_callback=lambda event, current_book=book_index, total_books=book_total: _write_quality_review_progress(
                    stream,
                    current_book,
                    total_books,
                    event,
                ),
            )
        except Exception as error:
            _write_line(stream, f"QUALITY REVIEW [{book_index}/{book_total}] failed error={error}")
            continue
        if not entries:
            _write_line(stream, f"QUALITY REVIEW [{book_index}/{book_total}] 未发现译文质量问题: {output_dir / '_debug'}")
            continue
        _write_line(
            stream,
            f"QUALITY REVIEW [{book_index}/{book_total}] flagged_pages={len(entries)} "
            f"report={output_dir / '_debug' / 'quality-review.tsv'}",
        )
        _run_retry_rounds(
            [input_dir],
            layout_mode,
            stream,
            launch_mode="menu-quality-review",
            style_id=style_id,
            include_quality_review=True,
            translation_config=translation_config,
        )


def _run_scan_and_fix_task(task, stream, project_root, include_quality_review=False):
    _save_task_session(task, project_root)
    input_dirs = list(task.get("input_dirs") or [])
    style_profile = _resolve_task_style_profile(task)
    layout_mode = style_profile["layout_mode"]
    scan_fix_translation = resolve_scan_fix_translation_config(
        settings=load_settings(project_root=project_root)
    )
    remaining = _run_retry_rounds(
        input_dirs,
        layout_mode,
        stream,
        launch_mode="menu-scan-fix",
        style_id=style_profile["style_id"],
        include_quality_review=False,
        translation_config=scan_fix_translation,
    )
    if not include_quality_review:
        return remaining
    if remaining:
        _write_line(stream, f"仍有 {len(remaining)} 本硬错误未修复；继续执行通篇译文质检，硬错误页仍会保留。")
    _run_quality_review_task(
        input_dirs,
        layout_mode,
        stream,
        style_id=style_profile["style_id"],
        project_root=project_root,
        translation_config=scan_fix_translation,
    )
    return remaining


def _prompt_scan_mode(input_func, stream):
    while True:
        raw_value = input_func("扫描模式 [1=只修复硬错误 / 2=硬错误+通篇译文质检(推荐) / 回车=2]: ").strip()
        if not raw_value or raw_value == "2":
            return "quality"
        if raw_value == "1":
            return "hard"
        _write_line(stream, "扫描模式只能选 1 或 2。")


def run_interactive_menu(input_func=input, output_stream=None, project_root=None):
    project_root = _resolve_project_root(project_root)
    output_stream = output_stream or sys.stdout

    while True:
        task = _resolve_current_task(project_root)
        _render_menu(output_stream, task)
        choice = input_func("Select: ").strip()

        if choice == "1":
            if not _can_reuse(task):
                _write_line(output_stream, "当前没有可继续的有效任务，请先新建任务。")
                continue
            task = dict(task)
            task["overwrite_existing"] = _prompt_overwrite_existing(
                input_func,
                output_stream,
                task.get("overwrite_existing", False),
            )
            _run_full_task(task, output_stream, project_root)
            continue

        if choice == "2":
            new_task = {
                "input_dirs": _prompt_input_dirs(input_func, output_stream),
            }
            style_id = _prompt_style_id(input_func, output_stream, task.get("style_id") or _style_id_from_layout(task.get("layout_mode")))
            style_profile = resolve_style_profile(style_id)
            new_task["style_id"] = style_profile["style_id"]
            new_task["layout_mode"] = style_profile["layout_mode"]
            new_task["overwrite_existing"] = _prompt_overwrite_existing(
                input_func,
                output_stream,
                task.get("overwrite_existing", False),
            )
            _run_full_task(new_task, output_stream, project_root)
            continue

        if choice == "3":
            scan_task = _prompt_scan_task(input_func, output_stream, task)
            scan_mode = _prompt_scan_mode(input_func, output_stream)
            _run_scan_and_fix_task(
                scan_task,
                output_stream,
                project_root,
                include_quality_review=scan_mode == "quality",
            )
            continue

        if choice == "4":
            return 0

        _write_line(output_stream, "无效选项，请重新输入。")


def main():
    return run_interactive_menu()


if __name__ == "__main__":
    raise SystemExit(main())
