from pathlib import Path

from src.cli import menu


def test_menu_reset_saves_session_and_returns_to_main_menu(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}
    prompts = iter(
        [
            "2",
            str(input_dir),
            str(output_dir),
            "1",
            "2",
            "3",
        ]
    )
    output_lines = []

    monkeypatch.setattr(
        menu,
        "load_settings",
        lambda project_root=None: {
            "paths": {},
            "render": {"layout_mode": "vertical"},
        },
    )

    def fake_run_batch_translation(**kwargs):
        captured["kwargs"] = kwargs
        return {"total": 1, "succeeded": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert captured["kwargs"]["input_dir"] == input_dir
    assert captured["kwargs"]["output_dir"] == output_dir
    assert captured["kwargs"]["layout_mode"] == "horizontal"
    assert captured["kwargs"]["overwrite_existing"] is True
    assert (project_root / "config" / "session.json").exists()
    session_text = (project_root / "config" / "session.json").read_text(encoding="utf-8")
    assert '"last_layout_mode": "horizontal"' in session_text
    assert '"last_overwrite_existing": true' in session_text
    combined_output = "".join(output_lines)
    assert combined_output.count("Translate Manga CLI") >= 2
    assert "Summary: total=1 ok=1 skip=0 fail=0" in combined_output


def test_menu_reuses_saved_session(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    normalized_input_dir = str(input_dir).replace("\\", "/")
    normalized_output_dir = str(output_dir).replace("\\", "/")
    config_root.joinpath("session.json").write_text(
        (
            "{\n"
            f'  "last_input_dir": "{normalized_input_dir}",\n'
            f'  "last_output_dir": "{normalized_output_dir}",\n'
            '  "last_layout_mode": "vertical",\n'
            '  "last_overwrite_existing": false\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    prompts = iter(["1", "3"])
    captured = {}

    monkeypatch.setattr(
        menu,
        "load_settings",
        lambda project_root=None: {
            "paths": {},
            "render": {"layout_mode": "vertical"},
        },
    )

    def fake_run_batch_translation(**kwargs):
        captured["kwargs"] = kwargs
        return {"total": 2, "succeeded": 2, "skipped": 0, "failed": 0}

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream([]),
        project_root=project_root,
    )

    assert exit_code == 0
    assert captured["kwargs"]["input_dir"] == input_dir
    assert captured["kwargs"]["output_dir"] == output_dir
    assert captured["kwargs"]["layout_mode"] == "vertical"
    assert captured["kwargs"]["overwrite_existing"] is False
