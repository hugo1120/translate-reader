import json
from pathlib import Path

from translate_manga.config import settings as settings_module
from translate_manga.config.settings import load_settings


def test_load_settings_merges_defaults_local_and_env(tmp_path, monkeypatch):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "D:/default-input",
                    "output_dir": "D:/default-output",
                    "saber_root": "../Saber-Translator",
                    "saber_python": "",
                },
                "translation": {
                    "model": "default-model",
                    "base_url": "https://default.example/v1",
                    "api_key": "",
                },
                "pipeline": {
                    "overwrite_existing": False,
                    "debug_output": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "D:/local-input",
                },
                "translation": {
                    "base_url": "https://local.example/v1",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSLATE_MANGA_CLI_MODEL", "env-model")
    monkeypatch.setenv("TRANSLATE_MANGA_CLI_OVERWRITE_EXISTING", "true")

    settings = load_settings(project_root=project_root)

    assert settings["paths"]["input_dir"] == "D:/local-input"
    assert settings["translation"]["base_url"] == "https://local.example/v1"
    assert settings["translation"]["model"] == "env-model"
    assert settings["pipeline"]["overwrite_existing"] is True


def test_resolve_translation_config_uses_single_config_entry(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "translation": {
                    "model": "configured-model",
                    "base_url": "https://configured.example/v1",
                    "api_key": "configured-key",
                    "request_timeout_seconds": 12.5,
                    "curl_timeout_seconds": 34,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text("{}", encoding="utf-8")

    config = settings_module.resolve_translation_config(project_root=project_root)

    assert config == {
        "model": "configured-model",
        "base_url": "https://configured.example/v1",
        "api_key": "configured-key",
        "request_timeout_seconds": 12.5,
        "curl_timeout_seconds": 34,
    }


def test_resolve_translation_prompt_config_merges_defaults_and_local(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "prompts": {
                    "translation": {
                        "system": "default system",
                        "rounds": {
                            "draft": "default draft",
                            "contextual": "default contextual",
                            "final": "default final",
                        },
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text(
        json.dumps(
            {
                "prompts": {
                    "translation": {
                        "system": "local system",
                        "rounds": {
                            "contextual": "local contextual",
                            "final": "",
                        },
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    prompts = settings_module.resolve_translation_prompt_config(project_root=project_root)

    assert prompts["system"] == "local system"
    assert prompts["rounds"]["draft"] == "default draft"
    assert prompts["rounds"]["contextual"] == "local contextual"
    assert prompts["rounds"]["final"] == "default final"


def test_resolve_translation_prompt_config_can_select_english_profile(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "prompts": {
                    "translation": {
                        "system": "把漫画中的日文文本翻译成简体中文",
                        "rounds": {
                            "draft": "日文初稿",
                            "contextual": "日文修订",
                            "final": "日文定稿",
                        },
                        "profiles": {
                            "english": {
                                "system": "把漫画中的英文文本翻译成简体中文",
                                "rounds": {
                                    "draft": "英文初稿",
                                    "contextual": "英文修订",
                                    "final": "英文定稿",
                                },
                            }
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prompts = settings_module.resolve_translation_prompt_config(project_root=project_root, prompt_profile="english")

    assert "英文文本" in prompts["system"]
    assert prompts["rounds"]["draft"] == "英文初稿"
    assert prompts["rounds"]["contextual"] == "英文修订"
    assert prompts["rounds"]["final"] == "英文定稿"


def test_resolve_ocr_config_merges_defaults_local_and_env(tmp_path, monkeypatch):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "ocr": {
                    "engine": "48px_ocr",
                    "enable_hybrid": True,
                    "secondary_engine": "manga_ocr",
                    "hybrid_threshold": 0.2,
                    "fallback_to_manga_ocr_when_48px_unavailable": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text(
        json.dumps(
            {
                "ocr": {
                    "secondary_engine": "paddle_ocr",
                    "hybrid_threshold": 0.35,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSLATE_MANGA_CLI_OCR_ENGINE", "manga_ocr")
    monkeypatch.setenv("TRANSLATE_MANGA_CLI_OCR_ENABLE_HYBRID", "false")

    config = settings_module.resolve_ocr_config(project_root=project_root)

    assert config["engine"] == "manga_ocr"
    assert config["enable_hybrid"] is False
    assert config["secondary_engine"] == "paddle_ocr"
    assert config["hybrid_threshold"] == 0.35
    assert config["fallback_to_manga_ocr_when_48px_unavailable"] is True


def test_resolve_runtime_config_supports_operation_timeout_override(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "saber_session_timeout_seconds": 45.0,
                    "saber_subprocess_timeout_seconds": 45.0,
                    "saber_operation_timeout_seconds": {
                        "preprocess": 90.0,
                    },
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text("{}", encoding="utf-8")

    config = settings_module.resolve_runtime_config(project_root=project_root)

    assert config["saber_session_timeout_seconds"] == 45.0
    assert config["saber_subprocess_timeout_seconds"] == 45.0
    assert config["saber_operation_timeout_seconds"] == {
        "preprocess": 90.0,
    }


def test_default_preprocess_timeout_allows_slow_paddle_english_pages():
    project_root = Path(__file__).resolve().parents[1]
    defaults = json.loads((project_root / "config" / "defaults.json").read_text(encoding="utf-8"))

    preprocess_timeout = defaults["runtime"]["saber_operation_timeout_seconds"]["preprocess"]

    assert preprocess_timeout >= 180.0


def test_resolve_pipeline_config_supports_context_options(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "pipeline": {
                    "overwrite_existing": False,
                    "debug_output": True,
                    "skip_frontmatter": True,
                    "translate_batch_size": 3,
                    "translate_batch_max_chars": 1600,
                    "manga_context_file_names": ["manga_context.md", "manga_context.txt"],
                    "auto_generate_manga_context": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "local.json").write_text(
        json.dumps(
            {
                "pipeline": {
                    "manga_context_file_names": ["book_context.md"],
                    "auto_generate_manga_context": False,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    config = settings_module.resolve_pipeline_config(project_root=project_root)

    assert config["manga_context_file_names"] == ["book_context.md"]
    assert config["auto_generate_manga_context"] is False


def test_resolve_pipeline_config_supports_speed_options(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    (config_dir / "defaults.json").write_text(
        json.dumps(
            {
                "pipeline": {
                    "translation_quality": "balanced",
                    "debug_flush_interval": 11,
                    "color_fast_mode": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    config = settings_module.resolve_pipeline_config(project_root=project_root)

    assert config["translation_quality"] == "balanced"
    assert config["debug_flush_interval"] == 11
    assert config["color_fast_mode"] is True


def test_session_state_supports_multi_input_dirs_and_legacy_single_dir(tmp_path):
    project_root = tmp_path / "translate_manga_cli"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    input_dir_one = tmp_path / "book-1" / "01"
    input_dir_two = tmp_path / "book-2" / "01"

    settings_module.save_session_state(
        last_input_dirs=[input_dir_one, input_dir_two],
        last_layout_mode="horizontal",
        last_overwrite_existing=False,
        project_root=project_root,
    )

    state = settings_module.load_session_state(project_root=project_root)

    assert state["last_input_dirs"] == [
        input_dir_one.resolve().as_posix(),
        input_dir_two.resolve().as_posix(),
    ]
    assert state["last_input_dir"] == input_dir_one.resolve().as_posix()
    assert state["last_output_dir"] == (input_dir_one / "out").resolve().as_posix()
    assert state["last_layout_mode"] == "horizontal"
    assert state["last_overwrite_existing"] is False

    (config_dir / "session.json").write_text(
        json.dumps({"last_input_dir": input_dir_one.as_posix(), "last_layout_mode": "vertical"}, ensure_ascii=False),
        encoding="utf-8",
    )

    legacy_state = settings_module.load_session_state(project_root=project_root)

    assert legacy_state["last_input_dirs"] == [Path(input_dir_one).as_posix()]
    assert legacy_state["last_input_dir"] == Path(input_dir_one).as_posix()
    assert legacy_state["last_layout_mode"] == "vertical"
