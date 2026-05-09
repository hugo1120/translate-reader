from pathlib import Path

from translate_manga.core.context.manga_context import find_existing_manga_context, load_or_generate_manga_context


def test_find_existing_manga_context_prefers_non_empty_file(tmp_path):
    input_dir = tmp_path / "book"
    input_dir.mkdir(parents=True)
    (input_dir / "manga_context.md").write_text("黑色幽默, 成年人口吻。", encoding="utf-8")

    result = find_existing_manga_context(input_dir)

    assert result["generated"] is False
    assert result["path"] == input_dir / "manga_context.md"
    assert result["content"] == "黑色幽默, 成年人口吻。"


def test_load_or_generate_manga_context_writes_generated_file(tmp_path, monkeypatch):
    input_dir = tmp_path / "[藤子不二雄A] 笑ゥせぇるすまん 2" / "01"
    input_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "translate_manga.core.context.manga_context.generate_manga_context",
        lambda input_dir: {
            "content": "## 作品定位\n黑色幽默短篇。\n\n## 翻译建议\n少感叹号, 口吻成熟。",
        },
    )

    result = load_or_generate_manga_context(input_dir, auto_generate=True)

    assert result["generated"] is True
    assert result["path"] == input_dir.parent / "_translation_profile" / "series_profile.md"
    assert result["path"].read_text(encoding="utf-8").startswith("## 作品定位")
    assert (input_dir.parent / "_translation_profile" / "glossary.tsv").exists()
    assert (input_dir.parent / "_translation_profile" / "characters.tsv").exists()


def test_load_or_generate_manga_context_reuses_series_profile_for_later_volume(tmp_path, monkeypatch):
    series_root = tmp_path / "翻译测试日漫" / "德川家康"
    input_dir = series_root / "02"
    input_dir.mkdir(parents=True)
    profile_path = series_root / "_translation_profile" / "series_profile.md"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("## 作品定位\n历史正剧。\n\n## 翻译建议\n称呼沉稳。", encoding="utf-8")

    def fail_generate(input_dir):
        raise AssertionError("existing series profile should be reused")

    monkeypatch.setattr("translate_manga.core.context.manga_context.generate_manga_context", fail_generate)

    result = load_or_generate_manga_context(input_dir, auto_generate=True)

    assert result["generated"] is False
    assert result["path"] == profile_path
    assert "历史正剧" in result["content"]


def test_load_or_generate_manga_context_returns_none_when_disabled_and_missing(tmp_path):
    input_dir = tmp_path / "book"
    input_dir.mkdir(parents=True)

    result = load_or_generate_manga_context(input_dir, auto_generate=False)

    assert result is None
