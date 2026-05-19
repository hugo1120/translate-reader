import os
import re
import tempfile
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from translate_manga.config.paths import find_project_root
from translate_manga.config.settings import load_settings, resolve_path_value, resolve_translation_config
from translate_manga.core.color.service import enrich_bubble_colors_with_background_metrics, extract_bubble_colors
from translate_manga.core.context.service import build_context_snapshot
from translate_manga.core.detection.service import detect_page
from translate_manga.core.inpaint.service import inpaint_page
from translate_manga.core.ocr.service import ocr_page, resolve_saber_ocr_options
from translate_manga.core.pipeline.filtering import filter_detection_payload, filter_ocr_payload, load_image_size
from translate_manga.core.pipeline.runtime import PipelineRuntime
from translate_manga.core.render.service import render_page
from translate_manga.core.translation_payload import (
    build_legacy_translation_payload as _build_legacy_translation_payload,
    default_ocr_retry_state as _default_ocr_retry_state,
    empty_usage as _empty_usage,
    normalize_ocr_retry_state as _normalize_ocr_retry_state,
    normalize_translation_payload as _normalize_translation_payload,
)
from translate_manga.core.translate.openai_compatible import OpenAICompatibleTranslator
from translate_manga.integrations.saber_loader import run_saber_task


DEFAULT_CLI_READABILITY_STYLE = {
    "fontFamily": "fonts/思源黑体SourceHanSansK-Bold.TTF",
    "strokeEnabled": True,
    "strokeColor": "#FFFFFF",
    "strokeWidth": 1,
    "lineSpacing": 0.84,
    "textAlign": "center",
}

DEFAULT_CLI_AUTO_FONT_SETTINGS = {
    "min_size": 16,
    "max_size": 72,
    "padding_ratio": 0.96,
}

DEFAULT_CLI_WATERMARK_STYLE = {
    "enabled": True,
    "text": "HUGO2233汉化",
    "fillColor": "#A8A8A8",
    "fillAlpha": 176,
    "strokeColor": "#FFFFFF",
    "strokeAlpha": 224,
    "strokeWidth": 1,
    "fontSizeRatio": 0.014,
    "minSize": 10,
    "maxSize": 18,
    "marginRatio": 0.015,
}

DEFAULT_CLI_VERTICAL_LAYOUT_STYLE = {
    "fontFamily": "fonts/汉仪正圆-65W.TTF",
    "lineSpacing": 1.04,
}

DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS = {
    "min_size": 14,
    "max_size": 60,
    "padding_ratio": 0.86,
}


def _normalize_layout_direction(value, default="vertical"):
    raw_value = str(value or "").strip().lower()
    if raw_value == "auto":
        return "auto"
    if raw_value in {"v", "vertical"}:
        return "vertical"
    if raw_value in {"h", "horizontal"}:
        return "horizontal"
    return default


_CJK_TOKEN_CLASS = r"\u3400-\u9fff\u3040-\u30ff々〆ヵヶー、。！？…・「」『』（）〔〕［］【】〈〉《》"
_CJK_SPACE_RE = re.compile(fr"(?<=[{_CJK_TOKEN_CLASS}])\s+(?=[{_CJK_TOKEN_CLASS}])")
_INLINE_SPACE_RE = re.compile(r"[ \t]{2,}")
_MICRO_KANA_NOISE_RE = re.compile(r"^[\u3040-\u30ffー]{1,2}$")


def _normalize_source_text_for_translation(text):
    lines = [line.strip() for line in str(text or "").replace("\r", "\n").split("\n")]
    value = "\n".join(line for line in lines if line)
    if not value:
        return ""
    value = _INLINE_SPACE_RE.sub(" ", value)
    return _CJK_SPACE_RE.sub("", value)


def _bubble_line_directions(textlines):
    directions = []
    for textline in textlines or []:
        direction = _normalize_layout_direction((textline or {}).get("direction"), default="")
        if direction and direction not in directions:
            directions.append(direction)
    return directions


def _bubble_line_direction_counts(textlines):
    line_directions = [
        _normalize_layout_direction((textline or {}).get("direction"), default="")
        for textline in textlines or []
    ]
    line_directions = [direction for direction in line_directions if direction]
    return {
        "horizontal": sum(1 for direction in line_directions if direction == "horizontal"),
        "vertical": sum(1 for direction in line_directions if direction == "vertical"),
        "total": len(line_directions),
    }


def _textline_bounds(textline):
    polygon = (textline or {}).get("polygon") or []
    xs = []
    ys = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            xs.append(int(point[0]))
            ys.append(int(point[1]))
        except (TypeError, ValueError):
            continue
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _vertical_textline_bounds(textlines):
    bounds = []
    for textline in textlines or []:
        direction = _normalize_layout_direction((textline or {}).get("direction"), default="")
        if direction != "vertical":
            continue
        line_bounds = _textline_bounds(textline)
        if line_bounds is not None:
            bounds.append(line_bounds)
    return bounds


def _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=None):
    text = str(original_text or "").strip()
    directions = _bubble_line_directions(textlines)
    metrics = {
        "width": 0,
        "height": 0,
        "areaRatio": 0.0,
        "topRatio": 1.0,
        "leftRatio": 1.0,
        "rightRatio": 1.0,
        "charCount": len(text),
        "lineCount": len(textlines or []),
        "directions": directions,
        "confidence": 1.0,
        "fallbackUsed": False,
    }
    if isinstance(coords, (list, tuple)) and len(coords) >= 4:
        width = max(0, int(coords[2]) - int(coords[0]))
        height = max(0, int(coords[3]) - int(coords[1]))
        metrics["width"] = width
        metrics["height"] = height
        if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
            page_width = max(1, int(image_size[0]))
            page_height = max(1, int(image_size[1]))
            metrics["areaRatio"] = float(width * height) / float(page_width * page_height)
            metrics["topRatio"] = max(0.0, float(coords[1]) / float(page_height))
            metrics["leftRatio"] = max(0.0, float(coords[0]) / float(page_width))
            metrics["rightRatio"] = max(0.0, float(page_width - int(coords[2])) / float(page_width))
    if isinstance(ocr_result, dict):
        try:
            metrics["confidence"] = float(ocr_result.get("confidence", 1.0) or 1.0)
        except (TypeError, ValueError):
            metrics["confidence"] = 1.0
        metrics["fallbackUsed"] = bool(ocr_result.get("fallbackUsed"))
    return metrics


