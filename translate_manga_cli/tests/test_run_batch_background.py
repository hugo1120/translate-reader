from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_batch_background as run_batch_background_module


def test_default_log_path_uses_logs_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "translate_manga_cli"
    project_root.mkdir(parents=True)
    monkeypatch.setattr(run_batch_background_module, "__file__", str(project_root / "run_batch_background.py"))

    log_path = run_batch_background_module._default_log_path()

    assert log_path.parent == project_root / "logs"
    assert log_path.name == "batch-live.log"


def test_resolve_default_paths_resolves_relative_config_against_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "translate_manga_cli"
    input_dir = project_root / "input"
    output_dir = project_root / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    monkeypatch.setattr(run_batch_background_module, "__file__", str(project_root / "run_batch_background.py"))
    monkeypatch.setattr(
        run_batch_background_module,
        "load_settings",
        lambda: {
            "paths": {
                "input_dir": "input",
                "output_dir": "output",
            }
        },
    )

    resolved_input, resolved_output = run_batch_background_module._resolve_default_paths()

    assert resolved_input == input_dir
    assert resolved_output == output_dir
