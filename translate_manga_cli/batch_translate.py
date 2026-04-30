from pathlib import Path

from src.cli.service import run_batch_translation
from src.config.settings import load_session_state, load_settings, resolve_path_value, save_session_state


def _project_root():
    return Path(__file__).resolve().parent


def _resolve_runtime_path(value):
    resolved = resolve_path_value(value, project_root=_project_root())
    if resolved:
        return Path(resolved)
    return Path(str(value or "").strip())


def _prompt_path(label, must_exist=False):
    while True:
        raw = input(f"{label}: ").strip().strip('"').strip("'")
        if not raw:
            print("Path cannot be empty.")
            continue

        path = Path(raw)
        if must_exist and (not path.exists() or not path.is_dir()):
            print(f"Folder not found: {path}")
            continue
        return path


def _prompt_choice(prompt, choices):
    allowed = {str(item) for item in choices}
    while True:
        raw = input(f"{prompt}: ").strip()
        if raw in allowed:
            return raw
        print(f"Please enter one of: {', '.join(sorted(allowed))}")


def _resolve_layout_mode(choice, default_layout_mode="vertical"):
    if choice == "1":
        return "horizontal"
    if choice == "2":
        return "vertical"
    return default_layout_mode


def main():
    settings = load_settings()
    path_settings = settings.get("paths") or {}
    render_settings = settings.get("render") or {}
    session_state = load_session_state()

    print("Translate Manga CLI")
    print("1. Reuse last input/output")
    print("2. Choose input/output again")
    print()

    configured_input = str(path_settings.get("input_dir") or "").strip()
    configured_output = str(path_settings.get("output_dir") or "").strip()
    session_input = str(session_state.get("last_input_dir") or "").strip()
    session_output = str(session_state.get("last_output_dir") or "").strip()
    default_layout_mode = str(session_state.get("last_layout_mode") or render_settings.get("layout_mode") or "vertical").strip() or "vertical"
    has_reusable_session = bool(session_input and session_output)

    if configured_input and configured_output and not has_reusable_session:
        input_dir = _resolve_runtime_path(configured_input)
        output_dir = _resolve_runtime_path(configured_output)
        layout_mode = default_layout_mode
        if not input_dir.exists() or not input_dir.is_dir():
            raise SystemExit(f"Configured input folder not found: {input_dir}")
    else:
        run_mode = "1" if has_reusable_session else "2"
        if has_reusable_session:
            print(f"Last input : {session_input}")
            print(f"Last output: {session_output}")
            print(f"Last style : {'2' if default_layout_mode == 'vertical' else '1'}")
            run_mode = _prompt_choice("Choose mode (1 reuse, 2 reset)", ["1", "2"])

        if run_mode == "1":
            input_dir = _resolve_runtime_path(session_input)
            output_dir = _resolve_runtime_path(session_output)
            layout_mode = default_layout_mode
            if not input_dir.exists() or not input_dir.is_dir():
                raise SystemExit(f"Last input folder not found: {input_dir}")
        else:
            print("Enter the source image folder and the output folder.")
            print()
            input_dir = _prompt_path("Input folder", must_exist=True)
            output_dir = _prompt_path("Output folder", must_exist=False)
            print()
            print("Layout style")
            print("1. Horizontal")
            print("2. Vertical RTL")
            layout_mode = _resolve_layout_mode(_prompt_choice("Choose style", ["1", "2"]), default_layout_mode=default_layout_mode)

    try:
        summary = run_batch_translation(input_dir=input_dir, output_dir=output_dir, layout_mode=layout_mode)
    except Exception as error:
        print()
        print(f"Batch translation failed: {error}")
        raise SystemExit(1) from error

    save_session_state(
        last_input_dir=str(input_dir),
        last_output_dir=str(output_dir),
        last_layout_mode=layout_mode,
    )

    print()
    print(
        "Summary: "
        f"total={summary['total']} "
        f"ok={summary['succeeded']} "
        f"skip={summary['skipped']} "
        f"fail={summary['failed']}"
    )


if __name__ == "__main__":
    main()
