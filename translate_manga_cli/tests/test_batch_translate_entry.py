from pathlib import Path

import batch_translate


def test_main_uses_configured_paths_without_prompt(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
            },
        },
    )
    monkeypatch.setattr(
        batch_translate,
        "_prompt_path",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not be used")),
    )
    monkeypatch.setattr(batch_translate, "load_session_state", lambda: {})

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    batch_translate.main()

    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir


def test_main_uses_session_paths_when_user_selects_reuse(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {
                "input_dir": "",
                "output_dir": "",
            },
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate,
        "load_session_state",
        lambda: {
            "last_input_dir": str(input_dir),
            "last_output_dir": str(output_dir),
            "last_layout_mode": "vertical",
        },
    )
    monkeypatch.setattr(
        batch_translate,
        "_prompt_path",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not be used")),
    )
    monkeypatch.setattr(batch_translate, "_prompt_choice", lambda *args, **kwargs: "1")

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)
    monkeypatch.setattr(batch_translate, "save_session_state", lambda **kwargs: captured.update({"saved": kwargs}))

    batch_translate.main()

    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"
    assert captured["saved"]["last_layout_mode"] == "vertical"


def test_main_prompts_for_paths_and_layout_when_user_selects_reset(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {"prompt_labels": []}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {
                "input_dir": "",
                "output_dir": "",
            },
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(batch_translate, "load_session_state", lambda: {})

    def fake_prompt_path(label, must_exist=False):
        captured["prompt_labels"].append(label)
        return input_dir if "Input" in label else output_dir

    choice_values = iter(["2", "1"])
    monkeypatch.setattr(batch_translate, "_prompt_path", fake_prompt_path)
    monkeypatch.setattr(batch_translate, "_prompt_choice", lambda *args, **kwargs: next(choice_values))

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)
    monkeypatch.setattr(batch_translate, "save_session_state", lambda **kwargs: captured.update({"saved": kwargs}))

    batch_translate.main()

    assert captured["prompt_labels"] == ["Input folder", "Output folder"]
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"
    assert captured["saved"]["last_input_dir"] == str(input_dir)
    assert captured["saved"]["last_output_dir"] == str(output_dir)
    assert captured["saved"]["last_layout_mode"] == "vertical"
