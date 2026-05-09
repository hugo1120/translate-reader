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
    assert "Translate Manga V2" in output
    assert "继续上次任务" in output
    assert "新建任务" in output
    assert "扫描并纠正错误" in output
    assert "退出" in output
