from pathlib import Path

from translate_manga.core.context.book_profile import build_book_profile, split_pasted_paths


def test_build_book_profile_uses_parent_as_series_when_leaf_is_volume_number(tmp_path):
    input_dir = tmp_path / "翻译测试日漫" / "德川家康" / "01"
    input_dir.mkdir(parents=True)

    profile = build_book_profile(input_dir)

    assert profile.series_name == "德川家康"
    assert profile.volume_name == "01"
    assert profile.series_root == input_dir.parent
    assert profile.profile_dir == input_dir.parent / "_translation_profile"
    assert profile.series_profile_path == input_dir.parent / "_translation_profile" / "series_profile.md"


def test_build_book_profile_uses_leaf_as_series_when_leaf_is_not_volume(tmp_path):
    input_dir = tmp_path / "翻译测试日漫" / "卡姆依传"
    input_dir.mkdir(parents=True)

    profile = build_book_profile(input_dir)

    assert profile.series_name == "卡姆依传"
    assert profile.volume_name == ""
    assert profile.series_root == input_dir


def test_split_pasted_paths_splits_concatenated_windows_drive_paths():
    raw = (
        r"D:\github\translate-reader\翻译测试日漫\武田信玄\10"
        r"D:\github\translate-reader\翻译测试日漫\德川家康\01"
        "\n"
        r'"D:\github\translate-reader\翻译测试日漫\丰臣秀吉\02"'
    )

    assert split_pasted_paths(raw) == [
        r"D:\github\translate-reader\翻译测试日漫\武田信玄\10",
        r"D:\github\translate-reader\翻译测试日漫\德川家康\01",
        r"D:\github\translate-reader\翻译测试日漫\丰臣秀吉\02",
    ]
