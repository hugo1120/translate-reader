from io import StringIO
import json
from pathlib import Path

from PIL import Image

from tests.test_constants import TEST_BASE_URL
from src.cli.cache import BatchStageCache
from src.cli.service import BatchProgressReporter, _resolve_cli_settings, build_output_path, run_batch_translation, scan_input_images
from src.core.translate.openai_compatible import TRANSLATION_PROMPT_SIGNATURE


def _save_image(path, color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 24), color).save(path)


def _current_preprocess_signature():
    return _resolve_cli_settings()["preprocess_signature"]


def test_build_output_path_uses_translated_png(tmp_path):
    output_path = build_output_path(tmp_path / "001.jpg", tmp_path / "out")

    assert output_path == tmp_path / "out" / "001.translated.png"


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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr(
        "src.cli.service.load_settings",
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stage_cache = BatchStageCache(
        cache_root=cache_root,
        input_dir=input_dir,
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
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

    from src.cli import debug_artifacts as debug_artifacts_module

    class CorruptingWriter(debug_artifacts_module.BatchDebugArtifactWriter):
        def record_page(self, **kwargs):
            record = super().record_page(**kwargs)
            if record["status"] == "translated":
                page_json_path = self.pages_root / "001.json"
                corrupted = dict(record)
                corrupted["status"] = "skipped-existing"
                page_json_path.write_text(json.dumps(corrupted, ensure_ascii=False, indent=2), encoding="utf-8")
            return record

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr("src.cli.service.BatchDebugArtifactWriter", CorruptingWriter)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", lambda texts, model, base_url, context_snapshot=None: [f"zh-{text}" for text in texts])
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)
    monkeypatch.setattr("src.cli.service.load_settings", lambda project_root=None: settings_by_engine[current_engine["value"]])

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "src.cli.service.preprocess_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")),
    )
    monkeypatch.setattr(
        "src.cli.service.run_page_pipeline",
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
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(
        "src.cli.service.classify_preprocessed_page",
        lambda **kwargs: {
            "page_type": "frontmatter",
            "should_translate": False,
            "skip_reason": "frontmatter",
        },
    )
    monkeypatch.setattr(
        "src.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "src.cli.service.run_page_pipeline",
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr(
        "src.cli.service.classify_preprocessed_page",
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
        "src.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "src.cli.service.run_page_pipeline",
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    assert translate_calls == [["001", "002"], ["001"], ["002"]]
    assert finalized == [("001.jpg", ["zh-001"]), ("002.jpg", ["zh-002"])]
    assert summary["succeeded"] == 2
    assert "TRANSLATE retry-single 001.jpg" in stream.getvalue()
    assert "TRANSLATE retry-single 002.jpg" in stream.getvalue()


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
        assert context_snapshot is None
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.cli.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

    stream = StringIO()
    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        reporter=BatchProgressReporter(stream=stream),
    )

    assert summary["succeeded"] == 1
    assert summary["failed"] == 0
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
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
        preprocess_signature=_current_preprocess_signature(),
    ).save_translated(source_path, cached_preprocessed, ["来吧"])

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "src.cli.service.preprocess_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")),
    )
    monkeypatch.setattr(
        "src.cli.service.translate_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")),
    )
    monkeypatch.setattr(
        "src.cli.service.run_page_pipeline",
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
        translation_signature=TRANSLATION_PROMPT_SIGNATURE,
        preprocess_signature=_current_preprocess_signature(),
    ).save_preprocessed(source_path, cached_preprocessed)

    class DummySession:
        def __enter__(self):
            return "session-token"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr(
        "src.cli.service.classify_preprocessed_page",
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

    monkeypatch.setattr("src.cli.service.SaberWorkerSession", DummySession)
    monkeypatch.setattr("src.cli.service.preprocess_page", fake_preprocess_page)
    monkeypatch.setattr("src.cli.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.cli.service.run_page_pipeline", fake_run_page_pipeline)

    summary = run_batch_translation(
        input_dir=input_dir,
        output_dir=output_dir,
        workspace_root=workspace_root,
        layout_mode="horizontal",
    )

    assert summary["succeeded"] == 1
    assert captured["layout_mode"] == "horizontal"
