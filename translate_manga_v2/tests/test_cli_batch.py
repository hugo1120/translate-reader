from io import StringIO
import json
from pathlib import Path

from PIL import Image
import pytest

from tests.test_constants import TEST_BASE_URL
from translate_manga.cli.cache import BatchStageCache
from translate_manga.cli.debug_artifacts import BatchDebugArtifactWriter
from translate_manga.cli.service import (
    BatchProgressReporter,
    _build_translation_signature,
    _expand_translation_payload_to_page,
    _load_retry_review_page_names,
    _resolve_cli_settings,
    build_output_path,
    run_batch_translation,
    scan_input_images,
)
from translate_manga.core.context.manga_context import find_existing_manga_context
from translate_manga.core.natural_sort import natural_sort_key
from translate_manga.core.styles import resolve_style_profile
from translate_manga.core.translate.openai_compatible import TRANSLATION_FAILURE_TEXT, TRANSLATION_PROMPT_SIGNATURE


def _save_image(path, color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 24), color).save(path)


def _current_preprocess_signature():
    return _resolve_cli_settings()["preprocess_signature"]


def _current_translation_signature():
    return _build_translation_signature(
        _resolve_cli_settings()["settings"],
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
    )


@pytest.fixture(autouse=True)
def _disable_auto_manga_context_generation(monkeypatch):
    def fake_load_or_generate_manga_context(input_dir, *, auto_generate=None, pipeline_config=None):
        return find_existing_manga_context(input_dir, pipeline_config=pipeline_config)

    monkeypatch.setattr(
        "translate_manga.cli.service.load_or_generate_manga_context",
        fake_load_or_generate_manga_context,
    )


def test_build_output_path_uses_translated_png(tmp_path):
    output_path = build_output_path(tmp_path / "001.jpg", tmp_path / "out")

    assert output_path == tmp_path / "out" / "001.translated.png"


def test_run_batch_translation_records_run_options_in_debug_summary(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["001"],
            "ocrResults": [{"text": "001", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        return {
            "translatedTexts": ["译文"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.load_settings",
        lambda project_root=None: {
            "translation": {
                "model": "config-model",
                "base_url": TEST_BASE_URL,
                "api_key": "secret",
            },
            "ocr": {
                "engine": "48px_ocr",
                "secondary_engine": "manga_ocr",
                "enable_hybrid": True,
                "hybrid_threshold": 0.2,
                "fallback_to_manga_ocr_when_48px_unavailable": True,
            },
            "pipeline": {
                "overwrite_existing": False,
                "debug_output": True,
                "skip_frontmatter": True,
                "translate_batch_size": 3,
                "translate_batch_max_chars": 1600,
            },
            "paths": {},
            "render": {
                "layout_mode": "vertical",
            },
        },
    )

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        launch_mode="menu",
        overwrite_existing=True,
        layout_mode="vertical",
    )

    summary_payload = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))

    assert summary_payload["runOptions"]["inputDir"] == str(input_dir)
    assert summary_payload["runOptions"]["outputDir"] == str(output_dir)
    assert summary_payload["runOptions"]["layoutMode"] == "vertical"
    assert summary_payload["runOptions"]["styleName"] == "Style 2"
    assert summary_payload["runOptions"]["overwriteExisting"] is True
    assert summary_payload["runOptions"]["launchMode"] == "menu"
    assert summary_payload["runOptions"]["translationModel"] == "config-model"
    assert summary_payload["runOptions"]["ocrEngine"] == "48px_ocr"
    assert summary_payload["runOptions"]["secondaryOcrEngine"] == "manga_ocr"
    assert "apiKey" not in summary_payload["runOptions"]


def test_build_output_path_zero_pads_pure_numeric_stem_when_width_provided(tmp_path):
    output_path = build_output_path(tmp_path / "1.jpg", tmp_path / "out", numeric_width=3)

    assert output_path == tmp_path / "out" / "001.translated.png"


def test_scan_input_images_uses_natural_numeric_order(tmp_path):
    input_dir = tmp_path / "input"
    _save_image(input_dir / "1.jpg")
    _save_image(input_dir / "10.jpg")
    _save_image(input_dir / "2.jpg")
    _save_image(input_dir / "100.jpg")

    image_paths = scan_input_images(input_dir)

    assert [path.name for path in image_paths] == ["1.jpg", "2.jpg", "10.jpg", "100.jpg"]


def test_natural_sort_key_orders_equal_numbers_with_shorter_padding_first():
    names = ["001.jpg", "010.jpg", "01.jpg", "1.jpg", "10.jpg"]

    assert sorted(names, key=natural_sort_key) == ["1.jpg", "01.jpg", "001.jpg", "10.jpg", "010.jpg"]


def test_expand_translation_payload_to_page_reflows_long_narration_text():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": [
                "看来我过于深入狼的生活了。而且，这只白狼的成长，与本故事中同时描写的人类社会部分并无关联。因此，白狼在狼群中遭受的歧视问题，也不能直接与人类社会的歧视问题等同视之。在人类社会，歧视是作为维护统治利益的策略而被制造出来的。"
            ],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [
                {"role": "long_narration"},
            ],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[40, 220, 720, 700]],
            "count": 1,
        },
    )

    translated = payload["translatedTexts"][0]
    lines = translated.splitlines()
    assert len(lines) >= 4
    assert lines[0] == "看来我过于深入狼的生活了。"
    assert max(len(line) for line in lines) <= 22


def test_expand_translation_payload_to_page_groups_long_narration_paragraphs():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": [
                "看来我过于深入狼的生活了.而且,这只白狼的成长,与本故事中同时描写的人类社会部分并无关联.因此,白狼遭受同伴歧视的问题,不能直接等同于人类社会的歧视问题.此外,这类歧视被作为统治手段制造出来."
            ],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [
                {"role": "long_narration"},
            ],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[40, 220, 720, 700]],
            "count": 1,
        },
    )

    translated = payload["translatedTexts"][0]
    assert "." not in translated
    assert "," not in translated
    assert "因此，" in translated
    assert "此外，" in translated
    assert "\n\n" in translated


def test_expand_translation_payload_to_page_inserts_paragraph_gaps_for_large_narration_block():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": [
                "看来我过度介入了狼的生活.而且,这只白狼的成长,与人类社会部分并无关联.因此,它遭受同伴歧视的问题,不能直接等同于人类社会的歧视问题.然而,在人类社会中,歧视会被当作统治工具制造出来.此外,这类问题最终会导致群体分裂."
            ],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [{"role": "long_narration"}],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[40, 240, 700, 640]],
            "count": 1,
        },
    )

    assert "\n\n" in payload["translatedTexts"][0]


def test_expand_translation_payload_to_page_inserts_paragraph_gaps_for_dense_large_narration():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": [
                "看来我过度介入了狼的生活.而且,这只白狼的成长,与本故事同时描写的人类社会部分并无关联.因此,白狼遭受同伴歧视的问题,不能直接等同于人类社会的歧视问题.在人类社会中,为了维护统治者的利益,歧视被作为一种政策制造出来,身份也被法制化.然而,这种歧视会使人们互相反目,分裂,最终导致自我毁灭.此外,无论狼追求自由,高傲地拒绝妥协,还是贯彻独立自尊精神的生活,都与涉及此问题的人类主人公们并非对照关系.归根结底,狼被提及,仅仅是作为贯穿本故事整体所要讲述的要素之一罢了."
            ],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [{"role": "long_narration"}],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[40, 220, 716, 620]],
            "count": 1,
        },
    )

    assert "\n\n" in payload["translatedTexts"][0]


def test_expand_translation_payload_to_page_normalizes_long_narration_tail_punctuation():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": [
                "这种情况下就会采取检地的方式,测量全藩领内田地的面积,算出每个百姓持有的高(义务生产量)."
            ],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [{"role": "long_narration"}],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[40, 220, 720, 700]],
            "count": 1,
        },
    )

    translated = payload["translatedTexts"][0]
    assert "(义务生产量)" not in translated
    assert "（义务生产量）。" in translated


