from pathlib import Path
import subprocess


def test_start_cli_bat_without_args_launches_interactive_menu():
    project_root = Path(__file__).resolve().parents[1]
    bat_path = project_root / "start_cli.bat"

    completed = subprocess.run(
        ["cmd", "/c", str(bat_path)],
        cwd=project_root,
        input="4\n",
        capture_output=True,
        text=True,
        encoding="gbk",
        errors="ignore",
    )

    output = completed.stdout + completed.stderr

    assert completed.returncode == 0
    assert "Translate Manga CLI" in output
    assert "Reuse" in output
    assert "Reset" in output
    assert "Batch" in output
    assert "Exit" in output
