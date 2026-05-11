import csv
import json
from pathlib import Path
import sys

from translate_manga.cli.service import (
    BatchProgressReporter,
    find_missing_output_page_names,
    run_batch_translation,
    scan_input_images,
)
from translate_manga.config.paths import find_project_root
from translate_manga.config.settings import load_session_state, load_settings, resolve_path_value, save_session_state
from translate_manga.core.context.book_profile import split_pasted_paths
from translate_manga.core.natural_sort import natural_sort_key
from translate_manga.core.styles import normalize_style_id, resolve_style_profile
from translate_manga.core.translate.openai_compatible import TRANSLATION_FAILURE_TEXT


_MAX_RETRY_ROUNDS = 5
_STYLE_LABELS = {
    "style1": "Style 1 horizontal JP",
    "style2": "Style 2 vertical JP",
    "style3": "Style 3 horizontal EN",
    "auto": "Auto layout JP",
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
    "auto": "auto",
    "3": "style3",
    "style3": "style3",
    "style_3": "style3",
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
    if candidate in {"horizontal", "vertical"}:
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
    input_dir = _normalize_optional_path(resolve_path_value(paths.get("input_dir"), project_root=project_root))
    style_profile = resolve_style_profile(render.get("style_id"), layout_mode=render.get("layout_mode") or "vertical")
    return {
        "input_dirs": [input_dir] if input_dir else [],
        "layout_mode": style_profile["layout_mode"],
        "style_id": style_profile["style_id"],
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
    return task


def _style_label(style_id=None, *, layout_mode=None):
    style_profile = resolve_style_profile(style_id, layout_mode=layout_mode)
    return _STYLE_LABELS.get(style_profile["style_id"], style_profile["style_id"])


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
    default_choice = default_profile["style_id"].replace("style", "")
    while True:
        raw_value = input_func(
            "选择样式 "
            "[1=Style 1 horizontal JP / 2=Style 2 vertical JP / 3=Style 3 horizontal EN "
            f"/ 回车=上次({default_choice})]: "
        ).strip()
        if not raw_value:
            return default_profile["style_id"]
        style_id = _STYLE_INPUT_ALIASES.get(raw_value.lower())
        if style_id:
            return style_id
        _write_line(stream, "样式只能选 1、2 或 3。")


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
    return {"input_dirs": input_dirs, "layout_mode": style_profile["layout_mode"], "style_id": style_profile["style_id"]}


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
        last_overwrite_existing=False,
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


def _run_translation(input_dir, layout_mode, stream, *, launch_mode, style_id=None):
    summary = run_batch_translation(
        input_dir=Path(input_dir),
        output_dir=_task_output_dir(input_dir),
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=False,
        layout_mode=layout_mode,
        style_id=style_id,
        launch_mode=launch_mode,
        retry_review_pages=False,
    )
    _write_summary(stream, summary)
    return summary


def _run_retry_translation(input_dir, layout_mode, stream, *, launch_mode, style_id=None):
    summary = run_batch_translation(
        input_dir=Path(input_dir),
        output_dir=_task_output_dir(input_dir),
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=True,
        layout_mode=layout_mode,
        style_id=style_id,
        launch_mode=launch_mode,
        retry_review_pages=True,
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
                entries.append({"sourceName": source_name, "reviewReasons": reasons})
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
    return any(str(text or "").strip() == TRANSLATION_FAILURE_TEXT for text in translated_texts)


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
        entries.append({"sourceName": source_name, "reviewReasons": list(record.get("reviewReasons") or [])})
    return entries


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


def _collect_missing_output_entries(input_dir, output_dir):
    try:
        image_paths = scan_input_images(input_dir)
    except Exception:
        return []

    return [
        {"sourceName": source_name, "reviewReasons": ["missing_output"]}
        for source_name in sorted(find_missing_output_page_names(image_paths, output_dir), key=natural_sort_key)
    ]


def _collect_review_entries(input_dir, output_dir):
    debug_root = Path(output_dir) / "_debug"
    return _dedupe_review_entries(
        list(_read_failed_translations(debug_root) or [])
        + list(_read_review_pages(debug_root) or [])
        + list(_scan_page_debug_records(debug_root) or [])
        + list(_collect_missing_output_entries(input_dir, output_dir) or [])
    )


def _is_no_review_pages_error(error):
    return "No review pages found" in str(error)


def _write_remaining_report(stream, output_dir, entries):
    failed_tsv_path = Path(output_dir) / "_debug" / "failed-translations.tsv"
    _write_line(stream, f"仍有 {len(entries)} 页需要人工复查: {failed_tsv_path}")
    for entry in entries[:10]:
        reasons = ",".join(entry.get("reviewReasons") or []) or "unknown"
        _write_line(stream, f"  - {entry['sourceName']} ({reasons})")
    if len(entries) > 10:
        _write_line(stream, f"  - ... 还有 {len(entries) - 10} 页")


def _run_retry_rounds(input_dirs, layout_mode, stream, *, launch_mode, style_id=None, max_rounds=_MAX_RETRY_ROUNDS):
    remaining_by_output = {}
    book_total = len(input_dirs)
    for book_index, input_dir in enumerate(input_dirs, start=1):
        output_dir = _task_output_dir(input_dir)
        for round_index in range(1, max_rounds + 1):
            review_entries = _collect_review_entries(input_dir, output_dir)
            if not review_entries:
                if round_index == 1:
                    _write_line(stream, f"RETRY [{book_index}/{book_total}] 没有需要纠正的页: {output_dir / '_debug'}")
                break

            _write_line(
                stream,
                f"RETRY [{book_index}/{book_total}] round={round_index}/{max_rounds} "
                f"review_pages={len(review_entries)} output={output_dir}",
            )
            try:
                _run_retry_translation(input_dir, layout_mode, stream, launch_mode=launch_mode, style_id=style_id)
            except ValueError as error:
                if _is_no_review_pages_error(error):
                    break
                _write_line(stream, f"RETRY [{book_index}/{book_total}] failed error={error}")
                break
            except Exception as error:
                _write_line(stream, f"RETRY [{book_index}/{book_total}] failed error={error}")
                break

        remaining_entries = _collect_review_entries(input_dir, output_dir)
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
    book_total = len(input_dirs)

    for book_index, input_dir in enumerate(input_dirs, start=1):
        _write_line(stream, f"BOOK [{book_index}/{book_total}] input={input_dir}")
        _write_line(stream, f"BOOK [{book_index}/{book_total}] output={_task_output_dir(input_dir)}")
        try:
            _run_translation(input_dir, layout_mode, stream, launch_mode="menu", style_id=style_id)
        except Exception as error:
            _write_line(stream, f"BOOK [{book_index}/{book_total}] failed error={error}")
            continue
        _run_retry_rounds([input_dir], layout_mode, stream, launch_mode="menu-auto-retry", style_id=style_id)


def _run_scan_and_fix_task(task, stream, project_root):
    _save_task_session(task, project_root)
    input_dirs = list(task.get("input_dirs") or [])
    style_profile = _resolve_task_style_profile(task)
    layout_mode = style_profile["layout_mode"]
    _run_retry_rounds(input_dirs, layout_mode, stream, launch_mode="menu-scan-fix", style_id=style_profile["style_id"])


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
            _run_full_task(new_task, output_stream, project_root)
            continue

        if choice == "3":
            scan_task = _prompt_scan_task(input_func, output_stream, task)
            _run_scan_and_fix_task(scan_task, output_stream, project_root)
            continue

        if choice == "4":
            return 0

        _write_line(output_stream, "无效选项，请重新输入。")


def main():
    return run_interactive_menu()


if __name__ == "__main__":
    raise SystemExit(main())