def test_expand_translation_payload_to_page_sanitizes_failed_intermediate_rounds():
    payload = _expand_translation_payload_to_page(
        {
            "translatedTexts": ["OK"],
            "rounds": [
                {
                    "name": "draft",
                    "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                    "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                },
                {
                    "name": "final",
                    "translatedTexts": ["OK"],
                    "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                },
            ],
            "tokenUsage": {"inputTokens": 2, "outputTokens": 2, "totalTokens": 4, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        {
            "profiles": [{"role": "dialogue"}],
            "indexes": [0],
            "texts": ["dummy"],
            "bubbleCoords": [[10, 20, 90, 60]],
            "count": 1,
        },
    )

    assert payload["translatedTexts"] == ["OK"]
    assert payload["rounds"][0]["translatedTexts"] == ["OK"]


def test_scan_input_images_accepts_supported_extensions_case_insensitively(tmp_path):
    input_dir = tmp_path / "input"
    _save_image(input_dir / "001.JPG")
    _save_image(input_dir / "002.PnG")
    _save_image(input_dir / "003.WebP")
    (input_dir / "004.txt").write_text("not an image", encoding="utf-8")

    image_paths = scan_input_images(input_dir)

    assert [path.name for path in image_paths] == ["001.JPG", "002.PnG", "003.WebP"]


def test_scan_input_images_handles_cover_and_zero_padded_numeric_names(tmp_path):
    input_dir = tmp_path / "input"
    _save_image(input_dir / "00002.jpg")
    _save_image(input_dir / "cover.jpg")
    _save_image(input_dir / "00010.jpg")
    _save_image(input_dir / "00001.jpg")

    image_paths = scan_input_images(input_dir)

    assert [path.name for path in image_paths] == ["cover.jpg", "00001.jpg", "00002.jpg", "00010.jpg"]


def test_run_batch_translation_skips_existing_outputs_and_copies_translated_image(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(input_dir / "002.png")
    _save_image(output_dir / "001.translated.png", color="gray")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    calls = []

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [Path(source_path).stem],
            "ocrResults": [{"text": Path(source_path).stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return [f"zh-{text}" for text in texts]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        calls.append((page_id, Path(source_path).name, translated_texts, saber_session))
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": ["ok"],
            "timings": {"total": 1.25},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    assert calls == [("page-0002", "002.png", ["zh-002"], "session-token")]
    assert (output_dir / "002.translated.png").exists()
    assert summary["succeeded"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    assert "SKIP 001.jpg -> 001.translated.png" in stream.getvalue()
    assert "OK   002.png -> 002.translated.png" in stream.getvalue()


def test_run_batch_translation_all_existing_outputs_skips_without_starting_saber(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    for name in ["001.jpg", "002.jpg"]:
        _save_image(input_dir / name)
        _save_image(output_dir / f"{Path(name).stem}.translated.png", color="gray")

    class ForbiddenSession:
        def __enter__(self):
            raise AssertionError("Saber should not start when all outputs already exist")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", ForbiddenSession)
    monkeypatch.setattr(
        "translate_manga.cli.service.preprocess_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.translate_texts_multi_round",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translation should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.run_page_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=False,
    )

    assert summary["total"] == 2
    assert summary["succeeded"] == 0
    assert summary["skipped"] == 2
    assert summary["failed"] == 0
    assert "SKIP 001.jpg -> 001.translated.png" in stream.getvalue()
    assert "SKIP 002.jpg -> 002.translated.png" in stream.getvalue()
    assert (output_dir / "_debug" / "review-pages.txt").read_text(encoding="utf-8") == ""


def test_run_batch_translation_fast_skip_preserves_existing_debug_texts_without_hidden_cache(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    source_path = input_dir / "001.jpg"
    target_path = output_dir / "001.translated.png"
    _save_image(source_path)
    _save_image(target_path, color="gray")
    writer = BatchDebugArtifactWriter(output_dir)
    writer.record_page(
        page={"id": "page-0001", "fileName": "001.jpg"},
        page_index=1,
        total_pages=1,
        source_path=source_path,
        target_path=target_path,
        status="translated",
        preprocessed_payload={
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["行くぞ"],
            "ocrResults": [{"text": "行くぞ", "engine": "manga_ocr"}],
            "rawMask": None,
        },
        translated_texts=["走吧"],
        translation_payload=None,
        classification={"page_type": "story", "should_translate": True, "skip_reason": None, "metrics": {}},
    )
    writer.finish({"total": 1, "succeeded": 1, "skipped": 0, "failed": 0})

    class ForbiddenSession:
        def __enter__(self):
            raise AssertionError("Saber should not start when all outputs already exist")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", ForbiddenSession)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
        overwrite_existing=False,
        cache_root=tmp_path / "empty-cache",
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "001.json").read_text(encoding="utf-8"))
    assert page_record["status"] == "skipped-existing"
    assert page_record["originalTexts"] == ["行くぞ"]
    assert page_record["translatedTexts"] == ["走吧"]
    assert page_record["needsReview"] is False


def test_run_batch_translation_preserves_existing_debug_for_partial_existing_outputs(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    source_one = input_dir / "001.jpg"
    source_two = input_dir / "002.jpg"
    target_one = output_dir / "001.translated.png"
    _save_image(source_one)
    _save_image(source_two)
    _save_image(target_one, color="gray")

    writer = BatchDebugArtifactWriter(output_dir)
    writer.record_page(
        page={"id": "page-0001", "fileName": "001.jpg"},
        page_index=1,
        total_pages=2,
        source_path=source_one,
        target_path=target_one,
        status="translated",
        preprocessed_payload={
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["待って"],
            "ocrResults": [{"text": "待って", "engine": "manga_ocr"}],
            "rawMask": None,
        },
        translated_texts=["等等"],
        translation_payload=None,
        classification={"page_type": "story", "should_translate": True, "skip_reason": None, "metrics": {}},
    )
    writer.finish({"total": 2, "succeeded": 1, "skipped": 0, "failed": 0})

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        stem = Path(source_path).stem
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return [f"zh-{text}" for text in texts]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
        api_key=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
        cache_root=tmp_path / "cache",
        overwrite_existing=False,
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "001.json").read_text(encoding="utf-8"))

    assert page_record["status"] == "skipped-existing"
    assert page_record["originalTexts"] == ["待って"]
    assert page_record["translatedTexts"] == ["等等"]
    assert page_record["reviewReasons"] == []


def test_run_batch_translation_overwrites_existing_outputs_when_enabled(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(input_dir / "002.png")
    _save_image(output_dir / "001.translated.png", color="gray")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    calls = []

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [Path(source_path).stem],
            "ocrResults": [{"text": Path(source_path).stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return [f"zh-{text}" for text in texts]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        calls.append((page_id, Path(source_path).name, translated_texts, saber_session))
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.75},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
        overwrite_existing=True,
    )

    assert calls == [
        ("page-0001", "001.jpg", ["zh-001"], "session-token"),
        ("page-0002", "002.png", ["zh-002"], "session-token"),
    ]
    assert summary["succeeded"] == 2
    assert summary["skipped"] == 0
    assert summary["failed"] == 0
    assert "SKIP 001.jpg -> 001.translated.png" not in stream.getvalue()


def test_run_batch_translation_uses_config_defaults_for_translation_and_overwrite(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(output_dir / "001.translated.png", color="gray")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [Path(source_path).stem],
            "ocrResults": [{"text": Path(source_path).stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["model"] = model
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return {
            "translatedTexts": [f"zh-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.load_settings",
        lambda project_root=None: {
            "translation": {
                "model": "config-model",
                "base_url": "https://config.example/v1",
                "api_key": "config-key",
            },
            "pipeline": {
                "overwrite_existing": True,
                "debug_output": True,
                "skip_frontmatter": True,
                "translate_batch_size": 3,
                "translate_batch_max_chars": 1600,
            },
            "paths": {},
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
    )

    assert summary["succeeded"] == 1
    assert summary["skipped"] == 0
    assert captured["model"] == "config-model"
    assert captured["base_url"] == "https://config.example/v1"
    assert captured["api_key"] == "config-key"


def test_run_batch_translation_reads_manga_context_file_and_passes_it_to_pipeline(tmp_path, monkeypatch):
    input_dir = tmp_path / "[藤子不二雄A] 笑ゥせぇるすまん 2"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    (input_dir / "manga_context.md").write_text(
        "## 作品定位\n黑色幽默短篇, 主角丧黑福造。\n\n## 翻译建议\n成年人语气, 少夸张标点。",
        encoding="utf-8",
    )

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["ドーン"],
            "ocrResults": [{"text": "ドーン", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["context_snapshot"] = context_snapshot
        return {
            "translatedTexts": ["咚"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        captured["pipeline_context_snapshot"] = context_snapshot
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "contextInputs": context_snapshot,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    assert "黑色幽默短篇" in captured["context_snapshot"]["mangaContext"]
    assert "丧黑福造" in captured["pipeline_context_snapshot"]["mangaContext"]

    page_record = json.loads((output_dir / "_debug" / "pages" / "001.json").read_text(encoding="utf-8"))
    assert page_record["mangaContext"]["generated"] is False
    assert "成年人语气" in page_record["mangaContext"]["content"]


def test_run_batch_translation_overwrite_refreshes_stale_debug_records_for_prefetched_cached_pages(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    source_paths = []
    for index in range(1, 7):
        source_path = input_dir / f"{index:03d}.jpg"
        _save_image(source_path)
        _save_image(output_dir / f"{index:03d}.translated.png", color="gray")
        source_paths.append(source_path)

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        stem = Path(source_path).stem
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return [f"zh-{text}" for text in texts]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stage_cache = BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
    )
    for source_path in source_paths[3:]:
        cached_preprocessed = fake_preprocess_page(source_path)
        stage_cache.save_translated(
            source_path,
            cached_preprocessed,
            [f"zh-{source_path.stem}"],
        )

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    stale_record = json.loads((output_dir / "_debug" / "pages" / "004.json").read_text(encoding="utf-8"))
    assert stale_record["status"] == "skipped-existing"

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        reporter=BatchProgressReporter(stream=StringIO()),
        overwrite_existing=True,
    )

    refreshed_record = json.loads((output_dir / "_debug" / "pages" / "004.json").read_text(encoding="utf-8"))

    assert summary["succeeded"] == 6
    assert summary["skipped"] == 0
    assert refreshed_record["status"] == "translated"


def test_run_batch_translation_finish_rewrites_page_debug_files_from_final_records(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["001"],
            "ocrResults": [{"text": "001", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return ["zh-001"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.5},
        }

    from translate_manga.cli import debug_artifacts as debug_artifacts_module

    class CorruptingWriter(debug_artifacts_module.BatchDebugArtifactWriter):
        def record_page(self, **kwargs):
            record = super().record_page(**kwargs)
            if record["status"] == "translated":
                page_json_path = self.pages_root / "001.json"
                corrupted = dict(record)
                corrupted["status"] = "skipped-existing"
                page_json_path.write_text(json.dumps(corrupted, ensure_ascii=False, indent=2), encoding="utf-8")
            return record

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr("translate_manga.cli.service.BatchDebugArtifactWriter", CorruptingWriter)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "001.json").read_text(encoding="utf-8"))

    assert summary["succeeded"] == 1
    assert page_record["status"] == "translated"


def test_run_batch_translation_writes_debug_text_records_for_translated_pages(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60], [50, 20, 90, 60]],
            "bubblePolygons": [
                [[10, 20], [40, 20], [40, 60], [10, 60]],
                [[50, 20], [90, 20], [90, 60], [50, 60]],
            ],
            "autoDirections": ["vertical", "vertical"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [],
            "originalTexts": ["だれと話してたんだ？", "またみたな例のユメを．．．"],
            "ocrResults": [
                {"text": "だれと話してたんだ？", "engine": "manga_ocr"},
                {"text": "またみたな例のユメを．．．", "engine": "manga_ocr"},
            ],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return ["刚才在和谁说话?", "又做了那个梦…"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.75},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    debug_root = output_dir / "_debug"
    page_record = json.loads((debug_root / "pages" / "001.json").read_text(encoding="utf-8"))

    assert page_record["status"] == "translated"
    assert page_record["sourceName"] == "001.jpg"
    assert page_record["pageType"] == "story"
    assert page_record["originalTexts"] == ["だれと話してたんだ？", "またみたな例のユメを．．．"]
    assert page_record["translatedTexts"] == ["刚才在和谁说话?", "又做了那个梦…"]
    assert page_record["needsReview"] is False
    assert (debug_root / "texts" / "001.ocr.txt").read_text(encoding="utf-8") == "だれと話してたんだ？\n\nまたみたな例のユメを．．．"
    assert (debug_root / "texts" / "001.translation.txt").read_text(encoding="utf-8") == "刚才在和谁说话?\n\n又做了那个梦…"
    assert "001.jpg" in (debug_root / "book.ocr.txt").read_text(encoding="utf-8")
    assert "刚才在和谁说话?" in (debug_root / "book.translation.txt").read_text(encoding="utf-8")
    manifest_lines = (debug_root / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 1
    assert json.loads(manifest_lines[0])["outputName"] == "001.translated.png"


def test_debug_writer_flags_translation_failure_placeholders(tmp_path):
    output_dir = tmp_path / "output"
    source_path = tmp_path / "input" / "001.jpg"
    target_path = output_dir / "001.translated.png"
    writer = BatchDebugArtifactWriter(output_dir)

    record = writer.record_page(
        page={"id": "page-0001", "fileName": "001.jpg"},
        page_index=1,
        total_pages=1,
        source_path=source_path,
        target_path=target_path,
        status="translated",
        preprocessed_payload={
            "bubbleCoords": [[10, 20, 40, 60]],
            "originalTexts": ["こんにちは"],
        },
        translated_texts=[TRANSLATION_FAILURE_TEXT],
        translation_payload={
            "translatedTexts": [TRANSLATION_FAILURE_TEXT],
            "rounds": [
                {
                    "name": "final",
                    "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                    "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                }
            ],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": True, "reasons": ["translation_failed"], "attempted": False, "applied": False},
        },
        classification={"page_type": "story", "should_translate": True, "skip_reason": None, "metrics": {}},
    )
    writer.finish({"total": 1, "succeeded": 1, "skipped": 0, "failed": 0})

    summary_payload = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))
    failed_tsv = (output_dir / "_debug" / "failed-translations.tsv").read_text(encoding="utf-8")
    review_pages = (output_dir / "_debug" / "review-pages.txt").read_text(encoding="utf-8")
    final_report = (output_dir / "_debug" / "final-review-report.txt").read_text(encoding="utf-8")

    assert record["needsReview"] is True
    assert "translation_failed" in record["reviewReasons"]
    assert "translation_failure_placeholder" in record["reviewReasons"]
    assert "001.jpg" in review_pages
    assert failed_tsv.splitlines()[0] == "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath"
    assert "001.jpg\t001.translated.png\ttranslated\ttranslation_failed,translation_failure_placeholder" in failed_tsv
    assert summary_payload["reviewReasonCounts"]["translation_failed"] == 1
    assert summary_payload["reviewReasonCounts"]["translation_failure_placeholder"] == 1
    assert "仍需复查: 1" in final_report
    assert "001.jpg" in final_report
    assert "translation_failed,translation_failure_placeholder" in final_report


def test_load_retry_review_page_names_detects_short_translation_failure_text_in_page_json(tmp_path):
    input_dir = tmp_path / "book"
    output_dir = input_dir / "out"
    debug_root = output_dir / "_debug"
    pages_root = debug_root / "pages"
    input_dir.mkdir(parents=True)
    pages_root.mkdir(parents=True)
    source_path = input_dir / "001.jpg"
    _save_image(source_path)
    _save_image(output_dir / "001.translated.png")
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "translatedTexts": ["翻译失败"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert _load_retry_review_page_names(output_dir, [source_path]) == {"001.jpg"}


def test_load_retry_review_page_names_detects_translation_failure_text_file_without_page_json(tmp_path):
    input_dir = tmp_path / "book"
    output_dir = input_dir / "out"
    texts_root = output_dir / "_debug" / "texts"
    input_dir.mkdir(parents=True)
    texts_root.mkdir(parents=True)
    source_path = input_dir / "001.jpg"
    _save_image(source_path)
    _save_image(output_dir / "001.translated.png")
    (texts_root / "001.translation.txt").write_text("翻译失败\n", encoding="utf-8")

    assert _load_retry_review_page_names(output_dir, [source_path]) == {"001.jpg"}


def test_debug_writer_preserves_empty_translation_slots(tmp_path):
    output_dir = tmp_path / "output"
    source_path = tmp_path / "input" / "001.jpg"
    target_path = output_dir / "001.translated.png"
    writer = BatchDebugArtifactWriter(output_dir)

    record = writer.record_page(
        page={"id": "page-0001", "fileName": "001.jpg"},
        page_index=1,
        total_pages=1,
        source_path=source_path,
        target_path=target_path,
        status="translated",
        preprocessed_payload={
            "bubbleCoords": [[10, 20, 40, 60], [50, 20, 90, 60], [100, 20, 140, 60]],
            "originalTexts": ["SFX-A", "NOISE", "SFX-B"],
        },
        translated_texts=["A!!", "", "B!!"],
        translation_payload={
            "translatedTexts": ["A!!", "", "B!!"],
            "rounds": [
                {
                    "name": "final",
                    "translatedTexts": ["A!!", "", "B!!"],
                    "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
                }
            ],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
        classification={"page_type": "story", "should_translate": True, "skip_reason": None, "metrics": {}},
    )

    assert record["translatedTexts"] == ["A!!", "", "B!!"]
    assert record["translation"]["rounds"][0]["translatedTexts"] == ["A!!", "", "B!!"]
    assert record["needsReview"] is False
    assert "translation_count_mismatch" not in record["reviewReasons"]


def test_debug_writer_summarizes_timing_breakdown(tmp_path):
    output_dir = tmp_path / "out"
    writer = BatchDebugArtifactWriter(output_dir)

    for index, timings in enumerate(
        [
            {"detect": 1.0, "ocr": 2.0, "color": 3.0, "translate": 4.0, "render": 5.0, "total": 15.0},
            {"detect": 2.0, "ocr": 4.0, "color": 6.0, "translate": 8.0, "render": 10.0, "total": 30.0},
        ],
        start=1,
    ):
        writer.record_page(
            page={"id": f"page-{index}", "fileName": f"{index:03d}.jpg"},
            page_index=index,
            total_pages=2,
            source_path=tmp_path / f"{index:03d}.jpg",
            target_path=output_dir / f"{index:03d}.translated.png",
            status="translated",
            preprocessed_payload={"bubbleCoords": [], "originalTexts": [], "timings": timings},
            translated_texts=[],
            translation_payload=None,
            classification={"should_translate": False, "page_type": "blank", "skip_reason": "blank"},
        )

    writer.finish({"total": 2, "succeeded": 2, "skipped": 0, "failed": 0})
    summary = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))
    report = (output_dir / "_debug" / "final-review-report.txt").read_text(encoding="utf-8")

    assert summary["timingSummary"]["pageCount"] == 2
    assert summary["timingSummary"]["totals"]["ocr"] == 6.0
    assert summary["timingSummary"]["averages"]["total"] == 22.5
    assert summary["timingSummary"]["slowestPages"][0]["sourceName"] == "002.jpg"
    assert "## 阶段耗时汇总" in report
    assert "ocr: total=6.00s avg=3.00s" in report


def test_debug_writer_flushes_indexes_by_interval(tmp_path):
    output_dir = tmp_path / "out"
    writer = BatchDebugArtifactWriter(output_dir, flush_interval=3)

    for index in range(1, 3):
        writer.record_page(
            page={"id": f"page-{index}", "fileName": f"{index:03d}.jpg"},
            page_index=index,
            total_pages=2,
            source_path=tmp_path / f"{index:03d}.jpg",
            target_path=output_dir / f"{index:03d}.translated.png",
            status="translated",
            preprocessed_payload={
                "bubbleCoords": [],
                "originalTexts": [f"ocr-{index}"],
                "timings": {},
            },
            translated_texts=[f"zh-{index}"],
            translation_payload=None,
            classification={"should_translate": True, "page_type": "content", "skip_reason": None},
        )
        assert (output_dir / "_debug" / "pages" / f"{index:03d}.json").exists()

    assert not (output_dir / "_debug" / "summary.json").exists()
    writer.finish({"total": 2, "succeeded": 2, "skipped": 0, "failed": 0})

    assert (output_dir / "_debug" / "summary.json").exists()
    assert "ocr-1" in (output_dir / "_debug" / "book.ocr.txt").read_text(encoding="utf-8")


def test_run_batch_translation_writes_multiround_debug_records(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["こんにちは"],
            "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, context_snapshot=None):
        return {
            "translatedTexts": ["你好呀"],
            "rounds": [
                {"name": "draft", "translatedTexts": ["你好"], "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120, "estimated": False}},
                {"name": "contextual", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 140, "outputTokens": 22, "totalTokens": 162, "estimated": False}},
                {"name": "final", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 80, "outputTokens": 10, "totalTokens": 90, "estimated": False}},
            ],
            "tokenUsage": {"inputTokens": 320, "outputTokens": 52, "totalTokens": 372, "estimated": False},
            "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": False, "reasons": []},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.75},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    debug_root = output_dir / "_debug"
    page_record = json.loads((debug_root / "pages" / "001.json").read_text(encoding="utf-8"))

    assert page_record["translation"]["rounds"][0]["name"] == "draft"
    assert page_record["translation"]["rounds"][1]["translatedTexts"] == ["你好呀"]
    assert page_record["tokenUsage"]["totalTokens"] == 372
    assert page_record["ocrRetry"]["attempted"] is False
    assert (debug_root / "texts" / "001.draft.translation.txt").read_text(encoding="utf-8") == "你好"
    assert (debug_root / "texts" / "001.contextual.translation.txt").read_text(encoding="utf-8") == "你好呀"
    assert (debug_root / "texts" / "001.final.translation.txt").read_text(encoding="utf-8") == "你好呀"


def test_batch_stage_cache_round_trip(tmp_path):
    input_dir = tmp_path / "input"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)

    cache = BatchStageCache(
        cache_root=tmp_path / "hidden-cache",
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )
    preprocessed_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["さあ"],
        "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        "rawMask": None,
    }

    cache.save_translated(source_path, preprocessed_payload, ["来吧"])

    loaded = cache.load_best(source_path)

    assert loaded["stage"] == "translated"
    assert loaded["translatedTexts"] == ["来吧"]
    assert loaded["preprocessed"]["bubbleCoords"] == [[10, 20, 40, 60]]


def test_batch_stage_cache_round_trip_preserves_translation_payload(tmp_path):
    input_dir = tmp_path / "input"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)

    cache = BatchStageCache(
        cache_root=tmp_path / "hidden-cache",
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
    )
    preprocessed_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["こんにちは"],
        "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    translation_payload = {
        "translatedTexts": ["你好呀"],
        "rounds": [
            {"name": "draft", "translatedTexts": ["你好"], "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120, "estimated": False}},
            {"name": "contextual", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 140, "outputTokens": 22, "totalTokens": 162, "estimated": False}},
            {"name": "final", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 80, "outputTokens": 10, "totalTokens": 90, "estimated": False}},
        ],
        "tokenUsage": {"inputTokens": 320, "outputTokens": 52, "totalTokens": 372, "estimated": False},
        "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": False, "reasons": []},
    }

    cache.save_translated(source_path, preprocessed_payload, ["你好呀"], translation_payload)

    loaded = cache.load_best(source_path)

    assert loaded["stage"] == "translated"
    assert loaded["translationPayload"]["tokenUsage"]["totalTokens"] == 372
    assert loaded["translationPayload"]["rounds"][0]["name"] == "draft"


def test_batch_stage_cache_downgrades_stale_translated_stage_to_preprocessed(tmp_path):
    input_dir = tmp_path / "input"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)

    preprocessed_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["さあ"],
        "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        "rawMask": None,
    }

    BatchStageCache(
        cache_root=tmp_path / "hidden-cache",
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature="sig-v1",
    ).save_translated(source_path, preprocessed_payload, ["旧译文"])

    loaded = BatchStageCache(
        cache_root=tmp_path / "hidden-cache",
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature="sig-v2",
    ).load_best(source_path)

    assert loaded["stage"] == "preprocessed"
    assert loaded["translatedTexts"] is None
    assert loaded["preprocessed"]["originalTexts"] == ["さあ"]


def test_run_batch_translation_retry_review_pages_only_processes_failed_translation_list(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    for name in ["001.jpg", "002.jpg", "003.jpg"]:
        _save_image(input_dir / name)
        _save_image(output_dir / f"{Path(name).stem}.translated.png", color="white")

    debug_pages_root = output_dir / "_debug" / "pages"
    debug_pages_root.mkdir(parents=True)
    (debug_pages_root / "001.json").write_text(
        json.dumps(
            {
                "pageId": "page-0001",
                "pageIndex": 1,
                "totalPages": 3,
                "sourceName": "001.jpg",
                "sourcePath": str(input_dir / "001.jpg"),
                "outputName": "001.translated.png",
                "outputPath": str(output_dir / "001.translated.png"),
                "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "originalTexts": ["ok"],
                "translatedTexts": ["ok"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (debug_pages_root / "002.json").write_text(
        json.dumps(
            {
                "pageId": "page-0002",
                "pageIndex": 2,
                "totalPages": 3,
                "sourceName": "002.jpg",
                "sourcePath": str(input_dir / "002.jpg"),
                "outputName": "002.translated.png",
                "outputPath": str(output_dir / "002.translated.png"),
                "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                "translation": {
                    "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                    "ocrRetry": {
                        "shouldRetry": True,
                        "reasons": ["translation_failed"],
                        "attempted": False,
                        "applied": False,
                    },
                },
                "ocrRetry": {
                    "shouldRetry": True,
                    "reasons": ["translation_failed"],
                    "attempted": False,
                    "applied": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    preprocessed_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["old text"],
        "ocrResults": [{"text": "old text", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
        preprocess_signature=_current_preprocess_signature(),
    ).save_translated(
        input_dir / "002.jpg",
        preprocessed_payload,
        [TRANSLATION_FAILURE_TEXT],
        {
            "translatedTexts": [TRANSLATION_FAILURE_TEXT],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": True, "reasons": ["translation_failed"], "attempted": False, "applied": False},
        },
    )

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    preprocess_calls = []
    translated_batches = []
    rendered_sources = []

    def fake_preprocess_page(source_path, saber_session=None):
        preprocess_calls.append(Path(source_path).name)
        return preprocessed_payload

    def fake_translate_texts_multi_round(texts, model, base_url, api_key=None, context_snapshot=None):
        translated_batches.append(list(texts))
        return {
            "translatedTexts": ["new translation"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        rendered_sources.append(Path(source_path).name)
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {
                "bubble_count": 1,
                "text_count": 1,
                "total_chars": 11,
            },
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
        retry_review_pages=True,
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "002.json").read_text(encoding="utf-8"))
    summary_payload = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))
    manifest_sources = [
        json.loads(line)["sourceName"]
        for line in (output_dir / "_debug" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert preprocess_calls == []
    assert translated_batches == [["old text"]]
    assert rendered_sources == ["002.jpg"]
    assert page_record["sourceName"] == "002.jpg"
    assert page_record["pageIndex"] == 2
    assert page_record["totalPages"] == 3
    assert page_record["translatedTexts"] == ["new translation"]
    assert page_record["needsReview"] is False
    assert summary_payload["recordedPages"] == 2
    assert manifest_sources == ["001.jpg", "002.jpg"]


def test_run_batch_translation_retry_review_pages_processes_quality_review_tsv_when_enabled(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    for name in ["001.jpg", "002.jpg"]:
        _save_image(input_dir / name)
        _save_image(output_dir / f"{Path(name).stem}.translated.png", color="white")
    debug_root = output_dir / "_debug"
    debug_root.mkdir(parents=True)
    (debug_root / "quality-review.tsv").write_text(
        "sourceName\toutputName\treasons\tconfidence\tcomment\n"
        "002.jpg\t002.translated.png\tquality_awkward_chinese\t0.9\t译文不通顺\n",
        encoding="utf-8",
    )

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    translated_batches = []
    rendered_sources = []

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [Path(source_path).stem],
            "ocrResults": [{"text": Path(source_path).stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key=None, context_snapshot=None):
        translated_batches.append(list(texts))
        return {
            "translatedTexts": [f"zh-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        rendered_sources.append(Path(source_path).name)
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {
                "bubble_count": 1,
                "text_count": 1,
                "total_chars": 11,
            },
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
        retry_review_pages=True,
        retry_quality_review_pages=True,
    )

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert translated_batches == [["002"]]
    assert rendered_sources == ["002.jpg"]


def test_run_batch_translation_retry_review_pages_processes_missing_output_pages(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    for name in ["001.jpg", "002.jpg", "003.jpg"]:
        _save_image(input_dir / name)
    _save_image(output_dir / "001.translated.png", color="white")
    _save_image(output_dir / "003.translated.png", color="white")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    preprocess_calls = []
    translated_batches = []
    rendered_sources = []

    def fake_preprocess_page(source_path, saber_session=None):
        preprocess_calls.append(Path(source_path).name)
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [Path(source_path).stem],
            "ocrResults": [{"text": Path(source_path).stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key=None, context_snapshot=None):
        translated_batches.append(list(texts))
        return {
            "translatedTexts": [f"zh-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        rendered_sources.append(Path(source_path).name)
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {
                "bubble_count": 1,
                "text_count": 1,
                "total_chars": 11,
            },
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
        retry_review_pages=True,
    )

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert preprocess_calls == ["002.jpg"]
    assert translated_batches == [["002"]]
    assert rendered_sources == ["002.jpg"]
    assert (output_dir / "002.translated.png").exists()


def test_run_batch_translation_retry_review_pages_uses_debug_preprocess_and_neighbor_context(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    for name in ["001.jpg", "002.jpg", "003.jpg"]:
        _save_image(input_dir / name)
        _save_image(output_dir / f"{Path(name).stem}.translated.png", color="white")

    debug_pages_root = output_dir / "_debug" / "pages"
    debug_pages_root.mkdir(parents=True)
    (debug_pages_root / "001.json").write_text(
        json.dumps(
                {
                    "pageId": "page-0001",
                    "pageIndex": 1,
                    "sourceName": "001.jpg",
                    "sourcePath": str(input_dir / "001.jpg"),
                    "outputName": "001.translated.png",
                    "outputPath": str(output_dir / "001.translated.png"),
                    "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "originalTexts": ["殿"],
                "translatedTexts": ["主公"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (debug_pages_root / "002.json").write_text(
        json.dumps(
                {
                    "pageId": "page-0002",
                    "pageIndex": 2,
                    "sourceName": "002.jpg",
                    "sourcePath": str(input_dir / "002.jpg"),
                    "outputName": "002.translated.png",
                    "outputPath": str(output_dir / "002.translated.png"),
                    "status": "translated",
                "needsReview": True,
                "reviewReasons": ["translation_failed"],
                "originalTexts": ["失敗"],
                "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                "translation": {
                    "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                    "ocrRetry": {"reasons": ["translation_failed"]},
                },
                "preprocessedPayload": {
                    "bubbleCoords": [[10, 20, 40, 60]],
                    "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
                    "autoDirections": ["vertical"],
                    "textlinesPerBubble": [[]],
                    "bubbleColors": [],
                    "originalTexts": ["失敗"],
                    "ocrResults": [{"text": "失敗", "engine": "manga_ocr"}],
                    "rawMask": None,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (debug_pages_root / "003.json").write_text(
        json.dumps(
                {
                    "pageId": "page-0003",
                    "pageIndex": 3,
                    "sourceName": "003.jpg",
                    "sourcePath": str(input_dir / "003.jpg"),
                    "outputName": "003.translated.png",
                    "outputPath": str(output_dir / "003.translated.png"),
                    "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "originalTexts": ["忠義"],
                "translatedTexts": ["忠义"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fail_preprocess_page(source_path, saber_session=None):
        raise AssertionError("retry should reuse preprocessedPayload from debug record")

    def fake_translate_texts_multi_round(texts, model, base_url, api_key=None, context_snapshot=None):
        captured["texts"] = list(texts)
        captured["context_snapshot"] = context_snapshot
        return {
            "translatedTexts": ["修复译文"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        captured["preprocessed_payload"] = preprocessed_payload
        captured["pipeline_context_snapshot"] = context_snapshot
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [{"originalText": "失敗", "translatedText": "修复译文"}],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "contextInputs": context_snapshot,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fail_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
        retry_review_pages=True,
    )

    assert summary["total"] == 1
    assert captured["texts"] == ["失敗"]
    assert captured["preprocessed_payload"]["originalTexts"] == ["失敗"]
    assert "主公" in captured["context_snapshot"]["confirmedTranslations"]
    assert "忠义" in captured["context_snapshot"]["confirmedTranslations"]
    assert TRANSLATION_FAILURE_TEXT not in captured["context_snapshot"]["confirmedTranslations"]
    assert captured["pipeline_context_snapshot"]["confirmedTranslations"] == captured["context_snapshot"]["confirmedTranslations"]


def test_run_batch_translation_processes_only_explicit_target_page_names(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    for name in ["001.jpg", "002.jpg", "003.jpg"]:
        _save_image(input_dir / name)

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    preprocess_calls = []
    render_calls = []

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        preprocess_calls.append(Path(source_path).name)
        stem = Path(source_path).stem
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        return {
            "translatedTexts": [f"译文-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        render_calls.append(Path(source_path).name)
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {
                "bubble_count": 1,
                "text_count": 1,
                "total_chars": 11,
            },
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
        target_page_names=["002.jpg"],
    )

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert preprocess_calls == ["002.jpg"]
    assert render_calls == ["002.jpg"]
    assert (output_dir / "002.translated.png").exists()
    assert not (output_dir / "001.translated.png").exists()
    assert not (output_dir / "003.translated.png").exists()


def test_run_batch_translation_reprocesses_target_page_when_debug_ocr_engine_mismatches_style(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)
    (output_dir / "_debug" / "pages").mkdir(parents=True)
    (output_dir / "_debug" / "pages" / "001.json").write_text(
        json.dumps(
            {
                "pageId": "page-0001",
                "sourceName": "001.jpg",
                "originalTexts": ["ENO"],
                "translatedTexts": ["ENO"],
                "preprocessedPayload": {
                    "bubbleCoords": [[10, 20, 40, 60]],
                    "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
                    "autoDirections": ["h"],
                    "textlinesPerBubble": [[{"direction": "h"}]],
                    "bubbleColors": [],
                    "originalTexts": ["ENO"],
                    "ocrResults": [{"text": "ENO", "engine": "paddle_ocr", "primaryEngine": "paddle_ocr"}],
                    "rawMask": None,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    preprocess_calls = []
    captured = {}

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        preprocess_calls.append({"name": Path(source_path).name, "ocr_options": dict(ocr_options or {})})
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[{"direction": "v"}]],
            "bubbleColors": [],
            "originalTexts": ["こんにちは"],
            "ocrResults": [{"text": "こんにちは", "engine": "48px_ocr", "primaryEngine": "48px_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["texts"] = list(texts)
        return {
            "translatedTexts": ["你好"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        captured["preprocessed_payload"] = preprocessed_payload
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {"bubble_count": 1, "text_count": 1, "total_chars": 5},
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
        target_page_names=["001.jpg"],
        style_id="auto",
    )

    assert summary["succeeded"] == 1
    assert [call["name"] for call in preprocess_calls] == ["001.jpg"]
    assert preprocess_calls[0]["ocr_options"]["source_language"] == "japanese"
    assert preprocess_calls[0]["ocr_options"]["reading_order"] == "rtl"
    assert preprocess_calls[0]["ocr_options"]["engine"] == "48px_ocr"
    assert captured["texts"] == ["こんにちは"]
    assert captured["preprocessed_payload"]["originalTexts"] == ["こんにちは"]


def test_run_batch_translation_normalizes_title_caption_text_before_translation(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    input_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (820, 1200), "white").save(input_dir / "001.jpg")
    captured = {}

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        return {
            "bubbleCoords": [[45, 11, 167, 133]],
            "bubblePolygons": [[[131, 144], [32, 21], [96, -30], [195, 93]]],
            "autoDirections": ["h"],
            "textlinesPerBubble": [
                [
                    {"polygon": [[45, 11], [75, 11], [75, 37], [45, 37]], "direction": "h"},
                    {"polygon": [[102, 14], [130, 14], [130, 37], [102, 37]], "direction": "h"},
                    {"polygon": [[147, 58], [167, 58], [167, 116], [147, 116]], "direction": "v"},
                    {"polygon": [[123, 57], [143, 57], [142, 133], [122, 133]], "direction": "v"},
                ]
            ],
            "bubbleColors": [],
            "originalTexts": ["誕 生 山中に おいても"],
            "ocrResults": [{"text": "誕 生 山中に おいても", "engine": "48px_ocr", "confidence": 0.97}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["texts"] = list(texts)
        return {
            "translatedTexts": ["即便在深山中也诞生"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "story",
            "should_translate": True,
            "skip_reason": None,
            "metrics": {
                "bubble_count": 1,
                "text_count": 1,
                "total_chars": 11,
            },
        },
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    assert summary["succeeded"] == 1
    assert captured["texts"] == ["誕生山中においても"]


def test_run_batch_translation_invalidates_hidden_cache_when_ocr_config_changes(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    preprocess_calls = []

    def fake_preprocess_page(source_path, saber_session=None):
        preprocess_calls.append(Path(source_path).name)
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["001"],
            "ocrResults": [{"text": "001", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    settings_by_engine = {
        "manga_ocr": {
            "translation": {
                "model": "mimo-v2.5-pro",
                "base_url": TEST_BASE_URL,
                "api_key": "",
            },
            "pipeline": {
                "overwrite_existing": False,
                "debug_output": True,
                "skip_frontmatter": True,
                "translate_batch_size": 3,
                "translate_batch_max_chars": 1600,
                "auto_generate_manga_context": False,
            },
            "render": {
                "layout_mode": "vertical",
            },
            "paths": {},
            "ocr": {
                "engine": "manga_ocr",
                "enable_hybrid": False,
                "secondary_engine": "",
                "hybrid_threshold": 0.2,
                "fallback_to_manga_ocr_when_48px_unavailable": True,
            },
        },
        "48px_ocr": {
            "translation": {
                "model": "mimo-v2.5-pro",
                "base_url": TEST_BASE_URL,
                "api_key": "",
            },
            "pipeline": {
                "overwrite_existing": False,
                "debug_output": True,
                "skip_frontmatter": True,
                "translate_batch_size": 3,
                "translate_batch_max_chars": 1600,
                "auto_generate_manga_context": False,
            },
            "render": {
                "layout_mode": "vertical",
            },
            "paths": {},
            "ocr": {
                "engine": "48px_ocr",
                "enable_hybrid": True,
                "secondary_engine": "manga_ocr",
                "hybrid_threshold": 0.2,
                "fallback_to_manga_ocr_when_48px_unavailable": True,
            },
        },
    }
    current_engine = {"value": "manga_ocr"}

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", lambda texts, model, base_url, context_snapshot=None: [f"zh-{text}" for text in texts])
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr("translate_manga.cli.service.load_settings", lambda project_root=None: settings_by_engine[current_engine["value"]])

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )
    preprocess_calls.clear()

    current_engine["value"] = "48px_ocr"
    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        overwrite_existing=True,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    assert preprocess_calls == ["001.jpg"]


def test_run_batch_translation_skips_existing_output_without_preprocess_when_hidden_cache_missing(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(output_dir / "001.translated.png", color="gray")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "translate_manga.cli.service.preprocess_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.run_page_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_page_pipeline should not run")),
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=tmp_path / "hidden-cache",
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    assert summary["skipped"] == 1
    assert summary["succeeded"] == 0


def test_run_batch_translation_batches_page_texts_and_reuses_hidden_cache(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    _save_image(input_dir / "001.jpg")
    _save_image(input_dir / "002.jpg")

    cached_preprocessed = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["cached-001"],
        "ocrResults": [{"text": "cached-001", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
        preprocess_signature=_current_preprocess_signature(),
    ).save_translated(input_dir / "001.jpg", cached_preprocessed, ["缓存译文"])

    captured = {
        "preprocess": [],
        "translate_calls": [],
        "finalize": [],
    }

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        captured["preprocess"].append((Path(source_path).name, saber_session))
        stem = Path(source_path).stem
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        captured["translate_calls"].append(list(texts))
        return [f"zh-{text}" for text in texts]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        captured["finalize"].append(
            (Path(source_path).name, preprocessed_payload["originalTexts"], translated_texts, saber_session)
        )
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="green")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 1.25},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    assert captured["preprocess"] == [("002.jpg", "session-token")]
    assert captured["translate_calls"] == [["002"]]
    assert captured["finalize"] == [
        ("001.jpg", ["cached-001"], ["缓存译文"], "session-token"),
        ("002.jpg", ["002"], ["zh-002"], "session-token"),
    ]
    assert (output_dir / "001.translated.png").exists()
    assert (output_dir / "002.translated.png").exists()
    assert summary["succeeded"] == 2


def test_run_batch_translation_reflows_cached_long_narration_before_render(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)

    original_text = (
        "どうも、オオカミの生活に、たちいりすぎたようだ。"
        "しかも、この白オオカミの成長は、この物語に同時的にあつかわれている。"
    ) * 5
    cached_preprocessed = {
        "bubbleCoords": [[72, 678, 748, 1078]],
        "bubblePolygons": [[[72, 678], [748, 678], [748, 1078], [72, 1078]]],
        "autoDirections": ["v"],
        "textlinesPerBubble": [[{"direction": "v"} for _ in range(24)]],
        "bubbleColors": [{"edgeDensity": 0.09, "darkPixelRatio": 0.001, "grayStdDev": 10.0}],
        "originalTexts": [original_text],
        "ocrResults": [{"text": original_text, "engine": "manga_ocr", "confidence": 0.66, "fallbackUsed": True}],
        "rawMask": None,
    }
    cached_translation = (
        "看来我们对狼的生活介入过深了。况且，这只白狼的成长，与本故事同时描绘的人类社会部分并无关联。"
        "因此，白狼在族群中遭受的歧视问题，也不能与人类社会的歧视问题等同视之。"
        "在人类社会，歧视是为维护统治者利益而制定的政策，身份被法制化。"
        "而在白狼的情况中，这不过是自然造就的个人不幸之一例，与历史毫无关联。"
    )
    BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
        preprocess_signature=_current_preprocess_signature(),
    ).save_translated(source_path, cached_preprocessed, [cached_translation])

    captured = {}

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translated_texts=None,
        **kwargs,
    ):
        captured["translated_texts"] = translated_texts
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="green")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 1.25},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "translate_manga.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cached page should not translate")),
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
        style_id="style2",
    )

    rendered_text = captured["translated_texts"][0]
    assert "\n" in rendered_text
    assert max(len(line) for line in rendered_text.splitlines()) <= 32
    assert summary["succeeded"] == 1


def test_run_batch_translation_logs_prepare_translate_render_stages(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
            "rawMask": None,
            "timings": {"total": 1.5},
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return ["来吧"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="purple")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.75},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    output = stream.getvalue()

    assert "PREP 001.jpg start" in output
    assert "PREP 001.jpg done" in output
    assert "TRANSLATE start pages=001.jpg" in output
    assert "TRANSLATE done pages=001.jpg" in output
    assert "RENDER 001.jpg start" in output
    assert summary["succeeded"] == 1


def test_run_batch_translation_records_batch_translate_timing_in_debug(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    counter = {"value": 0.0}

    def fake_perf_counter():
        counter["value"] += 1.0
        return counter["value"]

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
            "rawMask": None,
            "timings": {"detect": 0.5, "ocr": 0.5, "color": 0.25, "total": 1.25},
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        return ["来吧"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="purple")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {
                "detect": 0.5,
                "ocr": 0.5,
                "color": 0.25,
                "inpaint": 0.25,
                "render": 0.25,
                "translate": 0.0,
                "total": 1.75,
            },
        }

    monkeypatch.setattr("translate_manga.cli.service.perf_counter", fake_perf_counter)
    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "001.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))

    assert page_record["timings"]["translate"] > 0
    assert summary["timingSummary"]["totals"]["translate"] > 0
    assert summary["timingSummary"]["averages"]["total"] >= page_record["timings"]["translate"]


def test_run_batch_translation_copies_frontmatter_without_translate(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    source_path = input_dir / "000a.jpg"
    _save_image(source_path, color="red")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[640, 120, 680, 340]],
            "bubblePolygons": [[[640, 120], [680, 120], [680, 340], [640, 340]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["第一章"],
            "ocrResults": [{"text": "第一章", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "frontmatter",
            "should_translate": False,
            "skip_reason": "frontmatter",
        },
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.run_page_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_page_pipeline should not run")),
    )

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    output_path = output_dir / "000a.translated.png"
    debug_root = output_dir / "_debug"
    assert output_path.exists()
    assert Image.open(output_path).getpixel((0, 0)) == Image.open(source_path).getpixel((0, 0))
    assert summary["succeeded"] == 1
    assert "COPY 000a.jpg -> 000a.translated.png (frontmatter)" in stream.getvalue()
    page_record = json.loads((debug_root / "pages" / "000a.json").read_text(encoding="utf-8"))
    assert page_record["status"] == "copied"
    assert page_record["skipReason"] == "frontmatter"
    assert page_record["pageType"] == "frontmatter"
    assert page_record["translatedTexts"] == []
    assert (debug_root / "texts" / "000a.ocr.txt").read_text(encoding="utf-8") == "第一章"
    assert (debug_root / "texts" / "000a.translation.txt").read_text(encoding="utf-8") == ""


def test_run_batch_translation_flags_suspicious_frontmatter_for_review(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    for index in range(1, 12):
        _save_image(input_dir / f"i-{index:04d}.jpg", color="red")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    texts = [
        "犬田と数宮の走り方おもしれーな",
        "なんだありゃ",
        "オカマか",
        "ガハハハバハハ",
        "前に進んでねえみてえだ",
        "膝ジップ",
        "あり得ねえギャハハハ八ハハ",
        "はッはっはっ",
        "はぁはあはあぁ",
        "ＤｉｍｂｅＤ：２０",
        "ばたばたははあはた",
        "犬田２０秒１８",
        "数宮２０秒１６",
        "ぜーは",
        "ボクよりやせてるのに．．．",
    ]

    def fake_preprocess_page(source_path, saber_session=None):
        if Path(source_path).stem != "i-0011":
            return {
                "bubbleCoords": [],
                "bubblePolygons": [],
                "autoDirections": [],
                "textlinesPerBubble": [],
                "bubbleColors": [],
                "originalTexts": [],
                "ocrResults": [],
                "rawMask": None,
            }
        return {
            "bubbleCoords": [[10, 20, 40, 80] for _ in texts],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 80], [10, 80]] for _ in texts],
            "autoDirections": ["vertical" for _ in texts],
            "textlinesPerBubble": [[] for _ in texts],
            "bubbleColors": [],
            "originalTexts": texts,
            "ocrResults": [{"text": text, "engine": "manga_ocr"} for text in texts],
            "rawMask": None,
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: (
            {
                "page_type": "frontmatter",
                "should_translate": False,
                "skip_reason": "frontmatter",
                "metrics": {
                    "bubble_count": len(texts),
                    "text_count": len(texts),
                    "total_chars": sum(len(text) for text in texts),
                    "max_area_ratio": 0.028125,
                    "tall_narrow_ratio": 0.6,
                },
            }
            if kwargs["page_index"] == 11
            else {
                "page_type": "blank",
                "should_translate": False,
                "skip_reason": "blank",
                "metrics": {
                    "bubble_count": 0,
                    "text_count": 0,
                    "total_chars": 0,
                },
            }
        ),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.run_page_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_page_pipeline should not run")),
    )

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "i-0011.json").read_text(encoding="utf-8"))

    assert page_record["needsReview"] is True
    assert "suspicious_frontmatter" in page_record["reviewReasons"]


def test_run_batch_translation_retries_failed_batch_per_page(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(input_dir / "002.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    translate_calls = []
    finalized = []

    def fake_preprocess_page(source_path, saber_session=None):
        stem = Path(source_path).stem
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        translate_calls.append(list(texts))
        if len(texts) > 1:
            raise TimeoutError("batch timeout")
        return [f"zh-{texts[0]}"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
    ):
        finalized.append((Path(source_path).name, translated_texts))
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    assert translate_calls == [["001"], ["002"]]
    assert finalized == [("001.jpg", ["zh-001"]), ("002.jpg", ["zh-002"])]
    assert summary["succeeded"] == 2
    assert "TRANSLATE retry-single" not in stream.getvalue()


def test_run_batch_translation_records_preprocess_failure_and_continues(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    _save_image(input_dir / "002.jpg")
    _save_image(input_dir / "003.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    finalized = []

    def fake_preprocess_page(source_path, saber_session=None):
        stem = Path(source_path).stem
        if stem == "002":
            raise TimeoutError("preprocess timeout")
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": [stem],
            "ocrResults": [{"text": stem, "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="", context_snapshot=None):
        return {
            "translatedTexts": [f"zh-{text}" for text in texts],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        finalized.append((Path(source_path).name, translated_texts))
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    failed_record = json.loads((output_dir / "_debug" / "pages" / "002.json").read_text(encoding="utf-8"))
    failed_tsv = (output_dir / "_debug" / "failed-translations.tsv").read_text(encoding="utf-8")

    assert summary["succeeded"] == 2
    assert summary["failed"] == 1
    assert finalized == [("001.jpg", ["zh-001"]), ("003.jpg", ["zh-003"])]
    assert failed_record["status"] == "failed"
    assert failed_record["needsReview"] is True
    assert "error" in failed_record["reviewReasons"]
    assert "002.jpg" in failed_tsv
    assert "FAIL-PREP 002.jpg" in stream.getvalue()


def test_run_batch_translation_falls_back_to_lightweight_single_round_after_retry_single_failure(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    finalized = []
    captured_fallback_contexts = []

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["001"],
            "ocrResults": [{"text": "001", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="", context_snapshot=None):
        raise TimeoutError("multi-round timeout")

    def fake_translate_texts(texts, model, base_url, api_key=None, context_snapshot=None):
        captured_fallback_contexts.append(context_snapshot)
        return ["fallback-001"]

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        finalized.append((Path(source_path).name, translated_texts, translation_payload))
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    assert summary["succeeded"] == 1
    assert summary["failed"] == 0
    assert captured_fallback_contexts[0]["promptPreset"] == "default"
    assert captured_fallback_contexts[0]["sourceLanguage"] == "japanese"
    assert captured_fallback_contexts[0]["readingOrder"] == "rtl"
    assert finalized == [
        (
            "001.jpg",
            ["fallback-001"],
            {
                "translatedTexts": ["fallback-001"],
                "rounds": [
                    {
                        "name": "final",
                        "translatedTexts": ["fallback-001"],
                        "usage": {
                            "inputTokens": 0,
                            "outputTokens": 0,
                            "totalTokens": 0,
                            "estimated": False,
                        },
                    }
                ],
                "tokenUsage": {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "totalTokens": 0,
                    "estimated": False,
                },
                "ocrRetry": {
                    "shouldRetry": False,
                    "reasons": [],
                    "attempted": False,
                    "applied": False,
                },
            },
        )
    ]
    assert "TRANSLATE retry-single 001.jpg" in stream.getvalue()
    assert "TRANSLATE fallback-light 001.jpg" in stream.getvalue()


def test_run_batch_translation_backfills_debug_records_for_existing_outputs_from_hidden_cache(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    source_path = input_dir / "001.jpg"
    _save_image(source_path)
    _save_image(output_dir / "001.translated.png", color="green")

    cached_preprocessed = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["さあ"],
        "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
        preprocess_signature=_current_preprocess_signature(),
    ).save_translated(source_path, cached_preprocessed, ["来吧"])

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "translate_manga.cli.service.preprocess_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "translate_manga.cli.service.run_page_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_page_pipeline should not run")),
    )

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    debug_root = output_dir / "_debug"
    page_record = json.loads((debug_root / "pages" / "001.json").read_text(encoding="utf-8"))

    assert summary["skipped"] == 1
    assert page_record["status"] == "skipped-existing"
    assert page_record["originalTexts"] == ["さあ"]
    assert page_record["translatedTexts"] == ["来吧"]
    assert (debug_root / "texts" / "001.translation.txt").read_text(encoding="utf-8") == "来吧"


def test_run_batch_translation_does_not_flag_blank_existing_output_for_review(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    cache_root = tmp_path / "hidden-cache"
    source_path = input_dir / "i-0022.jpg"
    _save_image(source_path)
    _save_image(output_dir / "i-0022.translated.png", color="white")

    cached_preprocessed = {
        "bubbleCoords": [],
        "bubblePolygons": [],
        "autoDirections": [],
        "textlinesPerBubble": [],
        "bubbleColors": [],
        "originalTexts": [],
        "ocrResults": [],
        "rawMask": None,
    }
    BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=_current_translation_signature(),
        preprocess_signature=_current_preprocess_signature(),
    ).save_preprocessed(source_path, cached_preprocessed)

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "translate_manga.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "blank",
            "should_translate": False,
            "skip_reason": "blank",
            "metrics": {
                "bubble_count": 0,
                "text_count": 0,
                "total_chars": 0,
            },
        },
    )

    run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        cache_root=cache_root,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        reporter=BatchProgressReporter(stream=StringIO()),
    )

    page_record = json.loads((output_dir / "_debug" / "pages" / "i-0022.json").read_text(encoding="utf-8"))

    assert page_record["needsReview"] is False
    assert page_record["reviewReasons"] == []


def test_run_batch_translation_applies_explicit_layout_mode_override(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    captured = {}

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None):
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["001"],
            "ocrResults": [{"text": "001", "engine": "manga_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        return {
            "translatedTexts": ["译文"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        captured["layout_mode"] = app.config.get("CLI_LAYOUT_MODE_OVERRIDE")
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        layout_mode="horizontal",
    )

    assert summary["succeeded"] == 1
    assert captured["layout_mode"] == "horizontal"


def test_run_batch_translation_applies_style3_profile(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    workspace_root = tmp_path / "workspace"
    _save_image(input_dir / "001.jpg")
    captured = {}

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_preprocess_page(source_path, saber_session=None, ocr_options=None):
        captured["ocr_options"] = ocr_options
        return {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["horizontal"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
            "originalTexts": ["HELLO"],
            "ocrResults": [{"text": "HELLO", "engine": "paddle_ocr"}],
            "rawMask": None,
        }

    def fake_translate_texts_multi_round(texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["context_snapshot"] = context_snapshot
        return {
            "translatedTexts": ["你好"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        }

    def fake_run_page_pipeline(
        app,
        page_id,
        source_path,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        api_key="",
        preprocessed_payload=None,
        translated_texts=None,
        context_snapshot=None,
        saber_session=None,
        translation_payload=None,
    ):
        captured["layout_mode"] = app.config.get("CLI_LAYOUT_MODE_OVERRIDE")
        captured["runtime_ocr_options"] = getattr(app, "ocr_options", None)
        captured["font_family"] = getattr(app, "font_family", None)
        translated_path = Path(app.config["CACHE_ROOT"]) / "pages" / page_id / f"{page_id}.translated.png"
        _save_image(translated_path, color="blue")
        return {
            "pageId": page_id,
            "translatedImagePath": str(translated_path),
            "bubbleStates": [],
            "translatedTexts": translated_texts or [],
            "translation": translation_payload,
            "timings": {"total": 0.5},
        }

    monkeypatch.setattr("translate_manga.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("translate_manga.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("translate_manga.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.cli.service.run_page_pipeline", fake_run_page_pipeline)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        style_id="style3",
    )

    assert summary["succeeded"] == 1
    assert captured["layout_mode"] == "horizontal"
    assert captured["ocr_options"]["source_language"] == "english"
    assert captured["ocr_options"]["engine"] == "paddle_ocr"
    assert captured["runtime_ocr_options"]["source_language"] == "english"
    assert captured["font_family"] == "fonts/汉仪正圆-65W.TTF"
    assert captured["context_snapshot"]["sourceLanguage"] == "english"
    assert captured["context_snapshot"]["promptPreset"] == "english"
