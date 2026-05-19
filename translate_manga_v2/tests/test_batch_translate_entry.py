from pathlib import Path

import pytest

import batch_translate


def test_main_uses_configured_paths_when_cli_args_omitted(monkeypatch, tmp_path):
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
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(batch_translate.sys, "argv", ["batch_translate.py"])

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

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"


def test_main_prefers_explicit_cli_args_over_config_defaults(monkeypatch, tmp_path):
    input_dir = tmp_path / "cli-input"
    output_dir = tmp_path / "cli-output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {
                "input_dir": str(tmp_path / "config-input"),
                "output_dir": str(tmp_path / "config-output"),
            },
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--layout-mode",
            "horizontal",
            "--overwrite-existing",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        captured["overwrite_existing"] = kwargs.get("overwrite_existing")
        return {
            "total": 2,
            "succeeded": 2,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "horizontal"
    assert captured["overwrite_existing"] is True


def test_main_passes_style_id_option(monkeypatch, tmp_path):
    input_dir = tmp_path / "cli-input"
    output_dir = tmp_path / "cli-output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--style-id",
            "3",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        captured["style_id"] = kwargs.get("style_id")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"
    assert captured["style_id"] == "3"


def test_main_passes_auto_style_id_option(monkeypatch, tmp_path):
    input_dir = tmp_path / "cli-input"
    output_dir = tmp_path / "cli-output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--style-id",
            "auto",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        captured["style_id"] = kwargs.get("style_id")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"
    assert captured["style_id"] == "auto"


def test_main_passes_multimodal_style_id_option(monkeypatch, tmp_path):
    input_dir = tmp_path / "cli-input"
    output_dir = tmp_path / "cli-output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--style-id",
            "M",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["layout_mode"] = kwargs.get("layout_mode")
        captured["style_id"] = kwargs.get("style_id")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["layout_mode"] == "vertical"
    assert captured["style_id"] == "M"


def test_main_rejects_invalid_style_id(monkeypatch, tmp_path):
    input_dir = tmp_path / "cli-input"
    output_dir = tmp_path / "cli-output"
    input_dir.mkdir()

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--style-id",
            "9",
        ],
    )

    with pytest.raises(SystemExit) as error:
        batch_translate.main()

    assert error.value.code == 2


def test_main_passes_retry_review_pages_option(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--retry-review-pages",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["retry_review_pages"] = kwargs.get("retry_review_pages")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["retry_review_pages"] is True


def test_main_passes_retry_quality_review_pages_option(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--retry-quality-review-pages",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["retry_review_pages"] = kwargs.get("retry_review_pages")
        captured["retry_quality_review_pages"] = kwargs.get("retry_quality_review_pages")
        return {
            "total": 1,
            "succeeded": 1,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["retry_review_pages"] is True
    assert captured["retry_quality_review_pages"] is True


def test_main_passes_repeated_page_name_options(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        [
            "batch_translate.py",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--page-name",
            "001.jpg",
            "--page-name",
            "003.jpg",
        ],
    )

    def fake_run_batch_translation(*, input_dir, output_dir, **kwargs):
        captured["input_dir"] = Path(input_dir)
        captured["output_dir"] = Path(output_dir)
        captured["target_page_names"] = kwargs.get("target_page_names")
        return {
            "total": 2,
            "succeeded": 2,
            "skipped": 0,
            "failed": 0,
        }

    monkeypatch.setattr(batch_translate, "run_batch_translation", fake_run_batch_translation)

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir
    assert captured["target_page_names"] == ["001.jpg", "003.jpg"]


def test_main_supports_positional_input_output(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )
    monkeypatch.setattr(
        batch_translate.sys,
        "argv",
        ["batch_translate.py", str(input_dir), str(output_dir)],
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

    exit_code = batch_translate.main()

    assert exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == output_dir


def test_main_exits_when_input_and_output_are_unavailable(monkeypatch):
    monkeypatch.setattr(
        batch_translate,
        "load_settings",
        lambda: {
            "paths": {},
            "render": {},
        },
    )
    monkeypatch.setattr(batch_translate.sys, "argv", ["batch_translate.py"])

    with pytest.raises(SystemExit) as error:
        batch_translate.main()

    assert error.value.code == 2
