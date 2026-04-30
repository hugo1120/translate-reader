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
