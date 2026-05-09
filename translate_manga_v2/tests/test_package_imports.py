def test_translate_manga_public_imports_work():
    from translate_manga.cli.service import run_batch_translation
    from translate_manga.core.pipeline.runtime import PipelineRuntime

    assert callable(run_batch_translation)
    assert PipelineRuntime.__name__ == "PipelineRuntime"
