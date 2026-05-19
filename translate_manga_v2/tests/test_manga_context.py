from translate_manga.core.context.manga_context import find_existing_manga_context


def test_find_existing_manga_context_reads_utf16_file(tmp_path):
    input_dir = tmp_path / "book"
    input_dir.mkdir()
    (input_dir / "manga_context.md").write_text(
        "## 作品定位\n卡姆依传。\n\n## 术语\nマスどり -> 量斗",
        encoding="utf-16",
    )

    result = find_existing_manga_context(
        input_dir,
        pipeline_config={"manga_context_file_names": ["manga_context.md"]},
    )

    assert result is not None
    assert result["generated"] is False
    assert "卡姆依传" in result["content"]
    assert "マスどり -> 量斗" in result["content"]
