from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

from src.cli.service import run_batch_translation
from src.config.settings import load_settings, resolve_path_value


def _write(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _default_log_path() -> Path:
    return _project_root() / "logs" / "batch-live.log"


def _resolve_default_paths() -> tuple[Path, Path]:
    settings = load_settings()
    paths = settings.get("paths") or {}
    input_value = str(paths.get("input_dir") or "").strip()
    output_value = str(paths.get("output_dir") or "").strip()
    if not input_value:
        raise ValueError("config/local.json is missing paths.input_dir")
    if not output_value:
        raise ValueError("config/local.json is missing paths.output_dir")
    project_root = _project_root()
    resolved_input = resolve_path_value(input_value, project_root=project_root)
    resolved_output = resolve_path_value(output_value, project_root=project_root)
    return Path(resolved_input), Path(resolved_output)


class FileReporter:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def update(self, current_index, total_count, current_name, succeeded, skipped, failed, elapsed_seconds):
        _write(
            self.log_path,
            (
                f"UPDATE {current_index}/{total_count} {current_name} "
                f"ok={succeeded} skip={skipped} fail={failed} elapsed={elapsed_seconds:.2f}"
            ),
        )

    def log(self, message):
        _write(self.log_path, f"LOG {message}")

    def finish(self, total_count, succeeded, skipped, failed, elapsed_seconds):
        _write(
            self.log_path,
            f"FINISH total={total_count} ok={succeeded} skip={skipped} fail={failed} elapsed={elapsed_seconds:.2f}",
        )


def main() -> int:
    if len(sys.argv) >= 3:
        input_dir = Path(sys.argv[1])
        output_dir = Path(sys.argv[2])
        log_path = Path(sys.argv[3]) if len(sys.argv) >= 4 else _default_log_path()
    elif len(sys.argv) == 2:
        input_dir, output_dir = _resolve_default_paths()
        log_path = Path(sys.argv[1])
    else:
        input_dir, output_dir = _resolve_default_paths()
        log_path = _default_log_path()

    _write(log_path, f"RUN START {datetime.now().isoformat(timespec='seconds')}")
    try:
        summary = run_batch_translation(
            input_dir=input_dir,
            output_dir=output_dir,
            reporter=FileReporter(log_path),
        )
    except Exception:
        _write(log_path, "RUN ERROR")
        with log_path.open("a", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        raise

    _write(log_path, f"SUMMARY {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
