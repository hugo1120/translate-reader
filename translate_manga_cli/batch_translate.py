from pathlib import Path

from src.cli.service import run_batch_translation
from src.config.settings import load_settings


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


def main():
    settings = load_settings()
    path_settings = settings.get("paths") or {}

    print("Translate Manga CLI")
    print("Use config/defaults.json or config/local.json to set default folders.")
    print()

    configured_input = str(path_settings.get("input_dir") or "").strip()
    configured_output = str(path_settings.get("output_dir") or "").strip()
    if configured_input and configured_output:
        input_dir = Path(configured_input)
        output_dir = Path(configured_output)
        if not input_dir.exists() or not input_dir.is_dir():
            raise SystemExit(f"Configured input folder not found: {input_dir}")
    else:
        print("Enter the source image folder and the output folder.")
        print()
        input_dir = _prompt_path("Input folder", must_exist=True)
        output_dir = _prompt_path("Output folder", must_exist=False)

    try:
        summary = run_batch_translation(input_dir=input_dir, output_dir=output_dir)
    except Exception as error:
        print()
        print(f"Batch translation failed: {error}")
        raise SystemExit(1) from error

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
