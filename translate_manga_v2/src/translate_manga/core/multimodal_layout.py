import base64
import io
import json
import re
from pathlib import Path

import openai
from PIL import Image


_ROLE_ALIASES = {
    "dialog": "dialogue",
    "dialogue": "dialogue",
    "speech": "dialogue",
    "bubble": "dialogue",
    "对白": "dialogue",
    "台词": "dialogue",
    "narration": "narration",
    "narrative": "narration",
    "caption": "narration",
    "exposition": "narration",
    "说明": "narration",
    "旁白": "narration",
    "title": "title",
    "chapter_title": "title",
    "标题": "title",
    "page_number": "page_number",
    "page number": "page_number",
    "pagenumber": "page_number",
    "页码": "page_number",
    "页号": "page_number",
    "header": "header",
    "页眉": "header",
    "sfx": "sfx",
    "sound": "sfx",
    "sound_effect": "sfx",
    "onomatopoeia": "sfx",
    "拟声词": "sfx",
    "noise": "noise",
    "ocr_noise": "noise",
}

_ORIENTATION_ALIASES = {
    "h": "horizontal",
    "horizontal": "horizontal",
    "横排": "horizontal",
    "横向": "horizontal",
    "v": "vertical",
    "vertical": "vertical",
    "竖排": "vertical",
    "纵向": "vertical",
    "mixed": "mixed",
    "混排": "mixed",
}


def _normalize_role(value):
    key = str(value or "").strip().lower()
    return _ROLE_ALIASES.get(key, "dialogue")


def _normalize_orientation(value):
    key = str(value or "").strip().lower()
    return _ORIENTATION_ALIASES.get(key, "unknown")


def _extract_json_text(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0) if match else text


def _response_content(response):
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""
    if "regions" in response:
        return json.dumps(response, ensure_ascii=False)
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    return str(message.get("content") or "")


def _coerce_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bbox_from_value(value):
    if isinstance(value, dict):
        if all(key in value for key in ("x1", "y1", "x2", "y2")):
            return [value.get("x1"), value.get("y1"), value.get("x2"), value.get("y2")]
        if all(key in value for key in ("left", "top", "right", "bottom")):
            return [value.get("left"), value.get("top"), value.get("right"), value.get("bottom")]
        if all(key in value for key in ("x", "y", "w", "h")):
            x = _coerce_float(value.get("x"))
            y = _coerce_float(value.get("y"))
            w = _coerce_float(value.get("w"))
            h = _coerce_float(value.get("h"))
            if None not in (x, y, w, h):
                return [x, y, x + w, y + h]
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return list(value[:4])
    return None


def _normalize_bbox(value, image_size=None):
    raw_bbox = _bbox_from_value(value)
    if raw_bbox is None:
        return None
    numbers = [_coerce_float(item) for item in raw_bbox]
    if any(item is None for item in numbers):
        return None
    x1, y1, x2, y2 = numbers
    if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        width = max(1, int(image_size[0]))
        height = max(1, int(image_size[1]))
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
            x1 *= width
            x2 *= width
            y1 *= height
            y2 *= height
        x1 = min(max(0, x1), width)
        x2 = min(max(0, x2), width)
        y1 = min(max(0, y1), height)
        y2 = min(max(0, y2), height)
    left = int(round(min(x1, x2)))
    right = int(round(max(x1, x2)))
    top = int(round(min(y1, y2)))
    bottom = int(round(max(y1, y2)))
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def normalize_multimodal_layout_response(response, image_size=None):
    try:
        payload = json.loads(_extract_json_text(_response_content(response)))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return {"status": "failed", "reason": f"invalid_json: {error}", "regions": []}

    regions = []
    for index, region in enumerate(payload.get("regions") or [], start=1):
        if not isinstance(region, dict):
            continue
        bbox = _normalize_bbox(region.get("bbox") or region.get("box"), image_size=image_size)
        if bbox is None:
            continue
        confidence = _coerce_float(region.get("confidence"))
        regions.append(
            {
                "id": str(region.get("id") or f"region-{index}"),
                "role": _normalize_role(region.get("role") or region.get("type")),
                "bbox": bbox,
                "orientation": _normalize_orientation(region.get("orientation") or region.get("direction")),
                "text": str(region.get("text") or "").strip(),
                "confidence": confidence,
            }
        )
    return {
        "status": "ok",
        "regions": regions,
    }