def _bubble_role_from_context(coords, textlines, original_text, ocr_result, image_size=None):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return "dialogue"
    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    width = metrics["width"]
    height = metrics["height"]
    directions = metrics["directions"]
    direction_counts = _bubble_line_direction_counts(textlines)
    horizontal_count = direction_counts["horizontal"]
    vertical_count = direction_counts["vertical"]
    text = str(original_text or "").strip()
    confidence = metrics["confidence"]

    if (
        _MICRO_KANA_NOISE_RE.match(text)
        and len(textlines or []) <= 2
        and width <= 80
        and height <= 32
        and confidence < 0.38
    ):
        return "ocr_noise"

    if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        page_width = max(1, int(image_size[0]))
        page_height = max(1, int(image_size[1]))
        top_ratio = metrics["topRatio"]
        if (
            top_ratio <= 0.12
            and height <= int(page_height * 0.09)
            and width >= int(height * 1.6)
            and len(textlines or []) >= 2
            and directions == ["horizontal"]
            and confidence < 0.8
        ):
            return "header_noise"
        if (
            top_ratio <= 0.08
            and height <= int(page_height * 0.035)
            and len(text) <= 12
            and (metrics["leftRatio"] <= 0.12 or metrics["rightRatio"] <= 0.12)
            and (top_ratio <= 0.04 or confidence < 0.8)
        ):
            return "header_noise"
        if (
            top_ratio <= 0.18
            and "horizontal" in directions
            and "vertical" in directions
            and horizontal_count >= vertical_count
            and len(text) >= 4
            and width >= int(page_width * 0.08)
            and height <= int(page_height * 0.25)
        ):
            return "title_caption"

    if len(text) >= 120:
        return "long_narration"
    if metrics["areaRatio"] >= 0.12 and len(text) >= 60:
        return "long_narration"
    if metrics["lineCount"] >= 14 and len(text) >= 50 and height >= 140:
        return "long_narration"
    return "dialogue"


def _long_narration_auto_font_settings(coords, textlines, original_text, ocr_result, image_size=None):
    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    if metrics["charCount"] >= 400 or metrics["areaRatio"] >= 0.28 or metrics["lineCount"] >= 24:
        return {
            "min_size": 8,
            "max_size": 20,
            "padding_ratio": 0.84,
        }
    if metrics["charCount"] >= 220 or metrics["areaRatio"] >= 0.16 or metrics["lineCount"] >= 18:
        return {
            "min_size": 8,
            "max_size": 18,
            "padding_ratio": 0.74,
        }
    return {
        "min_size": 10,
        "max_size": 20,
        "padding_ratio": 0.76,
    }


def _is_horizontal_chart_list_long_narration(coords, textlines, original_text, ocr_result, image_size=None):
    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    direction_counts = _bubble_line_direction_counts(textlines)
    total = direction_counts["total"]
    if total < 10 or direction_counts["horizontal"] < max(8, int(total * 0.75)):
        return False
    if metrics["height"] < 160 or metrics["width"] < 180:
        return False
    return metrics["charCount"] <= max(180, metrics["lineCount"] * 12)


def _horizontal_chart_list_auto_font_settings():
    return {
        "min_size": 8,
        "max_size": 14,
        "padding_ratio": 0.74,
    }


def _bubble_color_metric(bubble_color, key, default):
    if not isinstance(bubble_color, dict):
        return default
    try:
        return float(bubble_color.get(key, default))
    except (TypeError, ValueError):
        return default


def _should_use_horizontal_editorial_long_narration(
    coords,
    textlines,
    original_text,
    ocr_result,
    image_size=None,
    bubble_color=None,
):
    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    direction_counts = _bubble_line_direction_counts(textlines)
    total = direction_counts["total"]
    if total <= 0 or direction_counts["vertical"] < max(1, int(total * 0.7)):
        return False
    if not isinstance(image_size, (list, tuple)) or len(image_size) < 2:
        return False

    page_width = max(1, int(image_size[0]))
    page_height = max(1, int(image_size[1]))
    width_ratio = float(metrics["width"]) / float(page_width)
    height_ratio = float(metrics["height"]) / float(page_height)
    edge_density = _bubble_color_metric(bubble_color, "edgeDensity", 1.0)
    dark_pixel_ratio = _bubble_color_metric(bubble_color, "darkPixelRatio", 1.0)

    quiet_large_block = (
        width_ratio >= 0.55
        and height_ratio >= 0.28
        and (metrics["charCount"] >= 360 or metrics["lineCount"] >= 22 or metrics["areaRatio"] >= 0.20)
        and edge_density <= 0.13
        and dark_pixel_ratio <= 0.04
    )
    low_confidence_exposition = (
        metrics["fallbackUsed"]
        and metrics["confidence"] < 0.55
        and metrics["charCount"] >= 150
        and width_ratio >= 0.38
        and height_ratio >= 0.16
        and dark_pixel_ratio <= 0.05
    )
    return quiet_large_block or low_confidence_exposition


def _should_keep_vertical_long_narration(coords, textlines, original_text, ocr_result, image_size=None, bubble_color=None):
    if _should_use_horizontal_editorial_long_narration(
        coords,
        textlines,
        original_text,
        ocr_result,
        image_size=image_size,
        bubble_color=bubble_color,
    ):
        return False

    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    line_directions = [
        _normalize_layout_direction((textline or {}).get("direction"), default="")
        for textline in textlines or []
    ]
    line_directions = [direction for direction in line_directions if direction]
    vertical_count = sum(1 for direction in line_directions if direction == "vertical")
    return (
        bool(line_directions)
        and metrics["width"] > 0
        and metrics["height"] > 0
        and vertical_count >= max(1, int(len(line_directions) * 0.7))
    )


def _vertical_long_narration_auto_font_settings():
    return {
        "min_size": 8,
        "max_size": 16,
        "padding_ratio": 0.78,
    }


def _vertical_long_narration_render_coords(coords, textlines):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return None
    bounds = _vertical_textline_bounds(textlines)
    if len(bounds) < 12:
        return None

    x1, y1, x2, y2 = [int(value) for value in coords[:4]]
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    if width <= 0 or height <= 0:
        return None

    early_cutoff = y1 + height * 0.35
    late_cutoff = y1 + height * 0.45
    early_bounds = [item for item in bounds if item[1] <= early_cutoff]
    if len(early_bounds) < max(6, int(len(bounds) * 0.35)):
        return None

    early_min_x = min(item[0] for item in early_bounds)
    early_max_x = max(item[2] for item in early_bounds)
    late_right_bounds = [
        item
        for item in bounds
        if item[0] > early_max_x + 2 and item[1] >= late_cutoff
    ]
    if len(late_right_bounds) < max(4, int(len(bounds) * 0.25)):
        return None

    trimmed_width = early_max_x - early_min_x
    if trimmed_width < width * 0.3 or trimmed_width > width * 0.85:
        return None

    line_widths = [max(1, item[2] - item[0]) for item in early_bounds]
    padding = max(8, min(24, int(round(sum(line_widths) / len(line_widths)))))
    return [
        x1,
        y1,
        min(x2, early_max_x + padding),
        y2,
    ]


