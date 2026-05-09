from translate_manga.core.styles import resolve_style_profile


def test_style3_uses_english_paddle_ocr_horizontal_round_ltr():
    profile = resolve_style_profile("style3")

    assert profile["style_id"] == "style3"
    assert profile["layout_mode"] == "horizontal"
    assert profile["font_family"] == "fonts/汉仪正圆-65W.TTF"
    assert profile["source_language"] == "english"
    assert profile["prompt_profile"] == "english"
    assert profile["reading_order"] == "ltr"
    assert profile["ocr"]["engine"] == "paddle_ocr"
    assert profile["ocr"]["enable_hybrid"] is False


def test_legacy_layout_mode_maps_to_existing_styles():
    assert resolve_style_profile(layout_mode="horizontal")["style_id"] == "style1"
    assert resolve_style_profile(layout_mode="vertical")["style_id"] == "style2"


def test_legacy_auto_layout_mode_stays_auto():
    profile = resolve_style_profile(layout_mode="auto")

    assert profile["style_id"] == "auto"
    assert profile["layout_mode"] == "auto"
    assert profile["source_language"] == "japanese"
    assert profile["prompt_profile"] == "default"