def _area(box):
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return 0
    return max(0, int(box[2]) - int(box[0])) * max(0, int(box[3]) - int(box[1]))


def _iou(a, b):
    x1 = max(int(a[0]), int(b[0]))
    y1 = max(int(a[1]), int(b[1]))
    x2 = min(int(a[2]), int(b[2]))
    y2 = min(int(a[3]), int(b[3]))
    intersection = _area([x1, y1, x2, y2])
    if intersection <= 0:
        return 0.0
    union = _area(a) + _area(b) - intersection
    return float(intersection) / float(union) if union > 0 else 0.0


def _center(box):
    return ((int(box[0]) + int(box[2])) / 2.0, (int(box[1]) + int(box[3])) / 2.0)


def _contains_point(box, point):
    x, y = point
    return int(box[0]) <= x <= int(box[2]) and int(box[1]) <= y <= int(box[3])


def _match_score(bubble_box, region_box):
    score = _iou(bubble_box, region_box)
    if score > 0:
        return score
    if _contains_point(region_box, _center(bubble_box)) or _contains_point(bubble_box, _center(region_box)):
        return 0.025
    return 0.0


def _hint_from_region(region):
    role = str((region or {}).get("role") or "").strip()
    orientation = str((region or {}).get("orientation") or "").strip()
    hint = {
        "source": "multimodal",
        "matchedRegionId": (region or {}).get("id"),
        "matchedRole": role,
        "matchedText": (region or {}).get("text") or "",
    }
    if role in {"page_number", "header", "noise"}:
        hint["role"] = role
        hint["suppressTranslation"] = True
        return hint
    if role == "sfx":
        hint["role"] = "sfx"
        hint["suppressTranslation"] = True
        return hint
    if role == "title":
        hint["role"] = "title_caption"
        if orientation in {"horizontal", "vertical"}:
            hint["directionOverride"] = orientation
        return hint
    if role == "narration":
        hint["role"] = "long_narration"
        hint["textAlignOverride"] = "start"
        if orientation in {"horizontal", "vertical"}:
            hint["directionOverride"] = orientation
        return hint
    hint["role"] = "dialogue"
    if orientation in {"horizontal", "vertical"}:
        hint["directionOverride"] = orientation
    return hint


def build_bubble_layout_hints(layout, bubble_coords, min_score=0.02):
    regions = (layout or {}).get("regions") or []
    hints = []
    for coords in bubble_coords or []:
        best_region = None
        best_score = 0.0
        if isinstance(coords, (list, tuple)) and len(coords) >= 4:
            for region in regions:
                region_box = (region or {}).get("bbox")
                if not isinstance(region_box, (list, tuple)) or len(region_box) < 4:
                    continue
                score = _match_score(coords, region_box)
                if score > best_score:
                    best_score = score
                    best_region = region
        hints.append(_hint_from_region(best_region) if best_region is not None and best_score >= min_score else {})
    return hints


def _image_to_data_url(image_path, max_edge):
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        original_size = [width, height]
        max_edge = max(256, int(max_edge or 1280))
        if max(width, height) > max_edge:
            scale = float(max_edge) / float(max(width, height))
            image = image.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                Image.Resampling.LANCZOS,
            )
        request_size = [image.width, image.height]
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", original_size, request_size


def _layout_prompt(original_size=None, request_size=None):
    original = original_size or ["?", "?"]
    request = request_size or original
    return (
        "请分析这页漫画的文字版面，只返回 JSON。"
        "JSON 格式: {\"regions\":[{\"id\":\"r1\",\"role\":\"dialogue|narration|title|page_number|header|sfx|noise\","
        "\"bbox\":[x1,y1,x2,y2],\"orientation\":\"horizontal|vertical|mixed|unknown\",\"text\":\"可读原文\",\"confidence\":0.0}]}. "
        f"原图尺寸为 {original[0]}x{original[1]}，你看到的输入图尺寸为 {request[0]}x{request[1]}；"
        "bbox 请使用输入图像素坐标，不要使用原图坐标。无法确认的文本 text 可为空。不要翻译，不要解释。"
    )


