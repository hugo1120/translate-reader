from pathlib import Path
import sys

from src.cli.service import BatchProgressReporter, run_batch_translation
from src.config.settings import load_session_state, load_settings, resolve_path_value, save_session_state


_STYLE_LABELS = {
    "horizontal": "Style 1",
    "vertical": "Style 2",
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
    return Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]


def _normalize_optional_path(value):
    candidate = str(value or "").strip()
    if not candidate:
        return None
    return Path(candidate)


def _resolve_default_state(project_root):
    settings = load_settings(project_root=project_root)
    paths = settings.get("paths") or {}
    render = settings.get("render") or {}
    pipeline = settings.get("pipeline") or {}
    return {
        "input_dir": _normalize_optional_path(resolve_path_value(paths.get("input_dir"), project_root=project_root)),
        "output_dir": _normalize_optional_path(resolve_path_value(paths.get("output_dir"), project_root=project_root)),
        "layout_mode": str(render.get("layout_mode") or "vertical").strip() or "vertical",
        "overwrite_existing": bool(pipeline.get("overwrite_existing", False)),
    }


def _resolve_current_state(project_root):
    state = _resolve_default_state(project_root)
    session = load_session_state(project_root=project_root)
    if session.get("last_input_dir"):
        state["input_dir"] = _normalize_optional_path(session.get("last_input_dir"))
    if session.get("last_output_dir"):
        state["output_dir"] = _normalize_optional_path(session.get("last_output_dir"))
    if session.get("last_layout_mode"):
        state["layout_mode"] = str(session.get("last_layout_mode")).strip() or state["layout_mode"]
    if "last_overwrite_existing" in session:
        state["overwrite_existing"] = bool(session.get("last_overwrite_existing"))
    return state


def _style_label(layout_mode):
    return _STYLE_LABELS.get(layout_mode, str(layout_mode or "vertical"))


def _overwrite_label(overwrite_existing):
    return "覆盖已有输出" if overwrite_existing else "跳过已有输出"


def _write_line(stream, text=""):
    stream.write(f"{text}\n")
    stream.flush()


def _render_menu(stream, state):
    _write_line(stream, "Translate Manga CLI")
    _write_line(stream, f"Current input: {state['input_dir'] or '(未设置)'}")
    _write_line(stream, f"Current output: {state['output_dir'] or '(未设置)'}")
    _write_line(stream, f"Current style: {_style_label(state['layout_mode'])} ({state['layout_mode']})")
    _write_line(stream, f"Current overwrite: {_overwrite_label(state['overwrite_existing'])}")
    _write_line(stream, "1. Reuse 上次配置并开始")
    _write_line(stream, "2. Reset 重新设置并开始")
    _write_line(stream, "3. Exit")


def _prompt_existing_directory(input_func, stream, prompt_text):
    while True:
        raw_value = input_func(prompt_text).strip()
        candidate = Path(raw_value)
        if candidate.exists() and candidate.is_dir():
            return candidate
        _write_line(stream, f"输入目录不存在: {candidate}")


def _prompt_output_directory(input_func, stream, prompt_text):
    while True:
        raw_value = input_func(prompt_text).strip()
        if raw_value:
            return Path(raw_value)
        _write_line(stream, "输出目录不能为空。")


def _prompt_layout_mode(input_func, stream):
    while True:
        raw_value = input_func("选择样式 [1=Style 1 horizontal / 2=Style 2 vertical]: ").strip()
        if raw_value == "1":
            return "horizontal"
        if raw_value == "2":
            return "vertical"
        _write_line(stream, "样式只能选 1 或 2。")


def _prompt_overwrite_existing(input_func, stream):
    while True:
        raw_value = input_func("覆盖策略 [1=跳过已有输出 / 2=覆盖已有输出]: ").strip()
        if raw_value == "1":
            return False
        if raw_value == "2":
            return True
        _write_line(stream, "覆盖策略只能选 1 或 2。")


def _can_reuse(state):
    input_dir = state.get("input_dir")
    output_dir = state.get("output_dir")
    return bool(input_dir and output_dir and input_dir.exists() and input_dir.is_dir())


def _run_translation(state, stream, project_root):
    save_session_state(
        last_input_dir=state["input_dir"],
        last_output_dir=state["output_dir"],
        last_layout_mode=state["layout_mode"],
        last_overwrite_existing=state["overwrite_existing"],
        project_root=project_root,
    )
    summary = run_batch_translation(
        input_dir=state["input_dir"],
        output_dir=state["output_dir"],
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=state["overwrite_existing"],
        layout_mode=state["layout_mode"],
        launch_mode="menu",
    )
    _write_line(
        stream,
        "Summary: "
        f"total={summary['total']} "
        f"ok={summary['succeeded']} "
        f"skip={summary['skipped']} "
        f"fail={summary['failed']}",
    )


def run_interactive_menu(input_func=input, output_stream=None, project_root=None):
    project_root = _resolve_project_root(project_root)
    output_stream = output_stream or sys.stdout

    while True:
        state = _resolve_current_state(project_root)
        _render_menu(output_stream, state)
        choice = input_func("Select: ").strip()

        if choice == "1":
            if not _can_reuse(state):
                _write_line(output_stream, "当前没有可复用的有效配置，请先 Reset。")
                continue
            try:
                _run_translation(state, output_stream, project_root)
            except Exception as error:
                _write_line(output_stream, f"Batch translation failed: {error}")
            continue

        if choice == "2":
            state = {
                "input_dir": _prompt_existing_directory(input_func, output_stream, "输入目录: "),
                "output_dir": _prompt_output_directory(input_func, output_stream, "输出目录: "),
                "layout_mode": _prompt_layout_mode(input_func, output_stream),
                "overwrite_existing": _prompt_overwrite_existing(input_func, output_stream),
            }
            try:
                _run_translation(state, output_stream, project_root)
            except Exception as error:
                _write_line(output_stream, f"Batch translation failed: {error}")
            continue

        if choice == "3":
            return 0

        _write_line(output_stream, "无效选项，请重新输入。")


def main():
    return run_interactive_menu()


if __name__ == "__main__":
    raise SystemExit(main())