def _should_compact_vertical_dialogue(coords, textlines, original_text, ocr_result, image_size=None):
    metrics = _build_bubble_metrics(coords, textlines, original_text, ocr_result, image_size=image_size)
    direction_counts = _bubble_line_direction_counts(textlines)
    total = direction_counts["total"]
    if total < 6:
        return False
    if direction_counts["vertical"] < max(4, int(total * 0.6)):
        return False
    return metrics["width"] >= 120 and metrics["height"] >= 100


def _compact_vertical_dialogue_auto_font_settings():
    return {
        "min_size": 7,
        "max_size": 22,
        "padding_ratio": 0.64,
    }


def _compact_vertical_dialogue_position_offset(coords, textlines):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return {"x": 0, "y": 0}
    if _bubble_line_direction_counts(textlines)["horizontal"] <= 0:
        return {"x": 0, "y": 0}
    height = max(0, int(coords[3]) - int(coords[1]))
    return {"x": 0, "y": max(12, min(44, int(round(height * 0.25))))}


def build_bubble_text_profiles(detection, ocr, image_size=None):
    bubble_coords = detection.get("bubbleCoords", []) or []
    textlines_per_bubble = detection.get("textlinesPerBubble", []) or []
    bubble_colors = detection.get("bubbleColors", []) or []
    bubble_layout_hints = detection.get("bubbleLayoutHints", []) or []
    original_texts = ocr.get("originalTexts", []) or []
    ocr_results = ocr.get("ocrResults", []) or []
    profiles = []

    for index, coords in enumerate(bubble_coords):
        original_text = original_texts[index] if index < len(original_texts) else ""
        textlines = textlines_per_bubble[index] if index < len(textlines_per_bubble) else []
        ocr_result = ocr_results[index] if index < len(ocr_results) else {}
        bubble_color = bubble_colors[index] if index < len(bubble_colors) and isinstance(bubble_colors[index], dict) else {}
        layout_hint = bubble_layout_hints[index] if index < len(bubble_layout_hints) and isinstance(bubble_layout_hints[index], dict) else {}
        role = _bubble_role_from_context(
            coords,
            textlines,
            original_text,
            ocr_result,
            image_size=image_size,
        )
        hinted_role = str(layout_hint.get("role") or "").strip()
        if hinted_role:
            role = hinted_role
        profile = {
            "role": role,
            "sourceText": str(original_text or "").strip(),
            "suppressTranslation": False,
            "directionOverride": None,
            "autoFontSettings": None,
            "textAlignOverride": None,
            "positionOffset": None,
            "renderCoords": None,
        }
        if role in {"header_noise", "ocr_noise", "page_number", "header", "noise", "sfx"} or layout_hint.get("suppressTranslation"):
            profile["sourceText"] = ""
            profile["suppressTranslation"] = True
        elif role == "title_caption":
            profile["sourceText"] = _normalize_source_text_for_translation(original_text)
            profile["directionOverride"] = "horizontal"
            profile["autoFontSettings"] = {
                "min_size": 12,
                "max_size": 36,
                "padding_ratio": 0.72,
            }
        elif role == "long_narration":
            profile["sourceText"] = _normalize_source_text_for_translation(original_text)
            if _should_keep_vertical_long_narration(
                coords,
                textlines,
                original_text,
                ocr_result,
                image_size=image_size,
                bubble_color=bubble_color,
            ):
                profile["directionOverride"] = "vertical"
                profile["autoFontSettings"] = _vertical_long_narration_auto_font_settings()
                profile["renderCoords"] = _vertical_long_narration_render_coords(coords, textlines)
            else:
                profile["directionOverride"] = "horizontal"
                profile["textAlignOverride"] = "start"
                if _is_horizontal_chart_list_long_narration(
                    coords,
                    textlines,
                    original_text,
                    ocr_result,
                    image_size=image_size,
                ):
                    profile["autoFontSettings"] = _horizontal_chart_list_auto_font_settings()
                else:
                    profile["autoFontSettings"] = _long_narration_auto_font_settings(
                        coords,
                        textlines,
                        original_text,
                        ocr_result,
                        image_size=image_size,
                    )
        elif role == "dialogue" and _should_compact_vertical_dialogue(
            coords,
            textlines,
            original_text,
            ocr_result,
            image_size=image_size,
        ):
            profile["autoFontSettings"] = _compact_vertical_dialogue_auto_font_settings()
            profile["positionOffset"] = _compact_vertical_dialogue_position_offset(coords, textlines)
        hinted_direction = _normalize_layout_direction(layout_hint.get("directionOverride"), default="")
        if hinted_direction in {"horizontal", "vertical"} and not profile["suppressTranslation"]:
            profile["directionOverride"] = hinted_direction
        hinted_align = str(layout_hint.get("textAlignOverride") or "").strip()
        if hinted_align and not profile["suppressTranslation"]:
            profile["textAlignOverride"] = hinted_align
        profiles.append(profile)

    return profiles


def _resolve_render_style(layout_mode_override=None, font_family_override=None):
    settings = load_settings()
    render = settings.get("render") or {}
    layout_mode = _normalize_layout_direction(layout_mode_override or render.get("layout_mode"), default="auto")
    vertical_layout = render.get("vertical_layout") or {}
    font_family = str(render.get("font_family") or DEFAULT_CLI_READABILITY_STYLE["fontFamily"])
    line_spacing = float(render.get("line_spacing", DEFAULT_CLI_READABILITY_STYLE["lineSpacing"]) or DEFAULT_CLI_READABILITY_STYLE["lineSpacing"])
    if layout_mode == "vertical":
        font_family = str(vertical_layout.get("font_family") or DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["fontFamily"])
        line_spacing = float(vertical_layout.get("line_spacing", DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["lineSpacing"]) or DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["lineSpacing"])
    if font_family_override and layout_mode != "vertical":
        font_family = str(font_family_override)
    return {
        "fontFamily": font_family,
        "strokeEnabled": bool(render.get("stroke_enabled", DEFAULT_CLI_READABILITY_STYLE["strokeEnabled"])),
        "strokeColor": str(render.get("stroke_color") or DEFAULT_CLI_READABILITY_STYLE["strokeColor"]),
        "strokeWidth": int(render.get("stroke_width", DEFAULT_CLI_READABILITY_STYLE["strokeWidth"]) or DEFAULT_CLI_READABILITY_STYLE["strokeWidth"]),
        "lineSpacing": line_spacing,
        "textAlign": str(render.get("text_align") or DEFAULT_CLI_READABILITY_STYLE["textAlign"]),
        "layoutMode": layout_mode,
    }


def _resolve_vertical_render_style():
    settings = load_settings()
    render = settings.get("render") or {}
    vertical_layout = render.get("vertical_layout") or {}
    return {
        "fontFamily": str(vertical_layout.get("font_family") or DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["fontFamily"]),
        "lineSpacing": float(
            vertical_layout.get("line_spacing", DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["lineSpacing"])
            or DEFAULT_CLI_VERTICAL_LAYOUT_STYLE["lineSpacing"]
        ),
    }