def _scale_layout_bboxes(layout, *, source_size, target_size):
    if not isinstance(layout, dict):
        return layout
    if not (
        isinstance(source_size, (list, tuple))
        and isinstance(target_size, (list, tuple))
        and len(source_size) >= 2
        and len(target_size) >= 2
    ):
        return layout
    source_width = max(1, int(source_size[0]))
    source_height = max(1, int(source_size[1]))
    target_width = max(1, int(target_size[0]))
    target_height = max(1, int(target_size[1]))
    if source_width == target_width and source_height == target_height:
        return layout

    scale_x = float(target_width) / float(source_width)
    scale_y = float(target_height) / float(source_height)
    scaled = dict(layout)
    scaled_regions = []
    for region in layout.get("regions") or []:
        if not isinstance(region, dict):
            continue
        updated_region = dict(region)
        bbox = region.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            updated_region["bbox"] = [
                int(round(float(bbox[0]) * scale_x)),
                int(round(float(bbox[1]) * scale_y)),
                int(round(float(bbox[2]) * scale_x)),
                int(round(float(bbox[3]) * scale_y)),
            ]
        scaled_regions.append(updated_region)
    scaled["regions"] = scaled_regions
    return scaled


def request_multimodal_layout(image_path, config):
    config = config or {}
    client = openai.OpenAI(
        api_key=str(config.get("api_key") or "").strip() or "dummy",
        base_url=str(config.get("base_url") or "").strip(),
    )
    data_url, original_size, request_size = _image_to_data_url(image_path, config.get("max_edge") or 1280)
    completion = client.chat.completions.create(
        model=str(config.get("model") or "mimo-v2.5"),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _layout_prompt(original_size=original_size, request_size=request_size)},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
        stream=False,
        temperature=0,
        timeout=float(config.get("request_timeout_seconds") or 90.0),
    )
    content = ((completion.choices or [None])[0].message.content or "").strip()
    layout = normalize_multimodal_layout_response(content, image_size=request_size)
    layout = _scale_layout_bboxes(layout, source_size=request_size, target_size=original_size)
    layout["imageSize"] = original_size
    layout["requestImageSize"] = request_size
    usage = getattr(completion, "usage", None)
    if usage is not None:
        layout["usage"] = {
            "inputTokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "outputTokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "totalTokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
    return layout


def _empty_hints(preprocessed_payload):
    return [{} for _ in (preprocessed_payload.get("bubbleCoords") or [])]


def apply_multimodal_layout_assist(image_path, preprocessed_payload, config, request_layout=None):
    payload = dict(preprocessed_payload or {})
    if not (config or {}).get("enabled"):
        return payload
    if (
        not str((config or {}).get("model") or "").strip()
        or not str((config or {}).get("base_url") or "").strip()
        or not str((config or {}).get("api_key") or "").strip()
    ):
        payload["multimodalLayout"] = {"status": "skipped", "reason": "not_configured", "regions": []}
        payload["bubbleLayoutHints"] = _empty_hints(payload)
        return payload

    request_layout = request_layout or request_multimodal_layout
    try:
        layout = request_layout(Path(image_path), config)
        if not isinstance(layout, dict) or "regions" not in layout:
            layout = normalize_multimodal_layout_response(layout)
        layout.setdefault("status", "ok")
        layout.setdefault("regions", [])
    except Exception as error:
        payload["multimodalLayout"] = {"status": "failed", "reason": str(error), "regions": []}
        payload["bubbleLayoutHints"] = _empty_hints(payload)
        return payload

    payload["multimodalLayout"] = layout
    payload["bubbleLayoutHints"] = build_bubble_layout_hints(layout, payload.get("bubbleCoords") or [])
    return payload
