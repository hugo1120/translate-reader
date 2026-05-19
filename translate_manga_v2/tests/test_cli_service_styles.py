from pathlib import Path

from PIL import Image

from translate_manga.cli import service as cli_service
from translate_manga.cli.service import PreparedPage
from translate_manga.core.styles import resolve_style_profile
from translate_manga.core.translate.openai_compatible import TRANSLATION_FAILURE_TEXT


def _write_test_image(path):
    Image.new("RGB", (32, 32), "white").save(path)


def _preprocessed_payload(texts):
    return {
        "originalTexts": list(texts),
        "bubbleCoords": [[2, 2, 30, 30] for _ in texts],
        "textlinesPerBubble": [
            [{"direction": "h", "polygon": [[2, 2], [30, 2], [30, 30], [2, 30]]}]
            for _ in texts
        ],
    }


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


def test_build_run_options_records_auto_style_metadata(tmp_path):
    profile = resolve_style_profile("auto")

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

    assert options["styleId"] == "auto"
    assert options["styleName"] == "Auto"
    assert options["sourceLanguage"] == "japanese"
    assert options["readingOrder"] == "rtl"
    assert options["promptProfile"] == "default"


def test_build_run_options_records_multimodal_style_metadata(tmp_path):
    profile = resolve_style_profile("style_mm")

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

    assert options["styleId"] == "style_mm"
    assert options["styleName"] == "多模态AI辅助"
    assert options["layoutAssist"] == {"type": "multimodal", "enabled": True}
    assert options["sourceLanguage"] == "japanese"
    assert options["readingOrder"] == "rtl"


def test_build_preprocess_signature_includes_style_ocr_overrides():
    profile = resolve_style_profile("style3")

    signature = cli_service._build_preprocess_signature(
        {"ocr": {"source_language": "japanese", "engine": "48px_ocr"}},
        style_profile=profile,
    )

    assert '"source_language": "english"' in signature
    assert '"engine": "paddle_ocr"' in signature
    assert '"reading_order": "ltr"' in signature


def test_build_preprocess_signature_tracks_multimodal_assist_without_changing_auto():
    auto_signature = cli_service._build_preprocess_signature(
        {"ocr": {"source_language": "japanese", "engine": "48px_ocr"}},
        style_profile=resolve_style_profile("auto"),
    )
    multimodal_signature = cli_service._build_preprocess_signature(
        {"ocr": {"source_language": "japanese", "engine": "48px_ocr"}},
        style_profile=resolve_style_profile("style_mm"),
    )

    assert auto_signature != multimodal_signature
    assert '"layout_assist"' not in auto_signature
    assert '"type": "multimodal"' in multimodal_signature


def test_build_preprocess_signature_tracks_multimodal_config_readiness_without_secret():
    missing_key_signature = cli_service._build_preprocess_signature(
        {
            "ocr": {"source_language": "japanese", "engine": "48px_ocr"},
            "multimodal_layout": {
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "",
            },
        },
        style_profile=resolve_style_profile("style_mm"),
    )
    ready_signature = cli_service._build_preprocess_signature(
        {
            "ocr": {"source_language": "japanese", "engine": "48px_ocr"},
            "multimodal_layout": {
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-secret",
            },
        },
        style_profile=resolve_style_profile("style_mm"),
    )

    assert missing_key_signature != ready_signature
    assert '"configured": false' in missing_key_signature
    assert '"configured": true' in ready_signature
    assert "vision-secret" not in ready_signature


