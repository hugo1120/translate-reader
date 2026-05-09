from copy import deepcopy


_STYLE_ALIASES = {
    "1": "style1",
    "style1": "style1",
    "style_1": "style1",
    "horizontal": "style1",
    "2": "style2",
    "style2": "style2",
    "style_2": "style2",
    "vertical": "style2",
    "auto": "auto",
    "3": "style3",
    "style3": "style3",
    "style_3": "style3",
}


STYLE_PROFILES = {
    "style1": {
        "style_id": "style1",
        "label": "Style 1 horizontal JP",
        "layout_mode": "horizontal",
        "font_family": None,
        "source_language": "japanese",
        "prompt_profile": "default",
        "reading_order": "ltr",
        "ocr": {},
    },
    "style2": {
        "style_id": "style2",
        "label": "Style 2 vertical JP",
        "layout_mode": "vertical",
        "font_family": None,
        "source_language": "japanese",
        "prompt_profile": "default",
        "reading_order": "rtl",
        "ocr": {},
    },
    "style3": {
        "style_id": "style3",
        "label": "Style 3 horizontal EN",
        "layout_mode": "horizontal",
        "font_family": "fonts/汉仪正圆-65W.TTF",
        "source_language": "english",
        "prompt_profile": "english",
        "reading_order": "ltr",
        "ocr": {
            "engine": "paddle_ocr",
            "enable_hybrid": False,
            "secondary_engine": None,
        },
    },
    "auto": {
        "style_id": "auto",
        "label": "Auto layout JP",
        "layout_mode": "auto",
        "font_family": None,
        "source_language": "japanese",
        "prompt_profile": "default",
        "reading_order": "rtl",
        "ocr": {},
    },
}


def normalize_style_id(style_id=None, *, layout_mode=None):
    candidate = str(style_id or "").strip().lower()
    if candidate:
        return _STYLE_ALIASES.get(candidate, "style2")
    layout_candidate = str(layout_mode or "").strip().lower()
    return _STYLE_ALIASES.get(layout_candidate, "style2")


def resolve_style_profile(style_id=None, *, layout_mode=None):
    normalized = normalize_style_id(style_id, layout_mode=layout_mode)
    return deepcopy(STYLE_PROFILES[normalized])