def _resolve_auto_font_settings(layout_mode_override=None):
    settings = load_settings()
    render = settings.get("render") or {}
    layout_mode = _normalize_layout_direction(layout_mode_override or render.get("layout_mode"), default="auto")
    auto_font = render.get("auto_font") or {}
    if layout_mode == "vertical":
        auto_font = (render.get("vertical_layout") or {}).get("auto_font") or {}
        return {
            "min_size": int(auto_font.get("min_size", DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["min_size"]) or DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["min_size"]),
            "max_size": int(auto_font.get("max_size", DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["max_size"]) or DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["max_size"]),
            "padding_ratio": float(auto_font.get("padding_ratio", DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["padding_ratio"]) or DEFAULT_CLI_VERTICAL_AUTO_FONT_SETTINGS["padding_ratio"]),
        }
    return {
        "min_size": int(auto_font.get("min_size", DEFAULT_CLI_AUTO_FONT_SETTINGS["min_size"]) or DEFAULT_CLI_AUTO_FONT_SETTINGS["min_size"]),
        "max_size": int(auto_font.get("max_size", DEFAULT_CLI_AUTO_FONT_SETTINGS["max_size"]) or DEFAULT_CLI_AUTO_FONT_SETTINGS["max_size"]),
        "padding_ratio": float(auto_font.get("padding_ratio", DEFAULT_CLI_AUTO_FONT_SETTINGS["padding_ratio"]) or DEFAULT_CLI_AUTO_FONT_SETTINGS["padding_ratio"]),
    }


def _resolve_watermark_style():
    settings = load_settings()
    render = settings.get("render") or {}
    watermark = render.get("watermark") or {}
    return {
        "enabled": bool(watermark.get("enabled", DEFAULT_CLI_WATERMARK_STYLE["enabled"])),
        "text": str(watermark.get("text") or DEFAULT_CLI_WATERMARK_STYLE["text"]),
        "fillColor": str(watermark.get("fill_color") or DEFAULT_CLI_WATERMARK_STYLE["fillColor"]),
        "fillAlpha": int(watermark.get("fill_alpha", DEFAULT_CLI_WATERMARK_STYLE["fillAlpha"]) or DEFAULT_CLI_WATERMARK_STYLE["fillAlpha"]),
        "strokeColor": str(watermark.get("stroke_color") or DEFAULT_CLI_WATERMARK_STYLE["strokeColor"]),
        "strokeAlpha": int(watermark.get("stroke_alpha", DEFAULT_CLI_WATERMARK_STYLE["strokeAlpha"]) or DEFAULT_CLI_WATERMARK_STYLE["strokeAlpha"]),
        "strokeWidth": int(watermark.get("stroke_width", DEFAULT_CLI_WATERMARK_STYLE["strokeWidth"]) or DEFAULT_CLI_WATERMARK_STYLE["strokeWidth"]),
        "fontSizeRatio": float(watermark.get("font_size_ratio", DEFAULT_CLI_WATERMARK_STYLE["fontSizeRatio"]) or DEFAULT_CLI_WATERMARK_STYLE["fontSizeRatio"]),
        "minSize": int(watermark.get("min_size", DEFAULT_CLI_WATERMARK_STYLE["minSize"]) or DEFAULT_CLI_WATERMARK_STYLE["minSize"]),
        "maxSize": int(watermark.get("max_size", DEFAULT_CLI_WATERMARK_STYLE["maxSize"]) or DEFAULT_CLI_WATERMARK_STYLE["maxSize"]),
        "marginRatio": float(watermark.get("margin_ratio", DEFAULT_CLI_WATERMARK_STYLE["marginRatio"]) or DEFAULT_CLI_WATERMARK_STYLE["marginRatio"]),
        "fontFamily": str(watermark.get("font_family") or render.get("font_family") or DEFAULT_CLI_READABILITY_STYLE["fontFamily"]),
    }


def _parse_hex_color(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        return None
    try:
        return [int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)]
    except ValueError:
        return None


def _relative_luminance(rgb):
    if not rgb or len(rgb) != 3:
        return None
    red, green, blue = [max(0, min(255, int(channel))) for channel in rgb]
    return (0.299 * red) + (0.587 * green) + (0.114 * blue)


def _rgb_distance(left_rgb, right_rgb):
    if not left_rgb or not right_rgb or len(left_rgb) != 3 or len(right_rgb) != 3:
        return None
    return sum(abs(int(left_rgb[index]) - int(right_rgb[index])) for index in range(3))


def _is_tiny_bubble(coords):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return False
    x1, y1, x2, y2 = coords[:4]
    box_width = max(0, int(x2) - int(x1))
    box_height = max(0, int(y2) - int(y1))
    return min(box_width, box_height) <= 32 or (box_width * box_height) <= 1100


def _resolve_background_luminance(color):
    bg_rgb = color.get("autoBgColor") or _parse_hex_color(color.get("bgColor"))
    return _relative_luminance(bg_rgb)


def _resolve_background_complexity(color):
    gray_stddev = float(color.get("grayStdDev", 0.0) or 0.0)
    edge_density = float(color.get("edgeDensity", 0.0) or 0.0)
    dark_pixel_ratio = float(color.get("darkPixelRatio", 0.0) or 0.0)
    return max(
        min(1.0, gray_stddev / 32.0),
        min(1.0, edge_density / 0.16),
        min(1.0, dark_pixel_ratio / 0.18),
    )


def _resolve_color_fast_mode():
    settings = load_settings()
    pipeline = settings.get("pipeline") or {}
    return bool(pipeline.get("color_fast_mode", True))


def _is_simple_light_bubble_color(color):
    if not isinstance(color, dict):
        return False
    bg_luminance = _resolve_background_luminance(color)
    confidence = float(color.get("colorConfidence", 0.0) or 0.0)
    if bg_luminance is None:
        return False
    return bg_luminance >= 235 and confidence >= 0.8


def _with_fast_background_metrics(color):
    updated = dict(color)
    updated.setdefault("grayStdDev", 0.0)
    updated.setdefault("edgeDensity", 0.0)
    updated.setdefault("darkPixelRatio", 0.0)
    return updated


def _is_color_unreliable(color):
    bg_rgb = color.get("autoBgColor") or _parse_hex_color(color.get("bgColor"))
    fg_rgb = color.get("autoFgColor") or _parse_hex_color(color.get("textColor"))
    confidence = float(color.get("colorConfidence", 0.0) or 0.0)
    bg_luminance = _relative_luminance(bg_rgb)
    fg_bg_distance = _rgb_distance(fg_rgb, bg_rgb)
    return (
        (bg_rgb is None and fg_rgb is None)
        or confidence < 0.45
        or (
            fg_bg_distance is not None
            and fg_bg_distance <= 12
            and bg_luminance is not None
            and bg_luminance <= 24
        )
    )


