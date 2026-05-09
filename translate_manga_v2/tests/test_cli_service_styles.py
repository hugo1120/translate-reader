from pathlib import Path

from translate_manga.cli import service as cli_service
from translate_manga.cli.service import PreparedPage
from translate_manga.core.styles import resolve_style_profile


def test_build_run_options_records_style3_metadata(tmp_path):
    profile = resolve_style_profile("style3")

    options = cli_service._build_run_options(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "input" / "out",
        layout_mode=profile["layout_mode"],
        overwrite_existing=False,
        launch_mode="test",
        model="model",
        ocr_config={"engine": "48px_ocr", "secondary_engine": "manga_ocr"},
        retry_review_pages=False,
        style_profile=profile,
    )

    assert options["styleId"] == "style3"
    assert options["styleName"] == "Style 3"
    assert options["sourceLanguage"] == "english"
    assert options["readingOrder"] == "ltr"
    assert options["promptProfile"] == "english"


def test_build_preprocess_signature_includes_style_ocr_overrides():
    profile = resolve_style_profile("style3")

    signature = cli_service._build_preprocess_signature(
        {"ocr": {"source_language": "japanese", "engine": "48px_ocr"}},
        style_profile=profile,
    )

    assert '"source_language": "english"' in signature
    assert '"engine": "paddle_ocr"' in signature
    assert '"reading_order": "ltr"' in signature


def test_build_translation_signature_tracks_prompt_profile_and_context():
    settings = {
        "prompts": {
            "translation": {
                "profiles": {
                    "english": {
                        "system": "english system",
                        "rounds": {
                            "draft": "english draft",
                            "contextual": "english contextual",
                            "final": "english final",
                        },
                    }
                }
            }
        }
    }

    default_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style1"),
        manga_context_payload={"content": ""},
    )
    english_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style3"),
        manga_context_payload={"content": ""},
    )
    english_context_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style3"),
        manga_context_payload={"content": "角色名固定为 Zoe"},
    )

    assert default_signature != english_signature
    assert english_signature != english_context_signature


def test_build_translation_signature_tracks_quality():
    settings = {"pipeline": {"translation_quality": "high"}}
    high_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
        translation_quality="high",
    )
    fast_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
        translation_quality="fast",
    )

    assert high_signature != fast_signature


def test_build_translation_signature_defaults_quality_from_settings():
    settings = {"pipeline": {"translation_quality": "balanced"}}
    implicit_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
    )
    explicit_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
        translation_quality="balanced",
    )

    assert implicit_signature == explicit_signature


def test_translate_batch_passes_style_context_without_manga_context(monkeypatch, tmp_path):
    captured = {}
    prepared_page = PreparedPage(
        page={"id": "page-001", "fileName": "001.jpg"},
        source_path=tmp_path / "001.jpg",
        target_path=tmp_path / "001.translated.png",
        preprocessed_payload={"originalTexts": ["HELLO"]},
    )

    def fake_call_translate_texts_multi_round(**kwargs):
        captured["context_snapshot"] = kwargs.get("context_snapshot")
        return {
            "translatedTexts": ["你好"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    monkeypatch.setattr(cli_service, "_call_translate_texts_multi_round", fake_call_translate_texts_multi_round)

    translated = cli_service._translate_batch(
        [prepared_page],
        model="model",
        base_url="https://example.invalid/v1",
        api_key="key",
        context_snapshot={
            "sourceLanguage": "english",
            "promptPreset": "english",
            "readingOrder": "ltr",
            "mangaContext": "",
            "confirmedTranslations": [],
            "glossary": {},
        },
    )

    assert translated["page-001"]["translatedTexts"] == ["你好"]
    assert captured["context_snapshot"]["promptPreset"] == "english"
    assert captured["context_snapshot"]["sourceLanguage"] == "english"


def test_lightweight_retry_preserves_style_context(monkeypatch, tmp_path):
    captured = {}
    prepared_page = PreparedPage(
        page={"id": "page-001", "fileName": "001.jpg"},
        source_path=tmp_path / "001.jpg",
        target_path=tmp_path / "001.translated.png",
        preprocessed_payload={"originalTexts": ["HELLO"]},
    )

    class Reporter:
        def log(self, message):
            return None

    def fake_translate_batch(*args, **kwargs):
        raise RuntimeError("batch failed")

    def fake_translate_texts(**kwargs):
        captured["context_snapshot"] = kwargs.get("context_snapshot")
        return ["你好"]

    monkeypatch.setattr(cli_service, "_translate_batch", fake_translate_batch)
    monkeypatch.setattr(cli_service, "translate_texts", fake_translate_texts)

    translated_by_page, failures = cli_service._translate_pages_individually(
        [prepared_page],
        model="model",
        base_url="https://example.invalid/v1",
        api_key="key",
        context_snapshot={"promptPreset": "english", "sourceLanguage": "english"},
        reporter=Reporter(),
    )

    assert failures == {}
    assert translated_by_page["page-001"]["translatedTexts"] == ["你好"]
    assert captured["context_snapshot"]["promptPreset"] == "english"
