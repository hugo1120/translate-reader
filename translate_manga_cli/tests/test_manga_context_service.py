from pathlib import Path

from src.core.context.manga_context import find_existing_manga_context, load_or_generate_manga_context


def test_find_existing_manga_context_prefers_non_empty_file(tmp_path):
    input_dir = tmp_path / "book"
    input_dir.mkdir(parents=True)
    (input_dir / "manga_context.md").write_text("黑色幽默, 成年人口吻。", encoding="utf-8")

    result = find_existing_manga_context(input_dir)

    assert result["generated"] is False
    assert result["path"] == input_dir / "manga_context.md"
    assert result["content"] == "黑色幽默, 成年人口吻。"


def test_load_or_generate_manga_context_writes_generated_file(tmp_path, monkeypatch):
    input_dir = tmp_path / "[藤子不二雄A] 笑ゥせぇるすまん 2"
    input_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "src.core.context.manga_context.generate_manga_context",
        lambda input_dir: {
            "content": "## 作品定位\n黑色幽默短篇。\n\n## 翻译建议\n少感叹号, 口吻成熟。",
        },
    )

    result = load_or_generate_manga_context(input_dir, auto_generate=True)

    assert result["generated"] is True
    assert result["path"] == input_dir / "manga_context.md"
    assert result["path"].read_text(encoding="utf-8").startswith("## 作品定位")


def test_load_or_generate_manga_context_returns_none_when_disabled_and_missing(tmp_path):
    input_dir = tmp_path / "book"
    input_dir.mkdir(parents=True)

    result = load_or_generate_manga_context(input_dir, auto_generate=False)

    assert result is None