def _resolve_bubble_readability_style(style, color, coords):
    fill_color = color.get("bgColor")
    if _is_tiny_bubble(coords):
        return {
            "textColor": "#111111",
            "fillColor": fill_color,
            "strokeEnabled": style["strokeEnabled"],
            "strokeColor": "#FFFFFF",
            "strokeWidth": 0,
        }

    complexity = _resolve_background_complexity(color)
    color_unreliable = _is_color_unreliable(color)
    bg_luminance = _resolve_background_luminance(color)

    use_stroke = False
    if color_unreliable:
        use_stroke = complexity >= 0.5
    elif bg_luminance is None:
        use_stroke = complexity >= 0.5
    elif bg_luminance < 165:
        use_stroke = True
    elif bg_luminance >= 225:
        use_stroke = complexity >= 0.5
    else:
        use_stroke = complexity >= 0.35

    return {
        "textColor": "#111111",
        "fillColor": fill_color,
        "strokeEnabled": style["strokeEnabled"],
        "strokeColor": "#FFFFFF",
        "strokeWidth": 1 if style["strokeEnabled"] and use_stroke else 0,
    }


def _resolve_inpaint_config():
    settings = load_settings()
    inpaint = settings.get("inpaint") or {}
    method = str(inpaint.get("method") or "solid").strip().lower()
    if method not in {"solid", "lama_mpe", "litelama"}:
        method = "solid"
    return {
        "method": method,
        "mask_dilate_size": int(inpaint.get("mask_dilate_size", 1) or 0),
        "mask_box_expand_ratio": int(inpaint.get("mask_box_expand_ratio", 0) or 0),
    }


def _resolve_font_file_path(font_family):
    raw_value = str(font_family or "").strip()
    if not raw_value:
        return None

    candidate = Path(raw_value)
    project_root = find_project_root(__file__)
    settings = load_settings(project_root=project_root)
    saber_root = resolve_path_value((settings.get("paths") or {}).get("saber_root"), project_root=project_root)

    search_paths = []
    if candidate.is_absolute():
        search_paths.append(candidate)
    else:
        search_paths.extend(
            [
                project_root / raw_value,
                project_root / "src" / "app" / "static" / raw_value,
            ]
        )
        if saber_root:
            saber_root_path = Path(saber_root)
            search_paths.extend(
                [
                    saber_root_path / raw_value,
                    saber_root_path / "src" / "app" / "static" / raw_value,
                ]
            )

    for path in search_paths:
        if path.exists():
            return str(path)
    return None


def _load_watermark_font(font_family, font_size):
    font_path = _resolve_font_file_path(font_family)
    if font_path:
        try:
            return ImageFont.truetype(font_path, int(font_size))
        except OSError:
            pass
    return ImageFont.load_default()


def _apply_translation_watermark(image_path):
    output_path = Path(str(image_path or "").strip())
    if not output_path.exists():
        return

    style = _resolve_watermark_style()
    if not style["enabled"]:
        return

    text = str(style["text"] or "").strip()
    if not text:
        return

    with Image.open(output_path).convert("RGBA") as image:
        short_edge = max(1, min(image.size))
        font_size = max(
            int(style["minSize"]),
            min(
                int(style["maxSize"]),
                int(round(short_edge * float(style["fontSizeRatio"]))),
            ),
        )
        margin = max(4, int(round(short_edge * float(style["marginRatio"]))))
        stroke_width = max(0, int(style["strokeWidth"]))

        font = _load_watermark_font(style["fontFamily"], font_size)
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        text_width = max(1, int(bbox[2] - bbox[0]))
        text_height = max(1, int(bbox[3] - bbox[1]))

        x = max(margin, image.width - text_width - margin - int(bbox[0]))
        y = max(margin, image.height - text_height - margin - int(bbox[1]))

        fill_rgb = _parse_hex_color(style["fillColor"]) or [168, 168, 168]
        stroke_rgb = _parse_hex_color(style["strokeColor"]) or [255, 255, 255]
        draw.text(
            (x, y),
            text,
            font=font,
            fill=(*fill_rgb, max(0, min(255, int(style["fillAlpha"])))),
            stroke_width=stroke_width,
            stroke_fill=(*stroke_rgb, max(0, min(255, int(style["strokeAlpha"])))),
        )
        watermarked = Image.alpha_composite(image, overlay).convert("RGB")
        watermarked.save(output_path)


def translate_texts(texts, model=None, base_url=None, api_key=None, context_snapshot=None):
    translation = resolve_translation_config()
    return OpenAICompatibleTranslator().translate_texts(
        texts=texts,
        model=model or translation["model"],
        base_url=base_url or translation["base_url"],
        api_key=api_key if api_key is not None else translation["api_key"],
        context_snapshot=context_snapshot,
    )


_DEFAULT_TRANSLATE_TEXTS = translate_texts


def _call_translate_texts_multi_round(*, texts, model, base_url, api_key, context_snapshot):
    attempts = [
        {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "context_snapshot": context_snapshot,
        },
        {
            "model": model,
            "base_url": base_url,
            "context_snapshot": context_snapshot,
        },
        {
            "model": model,
            "base_url": base_url,
        },
    ]
    last_error = None
    for kwargs in attempts:
        try:
            return translate_texts_multi_round(texts, **kwargs)
        except TypeError as error:
            last_error = error
            error_text = str(error)
            if "unexpected keyword argument" not in error_text and "required keyword-only argument" not in error_text:
                raise
    raise last_error


def _call_inpaint_page(
    image_path,
    bubble_coords,
    raw_mask,
    *,
    bubble_polygons,
    output_path,
    method,
    saber_session,
    mask_dilate_size,
    mask_box_expand_ratio,
):
    try:
        return inpaint_page(
            image_path,
            bubble_coords,
            raw_mask=raw_mask,
            bubble_polygons=bubble_polygons,
            output_path=output_path,
            method=method,
            saber_session=saber_session,
            mask_dilate_size=mask_dilate_size,
            mask_box_expand_ratio=mask_box_expand_ratio,
        )
    except TypeError as error:
        if "mask_dilate_size" not in str(error) and "mask_box_expand_ratio" not in str(error):
            raise
        return inpaint_page(
            image_path,
            bubble_coords,
            raw_mask=raw_mask,
            bubble_polygons=bubble_polygons,
            output_path=output_path,
            method=method,
            saber_session=saber_session,
        )


