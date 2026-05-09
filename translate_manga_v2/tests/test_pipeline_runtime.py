from translate_manga.core.pipeline.runtime import PipelineRuntime


def test_pipeline_runtime_tracks_pages_results_and_cache_paths(tmp_path):
    runtime = PipelineRuntime(tmp_path / "workspace", layout_mode="horizontal")
    runtime.seed_pages(
        [
            {
                "id": "page-0001",
                "fileName": "001.jpg",
                "sourcePath": "001.jpg",
                "translatedPath": None,
                "status": "idle",
            }
        ]
    )

    runtime.save_result("page-0001", {"translatedTexts": ["你好"]})
    runtime.update_translated_path("page-0001", "001.translated.png")
    page_paths = runtime.page_cache_paths("page-0001")

    assert runtime.layout_mode == "horizontal"
    assert runtime.list_pages()[0]["translatedPath"] == "001.translated.png"
    assert runtime.list_pages()[0]["status"] == "translated"
    assert runtime.load_result("page-0001") == {"translatedTexts": ["你好"]}
    assert page_paths["cleanImagePath"] == str(tmp_path / "workspace" / "cache" / "pages" / "page-0001" / "page-0001.clean.png")
    assert page_paths["translatedImagePath"] == str(
        tmp_path / "workspace" / "cache" / "pages" / "page-0001" / "page-0001.translated.png"
    )
