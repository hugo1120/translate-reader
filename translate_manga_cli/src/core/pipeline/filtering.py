import re
from pathlib import Path

from PIL import Image


_FULLWIDTH_DIGIT_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")
_PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,4}$")
_INDEXED_FIELDS = (
    "bubbleCoords",
    "bubblePolygons",
    "autoDirections",
    "textlinesPerBubble",
    "bubbleColors",
    "originalTexts",
    "ocrResults",
    "translatedTexts",
    "bubbles",
)


def load_image_size(image_path):
    with Image.open(Path(image_path)) as image:
        return image.size


def filter_detection_payload(payload, image_size):
    return _filter_payload(payload, image_size=image_size, use_text_filters=False)


def filter_ocr_payload(payload, image_size):
    return _filter_payload(payload, image_size=image_size, use_text_filters=True)


def _filter_payload(payload, image_size, use_text_filters):
    bubble_coords = payload.get("bubbleCoords", []) or []
    kept_indices = []

    for index, coords in enumerate(bubble_coords):
        text = ""
        original_texts = payload.get("originalTexts", []) or []
        if index < len(original_texts):
            text = original_texts[index]

        if _should_keep_bubble(coords, text, image_size, use_text_filters=use_text_filters):
            kept_indices.append(index)

    filtered = dict(payload)
    for field in _INDEXED_FIELDS:
        values = payload.get(field)
        if isinstance(values, list):
            filtered[field] = [values[index] for index in kept_indices if index < len(values)]
    return filtered


def _should_keep_bubble(coords, text, image_size, use_text_filters):
    if not _passes_geometry_filter(coords):
        return False
    if use_text_filters and _looks_like_page_number(text, coords, image_size):
        return False
    return True


def _passes_geometry_filter(coords):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return False

    x1, y1, x2, y2 = [int(value) for value in coords[:4]]
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    area = width * height

    if width < 6 or height < 6:
        return False
    if area < 160 and min(width, height) < 12:
        return False
    return True


def _looks_like_page_number(text, coords, image_size):
    if not text or not image_size:
        return False

    normalized = str(text).translate(_FULLWIDTH_DIGIT_TRANS).strip()
    normalized = normalized.strip("[](){}（）【】「」『』〔〕<>")
    normalized = "".join(normalized.split())
    if not _PAGE_NUMBER_PATTERN.fullmatch(normalized):
        return False

    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return False

    image_width, image_height = image_size
    x1, y1, x2, y2 = [int(value) for value in coords[:4]]
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    if width > max(96, int(image_width * 0.2)) or height > max(96, int(image_height * 0.2)):
        return False

    side_margin = max(48, int(image_width * 0.08))
    top_margin = max(48, int(image_height * 0.05))
    bottom_margin = max(48, int(image_height * 0.05))
    near_side = x1 <= side_margin or x2 >= image_width - side_margin
    near_top = y1 <= top_margin
    near_bottom = y2 >= image_height - bottom_margin

    return near_bottom or (near_top and near_side)