def translate_texts_multi_round(texts, model=None, base_url=None, api_key=None, context_snapshot=None):
    if translate_texts is not _DEFAULT_TRANSLATE_TEXTS:
        attempts = [
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
                "api_key": api_key,
                "context_snapshot": context_snapshot,
            },
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
                "context_snapshot": context_snapshot,
            },
            {
                "texts": texts,
                "model": model,
                "base_url": base_url,
            },
        ]
        last_error = None
        translated = None
        for kwargs in attempts:
            try:
                translated = translate_texts(**kwargs)
                break
            except TypeError as error:
                last_error = error
                error_text = str(error)
                if "unexpected keyword argument" not in error_text and "required keyword-only argument" not in error_text:
                    raise
        if translated is None:
            raise last_error
        return _build_legacy_translation_payload(translated)
    translation = resolve_translation_config()
    return OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=texts,
        model=model or translation["model"],
        base_url=base_url or translation["base_url"],
        api_key=api_key if api_key is not None else translation["api_key"],
        context_snapshot=context_snapshot,
    )


def _resolve_inpaint_method():
    return _resolve_inpaint_config()["method"]


def _page_cache_paths(runtime, page_id):
    return runtime.page_cache_paths(page_id)


def _split_filtered_payload(payload):
    detection = {
        "bubbleCoords": payload.get("bubbleCoords", []) or [],
        "bubblePolygons": payload.get("bubblePolygons", []) or [],
        "autoDirections": payload.get("autoDirections", []) or [],
        "textlinesPerBubble": payload.get("textlinesPerBubble", []) or [],
        "bubbleColors": payload.get("bubbleColors", []) or [],
        "bubbleLayoutHints": payload.get("bubbleLayoutHints", []) or [],
        "multimodalLayout": payload.get("multimodalLayout"),
        "rawMask": payload.get("rawMask"),
    }
    ocr = {
        "originalTexts": payload.get("originalTexts", []) or [],
        "ocrResults": payload.get("ocrResults", []) or [],
    }
    return detection, ocr


def _enrich_bubble_color_metrics(payload, source_path):
    if not payload.get("bubbleColors"):
        return payload
    if _resolve_color_fast_mode() and all(
        _is_simple_light_bubble_color(color)
        for color in payload.get("bubbleColors", []) or []
    ):
        enriched = dict(payload)
        enriched["bubbleColors"] = [
            _with_fast_background_metrics(color)
            for color in payload["bubbleColors"]
        ]
        return enriched
    color_payload = enrich_bubble_colors_with_background_metrics(
        {"colors": payload["bubbleColors"]},
        source_path,
        payload.get("bubbleCoords", []) or [],
        payload.get("textlinesPerBubble", []) or [],
    )
    enriched = dict(payload)
    enriched["bubbleColors"] = color_payload.get("colors", payload["bubbleColors"])
    return enriched


def _build_bubbles(detection, ocr, translated_texts, *, layout_mode_override=None, font_family_override=None, image_size=None):
    style = _resolve_render_style(layout_mode_override=layout_mode_override, font_family_override=font_family_override)
    horizontal_style = _resolve_render_style(layout_mode_override="horizontal", font_family_override=font_family_override)
    vertical_style = _resolve_render_style(layout_mode_override="vertical", font_family_override=font_family_override)
    bubbles = []
    bubble_coords = detection.get("bubbleCoords", []) or []
    bubble_polygons = detection.get("bubblePolygons", []) or []
    auto_directions = detection.get("autoDirections", []) or []
    textlines_per_bubble = detection.get("textlinesPerBubble", []) or []
    original_texts = ocr.get("originalTexts", []) or []
    ocr_results = ocr.get("ocrResults", []) or []
    colors = detection.get("bubbleColors", []) or []
    bubble_profiles = build_bubble_text_profiles(detection, ocr, image_size=image_size)

    for index, coords in enumerate(bubble_coords):
        color = colors[index] if index < len(colors) and isinstance(colors[index], dict) else {}
        bubble_profile = bubble_profiles[index] if index < len(bubble_profiles) else {}
        render_coords = bubble_profile.get("renderCoords") or coords
        auto_direction = _normalize_layout_direction(
            auto_directions[index] if index < len(auto_directions) else "vertical"
        )
        if style["layoutMode"] == "horizontal":
            direction = "horizontal"
        elif style["layoutMode"] == "vertical":
            direction = "horizontal" if auto_direction == "horizontal" else "vertical"
        else:
            direction = auto_direction
        if bubble_profile.get("directionOverride"):
            direction = _normalize_layout_direction(bubble_profile.get("directionOverride"), default=direction)
        is_vertical_layout = direction == "vertical"
        bubble_style = vertical_style if is_vertical_layout else horizontal_style
        readability_style = _resolve_bubble_readability_style(bubble_style, color, coords)
        translated_text = translated_texts[index] if index < len(translated_texts) else ""
        if bubble_profile.get("suppressTranslation"):
            translated_text = ""
        bubbles.append(
            {
                "coords": render_coords,
                "polygon": bubble_polygons[index] if index < len(bubble_polygons) else [],
                "direction": direction,
                "textDirection": direction,
                "autoTextDirection": auto_direction,
                "textlines": textlines_per_bubble[index] if index < len(textlines_per_bubble) else [],
                "originalText": original_texts[index] if index < len(original_texts) else "",
                "translatedText": translated_text,
                "ocrResult": ocr_results[index] if index < len(ocr_results) else {},
                "fontFamily": bubble_style["fontFamily"],
                "textColor": readability_style["textColor"],
                "fillColor": readability_style["fillColor"],
                "strokeEnabled": readability_style["strokeEnabled"],
                "strokeColor": readability_style["strokeColor"],
                "strokeWidth": readability_style["strokeWidth"],
                "lineSpacing": bubble_style["lineSpacing"],
                "textAlign": bubble_profile.get("textAlignOverride") or bubble_style["textAlign"],
                "position": bubble_profile.get("positionOffset"),
                "layoutProfile": "vertical_layout2" if is_vertical_layout else None,
                "bubbleRole": bubble_profile.get("role", "dialogue"),
                "autoFontSettings": bubble_profile.get("autoFontSettings"),
                "autoFgColor": color.get("autoFgColor"),
                "autoBgColor": color.get("autoBgColor"),
                "colorConfidence": color.get("colorConfidence", 0.0),
            }
        )
    return bubbles


def _build_translation_context(runtime, page_id):
    pages = runtime.list_pages()
    if not pages:
        return {
            "historyPageIds": [],
            "confirmedTranslations": [],
            "glossary": {},
        }

    results_by_page = {}
    for page in pages:
        other_page_id = page.get("id")
        if not other_page_id or other_page_id == page_id:
            continue
        payload = runtime.load_result_or_default(other_page_id, default=None)
        if payload is not None:
            results_by_page[other_page_id] = payload

    return build_context_snapshot(pages, results_by_page, page_id)


