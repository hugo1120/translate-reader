from pathlib import Path


def find_project_root(start=None) -> Path:
    start_path = Path(start) if start is not None else Path(__file__)
    resolved = start_path.resolve()
    current = resolved.parent if resolved.is_file() or resolved.suffix else resolved

    for candidate in (current, *current.parents):
        if (candidate / "config" / "defaults.json").exists():
            return candidate

    raise FileNotFoundError(f"Unable to locate project root from: {start_path}")