def test_apply_layout_assist_runs_only_for_multimodal_style(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    preprocessed = _preprocessed_payload(["30"])
    calls = []

    def fake_apply_multimodal_layout_assist(image_path, payload, config):
        calls.append((Path(image_path), payload, config))
        updated = dict(payload)
        updated["multimodalLayout"] = {"status": "ok", "regions": []}
        updated["bubbleLayoutHints"] = [{"role": "page_number", "suppressTranslation": True}]
        return updated

    monkeypatch.setattr(cli_service, "apply_multimodal_layout_assist", fake_apply_multimodal_layout_assist)
    settings = {
        "multimodal_layout": {
            "enabled": False,
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
        }
    }

    auto_result = cli_service._apply_layout_assist_to_preprocessed(
        source_path,
        preprocessed,
        style_profile=resolve_style_profile("auto"),
        settings=settings,
    )
    multimodal_result = cli_service._apply_layout_assist_to_preprocessed(
        source_path,
        preprocessed,
        style_profile=resolve_style_profile("style_mm"),
        settings=settings,
    )

    assert auto_result is preprocessed
    assert len(calls) == 1
    assert calls[0][0] == source_path
    assert calls[0][2]["enabled"] is True
    assert multimodal_result["bubbleLayoutHints"][0]["role"] == "page_number"


def test_apply_layout_assist_respects_multimodal_cache_disabled(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    preprocessed = _preprocessed_payload(["30"])
    preprocessed["multimodalLayout"] = {"status": "ok", "regions": []}
    preprocessed["bubbleLayoutHints"] = [{"role": "page_number", "suppressTranslation": True}]
    calls = []

    def fake_apply_multimodal_layout_assist(image_path, payload, config):
        calls.append((Path(image_path), payload, config))
        updated = dict(payload)
        updated["multimodalLayout"] = {"status": "ok", "regions": [{"id": "fresh"}]}
        updated["bubbleLayoutHints"] = [{"role": "dialogue"}]
        return updated

    monkeypatch.setattr(cli_service, "apply_multimodal_layout_assist", fake_apply_multimodal_layout_assist)

    cached_result = cli_service._apply_layout_assist_to_preprocessed(
        source_path,
        preprocessed,
        style_profile=resolve_style_profile("style_mm"),
        settings={
            "multimodal_layout": {
                "enabled": False,
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-key",
                "cache_enabled": True,
            }
        },
    )
    refreshed_result = cli_service._apply_layout_assist_to_preprocessed(
        source_path,
        preprocessed,
        style_profile=resolve_style_profile("style_mm"),
        settings={
            "multimodal_layout": {
                "enabled": False,
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-key",
                "cache_enabled": False,
            }
        },
    )

    assert cached_result is preprocessed
    assert len(calls) == 1
    assert calls[0][2]["cache_enabled"] is False
    assert refreshed_result["bubbleLayoutHints"] == [{"role": "dialogue"}]


def test_apply_layout_assist_retries_cached_non_ok_multimodal_result(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    preprocessed = _preprocessed_payload(["30"])
    preprocessed["multimodalLayout"] = {"status": "skipped", "reason": "not_configured", "regions": []}
    preprocessed["bubbleLayoutHints"] = [{}]
    calls = []

    def fake_apply_multimodal_layout_assist(image_path, payload, config):
        calls.append((Path(image_path), payload, config))
        updated = dict(payload)
        updated["multimodalLayout"] = {"status": "ok", "regions": [{"id": "fresh"}]}
        updated["bubbleLayoutHints"] = [{"role": "dialogue"}]
        return updated

    monkeypatch.setattr(cli_service, "apply_multimodal_layout_assist", fake_apply_multimodal_layout_assist)

    result = cli_service._apply_layout_assist_to_preprocessed(
        source_path,
        preprocessed,
        style_profile=resolve_style_profile("style_mm"),
        settings={
            "multimodal_layout": {
                "enabled": False,
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-key",
                "cache_enabled": True,
            }
        },
    )

    assert len(calls) == 1
    assert result["multimodalLayout"]["status"] == "ok"
    assert result["bubbleLayoutHints"] == [{"role": "dialogue"}]


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
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-001", "fileName": "001.jpg"},
        source_path=source_path,
        target_path=tmp_path / "001.translated.png",
        preprocessed_payload=_preprocessed_payload(["HELLO"]),
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


def test_translate_batch_translates_each_page_separately(monkeypatch, tmp_path):
    calls = []
    source_path_1 = tmp_path / "001.jpg"
    source_path_2 = tmp_path / "002.jpg"
    _write_test_image(source_path_1)
    _write_test_image(source_path_2)
    prepared_pages = [
        PreparedPage(
            page={"id": "page-001", "fileName": "001.jpg"},
            source_path=source_path_1,
            target_path=tmp_path / "001.translated.png",
            preprocessed_payload=_preprocessed_payload(["A1", "A2"]),
        ),
        PreparedPage(
            page={"id": "page-002", "fileName": "002.jpg"},
            source_path=source_path_2,
            target_path=tmp_path / "002.translated.png",
            preprocessed_payload=_preprocessed_payload(["B1"]),
        ),
    ]

    def fake_call_translate_texts_multi_round(**kwargs):
        texts = list(kwargs.get("texts") or [])
        calls.append(texts)
        return {
            "translatedTexts": [f"zh-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    monkeypatch.setattr(cli_service, "_call_translate_texts_multi_round", fake_call_translate_texts_multi_round)

    translated = cli_service._translate_batch(
        prepared_pages,
        model="model",
        base_url="https://example.invalid/v1",
        api_key="key",
        context_snapshot={},
    )

    assert calls == [["A1", "A2"], ["B1"]]
    assert translated["page-001"]["translatedTexts"] == ["zh-A1", "zh-A2"]
    assert translated["page-002"]["translatedTexts"] == ["zh-B1"]


def test_translate_batch_retries_failure_placeholder_payload(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-001", "fileName": "001.jpg"},
        source_path=source_path,
        target_path=tmp_path / "001.translated.png",
        preprocessed_payload=_preprocessed_payload(["A1"]),
    )
    calls = []

    def fake_call_translate_texts_multi_round(**kwargs):
        calls.append(list(kwargs.get("texts") or []))
        if len(calls) == 1:
            return {
                "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                "rounds": [],
                "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                "ocrRetry": {"shouldRetry": True, "reasons": ["translation_failed"], "attempted": False, "applied": False},
            }
        return {
            "translatedTexts": ["zh-A1"],
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
        context_snapshot={},
    )

    assert calls == [["A1"], ["A1"]]
    assert translated["page-001"]["translatedTexts"] == ["zh-A1"]


def test_translate_batch_retries_and_normalizes_romanized_japanese_terms(monkeypatch, tmp_path):
    source_path = tmp_path / "352.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-352", "fileName": "352.jpg"},
        source_path=source_path,
        target_path=tmp_path / "352.translated.png",
        preprocessed_payload=_preprocessed_payload(["いよいよ、 これから マスどり じゃ。"]),
    )
    contexts = []

    def fake_call_translate_texts_multi_round(**kwargs):
        contexts.append(kwargs.get("context_snapshot") or {})
        if len(contexts) == 1:
            return {
                "translatedTexts": ["终于,要开始Masudori了."],
                "rounds": [],
                "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
            }
        return {
            "translatedTexts": ["终于,要开始量斗了."],
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
        context_snapshot={"sourceLanguage": "japanese", "mangaContext": ""},
    )

    assert len(contexts) == 2
    assert contexts[0]["glossary"]["マスどり"] == "量斗"
    assert contexts[1]["glossary"]["マスどり"] == "量斗"
    assert "罗马字" in contexts[1]["mangaContext"]
    assert translated["page-352"]["translatedTexts"] == ["终于,要开始量斗了."]


def test_translate_batch_replaces_known_term_if_retry_keeps_romanization(monkeypatch, tmp_path):
    source_path = tmp_path / "352.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-352", "fileName": "352.jpg"},
        source_path=source_path,
        target_path=tmp_path / "352.translated.png",
        preprocessed_payload=_preprocessed_payload(["オオ 正助、 ちょっと マスどり の ようすを みにきた のじゃ。"]),
    )

    def fake_call_translate_texts_multi_round(**kwargs):
        return {
            "translatedTexts": ["哦 正助,我来看看Masudori的情况."],
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
        context_snapshot={"sourceLanguage": "japanese"},
    )

    assert translated["page-352"]["translatedTexts"] == ["哦 正助,我来看看量斗的情况."]


def test_translate_batch_normalizes_known_japanese_sound_effect_residuals(monkeypatch, tmp_path):
    source_path = tmp_path / "054.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-054", "fileName": "054.jpg"},
        source_path=source_path,
        target_path=tmp_path / "054.translated.png",
        preprocessed_payload=_preprocessed_payload(["シュル", "ラスル", "ワウン ワウン", "アウッ アウッ", "アアッミ"]),
    )

    def fake_call_translate_texts_multi_round(**kwargs):
        return {
            "translatedTexts": ["シュル", "拉斯尔", "ワウン ワウン", "アウッ アウッ", "啊,阿音"],
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
        context_snapshot={"sourceLanguage": "japanese"},
    )

    assert translated["page-054"]["translatedTexts"] == ["嗖", "嗖", "汪 汪", "嗷 嗷", "啊啊"]


def test_lightweight_retry_preserves_style_context(monkeypatch, tmp_path):
    captured = {}
    source_path = tmp_path / "001.jpg"
    _write_test_image(source_path)
    prepared_page = PreparedPage(
        page={"id": "page-001", "fileName": "001.jpg"},
        source_path=source_path,
        target_path=tmp_path / "001.translated.png",
        preprocessed_payload=_preprocessed_payload(["HELLO"]),
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