def preprocess_page(source_path, saber_session=None, ocr_options=None):
    image_size = load_image_size(source_path)
    try:
        saber_ocr_options = resolve_saber_ocr_options(ocr_options)
    except TypeError as error:
        if "positional argument" not in str(error):
            raise
        saber_ocr_options = resolve_saber_ocr_options()
    payload = run_saber_task(
        "preprocess",
        {
            "image_path": source_path,
            **saber_ocr_options,
        },
        session=saber_session,
    )
    normalized = dict(payload)
    if "colors" in normalized and "bubbleColors" not in normalized:
        normalized["bubbleColors"] = normalized.pop("colors")
    normalized = _enrich_bubble_color_metrics(normalized, source_path)
    filtered_payload = filter_ocr_payload(normalized, image_size=image_size)
    return {
        "bubbleCoords": filtered_payload.get("bubbleCoords", []) or [],
        "bubblePolygons": filtered_payload.get("bubblePolygons", []) or [],
        "autoDirections": filtered_payload.get("autoDirections", []) or [],
        "textlinesPerBubble": filtered_payload.get("textlinesPerBubble", []) or [],
        "bubbleColors": filtered_payload.get("bubbleColors", []) or [],
        "originalTexts": filtered_payload.get("originalTexts", []) or [],
        "ocrResults": filtered_payload.get("ocrResults", []) or [],
        "rawMask": filtered_payload.get("rawMask"),
        "timings": payload.get("timings", {}) if isinstance(payload.get("timings"), dict) else {},
    }


def retry_preprocess_page_for_ocr(source_path, saber_session=None, ocr_options=None):
    source_path = Path(source_path)
    temp_output = None
    try:
        with Image.open(source_path) as image:
            enhanced = ImageOps.grayscale(image)
            enhanced = ImageOps.autocontrast(enhanced, cutoff=1)
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.35)
            enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.6)
            enhanced = enhanced.filter(ImageFilter.MedianFilter(size=3))

            handle, temp_name = tempfile.mkstemp(suffix=".png", prefix="translate-manga-cli-ocr-retry-")
            os.close(handle)
            temp_output = Path(temp_name)
            enhanced.save(temp_output)

        retry_payload = preprocess_page(str(temp_output), saber_session=saber_session, ocr_options=ocr_options)
        timings = dict(retry_payload.get("timings") or {})
        timings["ocrRetryPreprocess"] = True
        retry_payload["timings"] = timings
        return retry_payload
    finally:
        if temp_output is not None and temp_output.exists():
            temp_output.unlink(missing_ok=True)


def _call_ocr_page(image_path, bubble_coords, textlines_per_bubble, ocr_options=None):
    try:
        return ocr_page(image_path, bubble_coords, textlines_per_bubble, ocr_options=ocr_options)
    except TypeError as error:
        error_text = str(error)
        if "unexpected keyword argument" not in error_text and "positional argument" not in error_text:
            raise
    try:
        return ocr_page(image_path, bubble_coords, textlines_per_bubble)
    except TypeError as error:
        if "positional argument" not in str(error):
            raise
        return ocr_page(image_path, bubble_coords)


def redo_page_inpaint(runtime, page_id, source_path, cached_result, saber_session=None):
    page_paths = _page_cache_paths(runtime, page_id)
    clean_image_path = cached_result.get("cleanImagePath") or page_paths["cleanImagePath"]
    inpaint_config = _resolve_inpaint_config()
    clean = _call_inpaint_page(
        source_path,
        cached_result.get("bubbleCoords", []) or [],
        cached_result.get("rawMask"),
        bubble_polygons=cached_result.get("bubblePolygons", []) or [],
        output_path=clean_image_path,
        method=inpaint_config["method"],
        saber_session=saber_session,
        mask_dilate_size=inpaint_config["mask_dilate_size"],
        mask_box_expand_ratio=inpaint_config["mask_box_expand_ratio"],
    )
    updated = dict(cached_result)
    updated["cleanImagePath"] = clean["cleanImagePath"]
    return updated


def redo_page_render(runtime, page_id, source_path, cached_result, saber_session=None):
    page_paths = _page_cache_paths(runtime, page_id)
    updated = dict(cached_result)
    clean_image_path = updated.get("cleanImagePath") or page_paths["cleanImagePath"]
    if not Path(clean_image_path).exists():
        updated = redo_page_inpaint(runtime, page_id, source_path, updated, saber_session=saber_session)
        clean_image_path = updated["cleanImagePath"]

    translated_image_path = updated.get("translatedImagePath") or page_paths["translatedImagePath"]
    bubble_states = updated.get("bubbleStates") or updated.get("bubbles") or _build_bubbles(
        {
            "bubbleCoords": updated.get("bubbleCoords", []) or [],
            "bubblePolygons": updated.get("bubblePolygons", []) or [],
            "autoDirections": updated.get("autoDirections", []) or [],
            "textlinesPerBubble": updated.get("textlinesPerBubble", []) or [],
            "bubbleColors": updated.get("bubbleColors", []) or [],
        },
        {
            "originalTexts": updated.get("originalTexts", []) or [],
            "ocrResults": updated.get("ocrResults", []) or [],
        },
        updated.get("translatedTexts", []) or [],
        layout_mode_override=getattr(runtime, "layout_mode", None),
        font_family_override=getattr(runtime, "font_family", None),
        image_size=load_image_size(source_path),
    )
    rendered = render_page(
        clean_image_path,
        page_id,
        bubble_states,
        output_path=translated_image_path,
        auto_font_size=True,
        auto_font_settings=_resolve_auto_font_settings(layout_mode_override=getattr(runtime, "layout_mode", None)),
        saber_session=saber_session,
    )
    _apply_translation_watermark(rendered.get("translatedImagePath"))
    bubble_states = rendered.get("bubbleStates") or bubble_states
    updated["cleanImagePath"] = clean_image_path
    updated["translatedImagePath"] = rendered["translatedImagePath"]
    updated["bubbleStates"] = bubble_states
    updated["bubbles"] = bubble_states
    return updated


def _merge_retry_state(original_state, final_state, attempted, applied):
    merged_reasons = []
    for item in (original_state.get("reasons") or []) + (final_state.get("reasons") or []):
        if item not in merged_reasons:
            merged_reasons.append(item)
    return {
        "shouldRetry": bool(final_state.get("shouldRetry")),
        "reasons": merged_reasons,
        "attempted": bool(attempted),
        "applied": bool(applied),
    }


def run_page_pipeline(
    runtime: PipelineRuntime,
    page_id,
    source_path,
    model=None,
    base_url=None,
    api_key=None,
    preprocessed_payload=None,
    translated_texts=None,
    context_snapshot=None,
    saber_session=None,
    translation_payload=None,
):
    total_started_at = perf_counter()
    runtime_ocr_options = getattr(runtime, "ocr_options", None)
    if preprocessed_payload is not None:
        filtered_payload = dict(preprocessed_payload)
        filtered_payload["bubbleColors"] = filtered_payload.get("bubbleColors", []) or []
        filtered_payload = _enrich_bubble_color_metrics(filtered_payload, source_path)
        detection, ocr = _split_filtered_payload(filtered_payload)
        preprocessed_timings = filtered_payload.get("timings", {}) if isinstance(filtered_payload.get("timings"), dict) else {}
        detect_seconds = float(preprocessed_timings.get("detect", 0.0) or 0.0)
        ocr_seconds = float(preprocessed_timings.get("ocr", 0.0) or 0.0)
        color_seconds = float(preprocessed_timings.get("color", 0.0) or 0.0)
    else:
        image_size = load_image_size(source_path)

        detect_started_at = perf_counter()
        detection = filter_detection_payload(detect_page(source_path), image_size=image_size)
        detect_seconds = perf_counter() - detect_started_at

        ocr_started_at = perf_counter()
        ocr = _call_ocr_page(
            source_path,
            detection["bubbleCoords"],
            detection["textlinesPerBubble"],
            ocr_options=runtime_ocr_options,
        )
        filtered_payload = filter_ocr_payload({**detection, **ocr}, image_size=image_size)
        detection, ocr = _split_filtered_payload(filtered_payload)
        ocr_seconds = perf_counter() - ocr_started_at

        color_started_at = perf_counter()
        color_payload = extract_bubble_colors(
            source_path,
            detection["bubbleCoords"],
            detection["textlinesPerBubble"],
        )
        detection["bubbleColors"] = color_payload.get("colors", []) if isinstance(color_payload, dict) else []
        color_seconds = perf_counter() - color_started_at

    resolved_context_snapshot = context_snapshot or _build_translation_context(runtime, page_id)
    translate_seconds = 0.0
    normalized_translation_payload = _normalize_translation_payload(translation_payload) if translation_payload is not None else None

    if translated_texts is None:
        translate_started_at = perf_counter()
        translate_kwargs = {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "context_snapshot": resolved_context_snapshot,
        }
        normalized_translation_payload = _normalize_translation_payload(
            _call_translate_texts_multi_round(texts=ocr["originalTexts"], **translate_kwargs)
        )
        retry_state = _normalize_ocr_retry_state(normalized_translation_payload.get("ocrRetry"))

        if retry_state.get("shouldRetry"):
            retry_attempted = True
            retry_applied = False
            try:
                retry_payload = retry_preprocess_page_for_ocr(
                    source_path,
                    saber_session=saber_session,
                    ocr_options=runtime_ocr_options,
                )
                if retry_payload is not None:
                    retry_detection, retry_ocr = _split_filtered_payload(retry_payload)
                    retried_translation_payload = _normalize_translation_payload(
                        _call_translate_texts_multi_round(texts=retry_ocr["originalTexts"], **translate_kwargs)
                    )
                    final_retry_state = _normalize_ocr_retry_state(retried_translation_payload.get("ocrRetry"))
                    detection = retry_detection
                    ocr = retry_ocr
                    normalized_translation_payload = retried_translation_payload
                    normalized_translation_payload["ocrRetry"] = _merge_retry_state(
                        retry_state,
                        final_retry_state,
                        attempted=retry_attempted,
                        applied=True,
                    )
                    retry_applied = True
                    retry_timings = retry_payload.get("timings", {}) if isinstance(retry_payload.get("timings"), dict) else {}
                    detect_seconds = float(retry_timings.get("detect", detect_seconds) or detect_seconds)
                    ocr_seconds = float(retry_timings.get("ocr", ocr_seconds) or ocr_seconds)
                    color_seconds = float(retry_timings.get("color", color_seconds) or color_seconds)
            except Exception:
                normalized_translation_payload["ocrRetry"] = _merge_retry_state(
                    retry_state,
                    retry_state,
                    attempted=retry_attempted,
                    applied=retry_applied,
                )

        translated_texts = list(normalized_translation_payload.get("translatedTexts") or [])
        translate_seconds = perf_counter() - translate_started_at
    else:
        normalized_translation_payload = normalized_translation_payload or _build_legacy_translation_payload(translated_texts)
        normalized_translation_payload["translatedTexts"] = list(translated_texts or [])

    page_paths = _page_cache_paths(runtime, page_id)
    clean_image_path = page_paths["cleanImagePath"]
    translated_image_path = page_paths["translatedImagePath"]

    layout_mode_override = getattr(runtime, "layout_mode", None)
    bubble_states = _build_bubbles(
        detection,
        ocr,
        translated_texts,
        layout_mode_override=layout_mode_override,
        font_family_override=getattr(runtime, "font_family", None),
        image_size=load_image_size(source_path),
    )
    inpaint_config = _resolve_inpaint_config()

    inpaint_started_at = perf_counter()
    clean = _call_inpaint_page(
        source_path,
        detection["bubbleCoords"],
        detection.get("rawMask"),
        bubble_polygons=detection["bubblePolygons"],
        output_path=clean_image_path,
        method=inpaint_config["method"],
        saber_session=saber_session,
        mask_dilate_size=inpaint_config["mask_dilate_size"],
        mask_box_expand_ratio=inpaint_config["mask_box_expand_ratio"],
    )
    inpaint_seconds = perf_counter() - inpaint_started_at

    render_started_at = perf_counter()
    rendered = render_page(
        clean["cleanImagePath"],
        page_id,
        bubble_states,
        output_path=translated_image_path,
        auto_font_size=True,
        auto_font_settings=_resolve_auto_font_settings(layout_mode_override=layout_mode_override),
        saber_session=saber_session,
    )
    _apply_translation_watermark(rendered.get("translatedImagePath"))
    bubble_states = rendered.get("bubbleStates") or bubble_states
    render_seconds = perf_counter() - render_started_at
    total_seconds = perf_counter() - total_started_at

    return {
        "pageId": page_id,
        "bubbleCoords": detection["bubbleCoords"],
        "bubblePolygons": detection["bubblePolygons"],
        "autoDirections": detection["autoDirections"],
        "textlinesPerBubble": detection["textlinesPerBubble"],
        "bubbleColors": detection.get("bubbleColors", []),
        "originalTexts": ocr["originalTexts"],
        "ocrResults": ocr["ocrResults"],
        "translatedTexts": translated_texts,
        "translation": normalized_translation_payload,
        "ocrRetry": _normalize_ocr_retry_state(normalized_translation_payload.get("ocrRetry")),
        "translatedImagePath": rendered["translatedImagePath"],
        "cleanImagePath": clean["cleanImagePath"],
        "bubbleStates": bubble_states,
        "bubbles": bubble_states,
        "manualEdited": False,
        "contextInputs": resolved_context_snapshot,
        "timings": {
            "detect": detect_seconds,
            "ocr": ocr_seconds,
            "translate": translate_seconds,
            "color": color_seconds,
            "inpaint": inpaint_seconds,
            "render": render_seconds,
            "total": total_seconds,
        },
    }
