import json
import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections import deque
from pathlib import Path
from threading import Lock, Thread

from translate_manga.config.paths import find_project_root
from translate_manga.config.settings import load_settings, resolve_path_value, resolve_runtime_config


def _normalize_layout_direction(value, default="vertical"):
    raw_value = str(value or "").strip().lower()
    if raw_value == "auto":
        return "auto"
    if raw_value in {"v", "vertical"}:
        return "vertical"
    if raw_value in {"h", "horizontal"}:
        return "horizontal"
    return default


_SCRIPTS = {
    "detect": textwrap.dedent(
        """
        import base64
        import io
        import json
        import sys
        import numpy as np
        from PIL import Image
        from src.core.detection import get_bubble_detection_result_with_auto_directions

        def encode_mask_to_base64(mask):
            if mask is None:
                return None
            pil_image = Image.fromarray(np.asarray(mask).astype("uint8"))
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")

        def reading_order_to_right_to_left(payload):
            raw_value = str(payload.get("reading_order") or payload.get("readingOrder") or "rtl").strip().lower()
            return raw_value not in {"ltr", "left-to-right", "left_to_right"}

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["image_path"]).convert("RGB")
        result = get_bubble_detection_result_with_auto_directions(
            image,
            right_to_left=reading_order_to_right_to_left(payload),
        )
        print(json.dumps({
            "bubbleCoords": result.get("coords", []),
            "bubblePolygons": result.get("polygons", []),
            "autoDirections": result.get("auto_directions", []),
            "textlinesPerBubble": result.get("textlines_per_bubble", []),
            "rawMask": encode_mask_to_base64(result.get("raw_mask")),
        }, ensure_ascii=False))
        """
    ),
    "ocr": textwrap.dedent(
        """
        import json
        import sys
        from PIL import Image
        from src.core.ocr import recognize_ocr_results_in_bubbles
        from src.core.ocr_types import extract_texts_from_ocr_results, ocr_results_to_dicts

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["image_path"]).convert("RGB")
        results = recognize_ocr_results_in_bubbles(
            image,
            payload.get("bubble_coords", []),
            source_language=payload.get("source_language", "japanese"),
            ocr_engine=payload.get("ocr_engine", "manga_ocr"),
            textlines_per_bubble=payload.get("textlines_per_bubble", []),
            enable_hybrid_ocr=bool(payload.get("enable_hybrid_ocr", False)),
            secondary_ocr_engine=payload.get("secondary_ocr_engine"),
            hybrid_ocr_threshold=float(payload.get("hybrid_ocr_threshold", 0.2) or 0.2),
        )
        print(json.dumps({
            "originalTexts": extract_texts_from_ocr_results(results),
            "ocrResults": ocr_results_to_dicts(results),
        }, ensure_ascii=False))
        """
    ),
    "color": textwrap.dedent(
        """
        import json
        import sys
        from PIL import Image
        from src.core.color_extractor import extract_bubble_colors

        def rgb_to_hex(rgb):
            if rgb is None:
                return None
            return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["image_path"]).convert("RGB")
        bubble_coords = payload.get("bubble_coords", [])
        textlines_per_bubble = payload.get("textlines_per_bubble", [])
        results = extract_bubble_colors(
            image,
            bubble_coords,
            textlines_per_bubble,
            device="cpu",
        )
        colors = []
        for item in results:
            fg_color = item.get("fg_color")
            bg_color = item.get("bg_color")
            colors.append({
                "textColor": rgb_to_hex(fg_color),
                "bgColor": rgb_to_hex(bg_color),
                "autoFgColor": fg_color,
                "autoBgColor": bg_color,
                "colorConfidence": float(item.get("confidence", 0.0) or 0.0),
            })
        print(json.dumps({
            "colors": colors,
        }, ensure_ascii=False))
        """
    ),
    "preprocess": textwrap.dedent(
        """
        import base64
        import io
        import json
        import sys
        from time import perf_counter
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from src.core.detection import get_bubble_detection_result_with_auto_directions
        from src.core.ocr import recognize_ocr_results_in_bubbles
        from src.core.ocr_types import extract_texts_from_ocr_results, ocr_results_to_dicts
        from src.core.color_extractor import extract_bubble_colors

        def rgb_to_hex(rgb):
            if rgb is None:
                return None
            return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])

        def has_color_model():
            model_dir = Path("models") / "ocr_48px"
            return (model_dir / "ocr_ar_48px.ckpt").exists() and (model_dir / "alphabet-all-v7.txt").exists()

        def encode_mask_to_base64(mask):
            if mask is None:
                return None
            pil_image = Image.fromarray(np.asarray(mask).astype("uint8"))
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")

        def reading_order_to_right_to_left(payload):
            raw_value = str(payload.get("reading_order") or payload.get("readingOrder") or "rtl").strip().lower()
            return raw_value not in {"ltr", "left-to-right", "left_to_right"}

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["image_path"]).convert("RGB")

        detect_started_at = perf_counter()
        detection = get_bubble_detection_result_with_auto_directions(
            image,
            right_to_left=reading_order_to_right_to_left(payload),
        )
        detect_seconds = perf_counter() - detect_started_at

        bubble_coords = detection.get("coords", [])
        detect_payload = {
            "bubbleCoords": bubble_coords,
            "bubblePolygons": detection.get("polygons", []),
            "autoDirections": detection.get("auto_directions", []),
            "textlinesPerBubble": detection.get("textlines_per_bubble", []),
            "rawMask": encode_mask_to_base64(detection.get("raw_mask")),
        }

        ocr_started_at = perf_counter()
        ocr_results = recognize_ocr_results_in_bubbles(
            image,
            bubble_coords,
            source_language=payload.get("source_language", "japanese"),
            ocr_engine=payload.get("ocr_engine", "manga_ocr"),
            textlines_per_bubble=detection.get("textlines_per_bubble", []),
            enable_hybrid_ocr=bool(payload.get("enable_hybrid_ocr", False)),
            secondary_ocr_engine=payload.get("secondary_ocr_engine"),
            hybrid_ocr_threshold=float(payload.get("hybrid_ocr_threshold", 0.2) or 0.2),
        )
        ocr_seconds = perf_counter() - ocr_started_at

        color_started_at = perf_counter()
        colors = []
        if has_color_model():
            color_results = extract_bubble_colors(
                image,
                bubble_coords,
                detection.get("textlines_per_bubble", []),
                device="cpu",
            )
            for item in color_results:
                fg_color = item.get("fg_color")
                bg_color = item.get("bg_color")
                colors.append({
                    "textColor": rgb_to_hex(fg_color),
                    "bgColor": rgb_to_hex(bg_color),
                    "autoFgColor": fg_color,
                    "autoBgColor": bg_color,
                    "colorConfidence": float(item.get("confidence", 0.0) or 0.0),
                })
        else:
            colors = [
                {
                    "textColor": None,
                    "bgColor": None,
                    "autoFgColor": None,
                    "autoBgColor": None,
                    "colorConfidence": 0.0,
                }
                for _ in bubble_coords
            ]
        color_seconds = perf_counter() - color_started_at

        print(json.dumps({
            **detect_payload,
            "originalTexts": extract_texts_from_ocr_results(ocr_results),
            "ocrResults": ocr_results_to_dicts(ocr_results),
            "colors": colors,
            "timings": {
                "detect": detect_seconds,
                "ocr": ocr_seconds,
                "color": color_seconds,
                "total": detect_seconds + ocr_seconds + color_seconds,
            },
        }, ensure_ascii=False))
        """
    ),
    "inpaint": textwrap.dedent(
        """
        import base64
        import io
        import json
        import sys
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from src.core.inpainting import inpaint_bubbles

        def decode_mask_from_base64(raw_mask):
            if not raw_mask:
                return None
            if "," in raw_mask:
                raw_mask = raw_mask.split(",", 1)[1]
            image = Image.open(io.BytesIO(base64.b64decode(raw_mask)))
            if image.mode != "L":
                image = image.convert("L")
            return np.array(image)

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["image_path"]).convert("RGB")
        requested_method = payload.get("method", "solid")
        actual_method = "solid" if requested_method == "solid" else "lama"
        lama_model = payload.get("lama_model", "lama_mpe")
        bubble_coords = payload.get("bubble_coords", [])
        bubble_polygons = payload.get("bubble_polygons") or None
        raw_mask = payload.get("raw_mask")
        precise_mask = decode_mask_from_base64(raw_mask)
        cleaned, clean_background = inpaint_bubbles(
            image,
            bubble_coords,
            method=actual_method,
            bubble_polygons=bubble_polygons,
            precise_mask=precise_mask,
            mask_dilate_size=int(payload.get("mask_dilate_size", 0) or 0),
            mask_box_expand_ratio=int(payload.get("mask_box_expand_ratio", 0) or 0),
            lama_model=lama_model,
        )
        output_path = Path(payload["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image_to_save = clean_background or cleaned
        image_to_save.save(output_path)
        print(json.dumps({
            "cleanImagePath": str(output_path),
        }, ensure_ascii=False))
        """
    ),
    "render": textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path
        from PIL import Image
        from src.core.config_models import BubbleState
        from src.core.rendering import re_render_with_states

        def normalize_layout_direction(value, default="vertical"):
            raw_value = str(value or "").strip().lower()
            if raw_value in {"v", "vertical"}:
                return "vertical"
            if raw_value in {"h", "horizontal"}:
                return "horizontal"
            return default

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["clean_image_path"]).convert("RGB")
        setattr(image, "_clean_image", image.copy())
        setattr(image, "_clean_background", image.copy())

        bubble_states = []
        for bubble in payload.get("bubbles", []):
            text_direction = normalize_layout_direction(
                bubble.get("textDirection", bubble.get("direction", "vertical"))
            )
            auto_text_direction = normalize_layout_direction(
                bubble.get("autoTextDirection", bubble.get("direction", text_direction)),
                default=text_direction,
            )
            bubble_payload = {
                "originalText": bubble.get("originalText", ""),
                "translatedText": bubble.get("translatedText", ""),
                "coords": bubble.get("coords", [0, 0, 0, 0]),
                "polygon": bubble.get("polygon", []),
                "textDirection": text_direction,
                "autoTextDirection": auto_text_direction,
                "textlines": bubble.get("textlines", []),
                "ocrResult": bubble.get("ocrResult"),
            }
            for key in (
                "fontSize",
                "fontFamily",
                "textColor",
                "fillColor",
                "rotationAngle",
                "position",
                "strokeEnabled",
                "strokeColor",
                "strokeWidth",
                "lineSpacing",
                "textAlign",
                "inpaintMethod",
                "autoFgColor",
                "autoBgColor",
                "colorConfidence",
            ):
                if key in bubble and bubble.get(key) is not None:
                    bubble_payload[key] = bubble.get(key)
            state = BubbleState.from_dict(bubble_payload)
            setattr(state, "_layout_profile", bubble.get("layoutProfile"))
            bubble_states.append(state)

        auto_font_settings = payload.get("auto_font_settings") or {}
        if bool(payload.get("auto_font_size", False)):
            min_size = int(auto_font_settings.get("min_size", 12) or 12)
            max_size = int(auto_font_settings.get("max_size", 80) or 80)
            padding_ratio = float(auto_font_settings.get("padding_ratio", 1.0) or 1.0)
            from src.core.rendering import calculate_auto_font_size
            for state in bubble_states:
                if not state.translated_text:
                    continue
                x1, y1, x2, y2 = state.coords
                state.font_size = calculate_auto_font_size(
                    state.translated_text,
                    x2 - x1,
                    y2 - y1,
                    state.text_direction,
                    state.font_family,
                    min_size=min_size,
                    max_size=max_size,
                    padding_ratio=padding_ratio,
                )

        rendered = re_render_with_states(
            image,
            bubble_states,
            use_lama=False,
            auto_font_size=False,
        )
        output_path = Path(payload["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered.save(output_path)
        print(json.dumps({
            "translatedImagePath": str(output_path),
            "bubbleStates": [state.to_dict() for state in bubble_states],
        }, ensure_ascii=False))
        """
    ),
    "render_single": textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path
        from PIL import Image
        from src.core.config_models import BubbleState
        from src.core.rendering import calculate_auto_font_size, render_single_bubble_unified

        def normalize_layout_direction(value, default="vertical"):
            raw_value = str(value or "").strip().lower()
            if raw_value in {"v", "vertical"}:
                return "vertical"
            if raw_value in {"h", "horizontal"}:
                return "horizontal"
            return default

        payload = json.loads(sys.argv[1])
        image = Image.open(payload["clean_image_path"]).convert("RGB")
        setattr(image, "_clean_image", image.copy())
        setattr(image, "_clean_background", image.copy())

        bubble_states = []
        for bubble in payload.get("bubble_states", []):
            text_direction = normalize_layout_direction(
                bubble.get("textDirection", bubble.get("direction", "vertical"))
            )
            auto_text_direction = normalize_layout_direction(
                bubble.get("autoTextDirection", bubble.get("direction", text_direction)),
                default=text_direction,
            )
            bubble_payload = dict(bubble)
            bubble_payload["textDirection"] = text_direction
            bubble_payload["autoTextDirection"] = auto_text_direction
            state = BubbleState.from_dict(bubble_payload)
            setattr(state, "_layout_profile", bubble.get("layoutProfile"))
            raw_font_size = bubble.get("fontSize")
            if raw_font_size in (None, ""):
                auto_font_settings = payload.get("auto_font_settings") or {}
                min_size = int(auto_font_settings.get("min_size", 12) or 12)
                max_size = int(auto_font_settings.get("max_size", 80) or 80)
                padding_ratio = float(auto_font_settings.get("padding_ratio", 1.0) or 1.0)
                x1, y1, x2, y2 = state.coords
                state.font_size = calculate_auto_font_size(
                    state.translated_text,
                    x2 - x1,
                    y2 - y1,
                    state.text_direction,
                    state.font_family,
                    min_size=min_size,
                    max_size=max_size,
                    padding_ratio=padding_ratio,
                ) if state.translated_text else 0
            bubble_states.append(state)

        rendered = render_single_bubble_unified(
            image,
            bubble_states,
            int(payload.get("bubble_index", 0)),
        )
        output_path = Path(payload["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered.save(output_path)
        print(json.dumps({
            "translatedImagePath": str(output_path),
            "bubbleStates": [state.to_dict() for state in bubble_states],
        }, ensure_ascii=False))
        """
    ),
}


DEFAULT_SESSION_TIMEOUT_SECONDS = 45.0


_WORKER_SCRIPT = textwrap.dedent(
    """
    import base64
    import io
    import json
    import numpy as np
    import sys
    import traceback
    from time import perf_counter
    from pathlib import Path
    from PIL import Image
    from src.core.color_extractor import extract_bubble_colors
    from src.core.config_models import BubbleState
    from src.core.detection import get_bubble_detection_result_with_auto_directions
    from src.core.inpainting import inpaint_bubbles
    from src.core.ocr import recognize_ocr_results_in_bubbles
    from src.core.ocr_types import extract_texts_from_ocr_results, ocr_results_to_dicts
    from src.core.rendering import calculate_auto_font_size, re_render_with_states, render_single_bubble_unified

    def normalize_layout_direction(value, default="vertical"):
        raw_value = str(value or "").strip().lower()
        if raw_value in {"v", "vertical"}:
            return "vertical"
        if raw_value in {"h", "horizontal"}:
            return "horizontal"
        return default

    def rgb_to_hex(rgb):
        if rgb is None:
            return None
        return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])

    def has_color_model():
        model_dir = Path("models") / "ocr_48px"
        return (model_dir / "ocr_ar_48px.ckpt").exists() and (model_dir / "alphabet-all-v7.txt").exists()

    def reading_order_to_right_to_left(payload):
        raw_value = str(payload.get("reading_order") or payload.get("readingOrder") or "rtl").strip().lower()
        return raw_value not in {"ltr", "left-to-right", "left_to_right"}

    def build_color_payload(color_results):
        colors = []
        for item in color_results:
            fg_color = item.get("fg_color")
            bg_color = item.get("bg_color")
            colors.append({
                "textColor": rgb_to_hex(fg_color),
                "bgColor": rgb_to_hex(bg_color),
                "autoFgColor": fg_color,
                "autoBgColor": bg_color,
                "colorConfidence": float(item.get("confidence", 0.0) or 0.0),
            })
        return colors

    def encode_mask_to_base64(mask):
        if mask is None:
            return None
        pil_image = Image.fromarray(np.asarray(mask).astype("uint8"))
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def decode_mask_from_base64(raw_mask):
        if not raw_mask:
            return None
        if "," in raw_mask:
            raw_mask = raw_mask.split(",", 1)[1]
        image = Image.open(io.BytesIO(base64.b64decode(raw_mask)))
        if image.mode != "L":
            image = image.convert("L")
        return np.array(image)

    def build_bubble_states(bubbles):
        bubble_states = []
        for bubble in bubbles:
            text_direction = normalize_layout_direction(
                bubble.get("textDirection", bubble.get("direction", "vertical"))
            )
            auto_text_direction = normalize_layout_direction(
                bubble.get("autoTextDirection", bubble.get("direction", text_direction)),
                default=text_direction,
            )
            bubble_payload = {
                "originalText": bubble.get("originalText", ""),
                "translatedText": bubble.get("translatedText", ""),
                "coords": bubble.get("coords", [0, 0, 0, 0]),
                "polygon": bubble.get("polygon", []),
                "textDirection": text_direction,
                "autoTextDirection": auto_text_direction,
                "textlines": bubble.get("textlines", []),
                "ocrResult": bubble.get("ocrResult"),
            }
            for key in (
                "fontSize",
                "fontFamily",
                "textColor",
                "fillColor",
                "rotationAngle",
                "position",
                "strokeEnabled",
                "strokeColor",
                "strokeWidth",
                "lineSpacing",
                "textAlign",
                "inpaintMethod",
                "autoFgColor",
                "autoBgColor",
                "colorConfidence",
            ):
                if key in bubble and bubble.get(key) is not None:
                    bubble_payload[key] = bubble.get(key)
            state = BubbleState.from_dict(bubble_payload)
            setattr(state, "_layout_profile", bubble.get("layoutProfile"))
            setattr(state, "_auto_font_settings", bubble.get("autoFontSettings") or {})
            bubble_states.append(state)
        return bubble_states

    def apply_auto_font_settings(states, settings):
        for state in states:
            if not state.translated_text:
                continue
            state_settings = dict(settings or {})
            state_settings.update(getattr(state, "_auto_font_settings", {}) or {})
            min_size = int(state_settings.get("min_size", 12) or 12)
            max_size = int(state_settings.get("max_size", 80) or 80)
            padding_ratio = float(state_settings.get("padding_ratio", 1.0) or 1.0)
            x1, y1, x2, y2 = state.coords
            state.font_size = calculate_auto_font_size(
                state.translated_text,
                x2 - x1,
                y2 - y1,
                state.text_direction,
                state.font_family,
                min_size=min_size,
                max_size=max_size,
                padding_ratio=padding_ratio,
            )

    def handle_request(request):
        operation = request["operation"]
        payload = request.get("payload") or {}

        if operation == "detect":
            image = Image.open(payload["image_path"]).convert("RGB")
            result = get_bubble_detection_result_with_auto_directions(
                image,
                right_to_left=reading_order_to_right_to_left(payload),
            )
            return {
                "bubbleCoords": result.get("coords", []),
                "bubblePolygons": result.get("polygons", []),
                "autoDirections": result.get("auto_directions", []),
                "textlinesPerBubble": result.get("textlines_per_bubble", []),
                "rawMask": encode_mask_to_base64(result.get("raw_mask")),
            }

        if operation == "ocr":
            image = Image.open(payload["image_path"]).convert("RGB")
            results = recognize_ocr_results_in_bubbles(
                image,
                payload.get("bubble_coords", []),
                source_language=payload.get("source_language", "japanese"),
                ocr_engine=payload.get("ocr_engine", "manga_ocr"),
                textlines_per_bubble=payload.get("textlines_per_bubble", []),
                enable_hybrid_ocr=bool(payload.get("enable_hybrid_ocr", False)),
                secondary_ocr_engine=payload.get("secondary_ocr_engine"),
                hybrid_ocr_threshold=float(payload.get("hybrid_ocr_threshold", 0.2) or 0.2),
            )
            return {
                "originalTexts": extract_texts_from_ocr_results(results),
                "ocrResults": ocr_results_to_dicts(results),
            }

        if operation == "color":
            image = Image.open(payload["image_path"]).convert("RGB")
            color_results = extract_bubble_colors(
                image,
                payload.get("bubble_coords", []),
                payload.get("textlines_per_bubble", []),
                device="cpu",
            )
            return {
                "colors": build_color_payload(color_results),
            }

        if operation == "preprocess":
            image = Image.open(payload["image_path"]).convert("RGB")

            detect_started_at = perf_counter()
            detection = get_bubble_detection_result_with_auto_directions(
                image,
                right_to_left=reading_order_to_right_to_left(payload),
            )
            detect_seconds = perf_counter() - detect_started_at

            bubble_coords = detection.get("coords", [])

            ocr_started_at = perf_counter()
            ocr_results = recognize_ocr_results_in_bubbles(
                image,
                bubble_coords,
                source_language=payload.get("source_language", "japanese"),
                ocr_engine=payload.get("ocr_engine", "manga_ocr"),
                textlines_per_bubble=detection.get("textlines_per_bubble", []),
                enable_hybrid_ocr=bool(payload.get("enable_hybrid_ocr", False)),
                secondary_ocr_engine=payload.get("secondary_ocr_engine"),
                hybrid_ocr_threshold=float(payload.get("hybrid_ocr_threshold", 0.2) or 0.2),
            )
            ocr_seconds = perf_counter() - ocr_started_at

            color_started_at = perf_counter()
            if has_color_model():
                colors = build_color_payload(
                    extract_bubble_colors(
                        image,
                        bubble_coords,
                        detection.get("textlines_per_bubble", []),
                        device="cpu",
                    )
                )
            else:
                colors = [
                    {
                        "textColor": None,
                        "bgColor": None,
                        "autoFgColor": None,
                        "autoBgColor": None,
                        "colorConfidence": 0.0,
                    }
                    for _ in bubble_coords
                ]
            color_seconds = perf_counter() - color_started_at

            return {
                "bubbleCoords": bubble_coords,
                "bubblePolygons": detection.get("polygons", []),
                "autoDirections": detection.get("auto_directions", []),
                "textlinesPerBubble": detection.get("textlines_per_bubble", []),
                "rawMask": encode_mask_to_base64(detection.get("raw_mask")),
                "originalTexts": extract_texts_from_ocr_results(ocr_results),
                "ocrResults": ocr_results_to_dicts(ocr_results),
                "colors": colors,
                "timings": {
                    "detect": detect_seconds,
                    "ocr": ocr_seconds,
                    "color": color_seconds,
                    "total": detect_seconds + ocr_seconds + color_seconds,
                },
            }

        if operation == "inpaint":
            image = Image.open(payload["image_path"]).convert("RGB")
            requested_method = payload.get("method", "solid")
            actual_method = "solid" if requested_method == "solid" else "lama"
            lama_model = payload.get("lama_model", "lama_mpe")
            raw_mask = payload.get("raw_mask")
            precise_mask = decode_mask_from_base64(raw_mask)
            cleaned, clean_background = inpaint_bubbles(
                image,
                payload.get("bubble_coords", []),
                method=actual_method,
                bubble_polygons=payload.get("bubble_polygons") or None,
                precise_mask=precise_mask,
                mask_dilate_size=int(payload.get("mask_dilate_size", 0) or 0),
                mask_box_expand_ratio=int(payload.get("mask_box_expand_ratio", 0) or 0),
                lama_model=lama_model,
            )
            output_path = Path(payload["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            (clean_background or cleaned).save(output_path)
            return {
                "cleanImagePath": str(output_path),
            }

        if operation == "render":
            image = Image.open(payload["clean_image_path"]).convert("RGB")
            setattr(image, "_clean_image", image.copy())
            setattr(image, "_clean_background", image.copy())
            bubble_states = build_bubble_states(payload.get("bubbles", []))
            if bool(payload.get("auto_font_size", False)):
                apply_auto_font_settings(bubble_states, payload.get("auto_font_settings") or {})
            rendered = re_render_with_states(
                image,
                bubble_states,
                use_lama=False,
                auto_font_size=False,
            )
            output_path = Path(payload["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            rendered.save(output_path)
            return {
                "translatedImagePath": str(output_path),
                "bubbleStates": [state.to_dict() for state in bubble_states],
            }

        if operation == "render_single":
            image = Image.open(payload["clean_image_path"]).convert("RGB")
            setattr(image, "_clean_image", image.copy())
            setattr(image, "_clean_background", image.copy())
            bubble_states = []
            auto_font_settings = payload.get("auto_font_settings") or {}
            for bubble in payload.get("bubble_states", []):
                text_direction = normalize_layout_direction(
                    bubble.get("textDirection", bubble.get("direction", "vertical"))
                )
                auto_text_direction = normalize_layout_direction(
                    bubble.get("autoTextDirection", bubble.get("direction", text_direction)),
                    default=text_direction,
                )
                bubble_payload = dict(bubble)
                bubble_payload["textDirection"] = text_direction
                bubble_payload["autoTextDirection"] = auto_text_direction
                state = BubbleState.from_dict(bubble_payload)
                setattr(state, "_layout_profile", bubble.get("layoutProfile"))
                setattr(state, "_auto_font_settings", bubble.get("autoFontSettings") or {})
                raw_font_size = bubble.get("fontSize")
                if raw_font_size in (None, "") and state.translated_text:
                    state_settings = dict(auto_font_settings)
                    state_settings.update(getattr(state, "_auto_font_settings", {}) or {})
                    x1, y1, x2, y2 = state.coords
                    state.font_size = calculate_auto_font_size(
                        state.translated_text,
                        x2 - x1,
                        y2 - y1,
                        state.text_direction,
                        state.font_family,
                        min_size=int(state_settings.get("min_size", 12) or 12),
                        max_size=int(state_settings.get("max_size", 80) or 80),
                        padding_ratio=float(state_settings.get("padding_ratio", 1.0) or 1.0),
                    )
                bubble_states.append(state)
            rendered = render_single_bubble_unified(
                image,
                bubble_states,
                int(payload.get("bubble_index", 0)),
            )
            output_path = Path(payload["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            rendered.save(output_path)
            return {
                "translatedImagePath": str(output_path),
                "bubbleStates": [state.to_dict() for state in bubble_states],
            }

        raise KeyError(f"Unsupported Saber worker operation: {operation}")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = None
        try:
            request = json.loads(line)
            response = {
                "id": request.get("id"),
                "ok": True,
                "result": handle_request(request),
            }
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            response = {
                "id": request.get("id") if isinstance(request, dict) else None,
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)
    """
)


def _resolve_project_root():
    return find_project_root(__file__)


def _resolve_saber_root(project_root=None):
    base_root = Path(project_root) if project_root is not None else _resolve_project_root()
    config_path = base_root / "config" / "defaults.json"
    if config_path.exists():
        settings = load_settings(base_root)
        configured_root = resolve_path_value((settings.get("paths") or {}).get("saber_root"), project_root=base_root)
        if configured_root:
            return Path(configured_root)
        return base_root.parent / "Saber-Translator"
    return base_root / "Saber-Translator"


def _resolve_saber_python_path(project_root=None):
    env_python = os.environ.get("TRANSLATE_MANGA_CLI_SABER_PYTHON") or os.environ.get("TRANSLATE_READER_SABER_PYTHON")
    if env_python:
        return env_python

    base_root = Path(project_root) if project_root is not None else _resolve_project_root()
    settings = load_settings(base_root)
    configured_python = resolve_path_value((settings.get("paths") or {}).get("saber_python"), project_root=base_root)
    if configured_python:
        return configured_python
    candidates = [
        base_root / ".venv310" / "Scripts" / "python.exe",
        base_root / ".venv310" / "bin" / "python",
        base_root / ".venv" / "Scripts" / "python.exe",
        base_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return sys.executable


def _build_saber_subprocess_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def has_saber_48px_color_model(project_root=None):
    saber_root = _resolve_saber_root(Path(project_root) if project_root is not None else _resolve_project_root())
    model_dir = saber_root / "models" / "ocr_48px"
    return (model_dir / "ocr_ar_48px.ckpt").exists() and (model_dir / "alphabet-all-v7.txt").exists()


def _extract_json_payload(stdout):
    content = (stdout or "").strip()
    if not content:
        raise ValueError("Saber task returned empty stdout")

    for line in reversed(content.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        if candidate[0] not in "{[":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    for index, char in reversed(list(enumerate(content))):
        if char not in "{[":
            continue
        try:
            return json.loads(content[index:])
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Unable to extract JSON payload from Saber stdout: {content[:400]}")


class SaberWorkerSession:
    def __init__(self, project_root=None):
        self._project_root = Path(project_root) if project_root is not None else _resolve_project_root()
        self._saber_root = _resolve_saber_root(self._project_root)
        if not self._saber_root.exists():
            raise FileNotFoundError(f"Saber-Translator not found: {self._saber_root}")
        self._python_path = _resolve_saber_python_path(self._project_root)
        self._process = None
        self._request_id = 0
        self._lock = Lock()
        self._stderr_lines = deque(maxlen=200)
        self._stdout_logs = deque(maxlen=200)
        self._stderr_thread = None
        self._disabled_reason = None

    def _ensure_started(self):
        if self._process is not None and self._process.poll() is None:
            return

        self._process = subprocess.Popen(
            [self._python_path, "-u", "-c", _WORKER_SCRIPT],
            cwd=str(self._saber_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_saber_subprocess_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        if self._process.stderr is not None:
            self._stderr_thread = Thread(target=self._drain_stderr, daemon=True)
            self._stderr_thread.start()

    def _drain_stderr(self):
        if self._process is None or self._process.stderr is None:
            return

        while True:
            line = self._process.stderr.readline()
            if line == "":
                break
            self._stderr_lines.append(line.rstrip())

    def execute(self, operation, payload):
        with self._lock:
            self._ensure_started()
            if self._process is None or self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("Saber worker failed to start")

            self._request_id += 1
            request_id = self._request_id
            self._process.stdin.write(
                json.dumps(
                    {
                        "id": request_id,
                        "operation": operation,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self._process.stdin.flush()

            while True:
                line = self._process.stdout.readline()
                if line == "":
                    return_code = self._process.poll()
                    stderr_tail = "\n".join(self._stderr_lines)
                    raise RuntimeError(
                        stderr_tail or f"Saber worker exited unexpectedly while running: {operation} (code={return_code})"
                    )

                candidate = line.strip()
                if not candidate:
                    continue

                try:
                    response = json.loads(candidate)
                except json.JSONDecodeError:
                    self._stdout_logs.append(candidate)
                    continue

                if response.get("id") != request_id:
                    self._stdout_logs.append(candidate)
                    continue

                if not response.get("ok", False):
                    stderr_tail = "\n".join(self._stderr_lines)
                    error_text = response.get("error") or stderr_tail or f"Saber worker failed: {operation}"
                    raise RuntimeError(error_text)

                return response.get("result")

    def close(self):
        process = self._process
        if process is None:
            return

        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        for stream_name in ("stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass

        self._process = None

    def disable(self, reason):
        self._disabled_reason = str(reason).strip() or "unknown"

    def is_disabled(self):
        return bool(self._disabled_reason)

    @property
    def disabled_reason(self):
        return self._disabled_reason

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def run_saber_task(operation, payload, session=None):
    if session is not None and not session.is_disabled():
        timeout_seconds = _resolve_session_timeout_seconds(operation)
        if timeout_seconds > 0:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(session.execute, operation, payload)
            try:
                return future.result(timeout=timeout_seconds)
            except FutureTimeoutError:
                reason = f"{operation} timed out after {timeout_seconds:.1f}s"
                session.disable(reason)
                session.close()
                try:
                    future.result(timeout=1)
                except Exception:
                    pass
            except Exception as error:
                reason = f"{operation} failed in worker session: {error}"
                session.disable(reason)
                session.close()
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            return session.execute(operation, payload)

    return _run_saber_subprocess_task(operation, payload)


def _resolve_session_timeout_seconds(operation):
    runtime = resolve_runtime_config()
    operation_timeouts = runtime.get("saber_operation_timeout_seconds") or {}
    if operation in operation_timeouts:
        return max(0.0, float(operation_timeouts[operation]))
    return max(0.0, float(runtime["saber_session_timeout_seconds"]))


def _resolve_subprocess_timeout_seconds(operation):
    runtime = resolve_runtime_config()
    operation_timeouts = runtime.get("saber_operation_timeout_seconds") or {}
    if operation in operation_timeouts:
        return max(0.0, float(operation_timeouts[operation]))
    return max(0.0, float(runtime["saber_subprocess_timeout_seconds"]))


def _run_saber_subprocess_task(operation, payload):
    project_root = _resolve_project_root()
    saber_root = _resolve_saber_root(project_root)
    if not saber_root.exists():
        raise FileNotFoundError(f"Saber-Translator not found: {saber_root}")

    script = "import sys\nsys.argv = ['-c', sys.stdin.read()]\n" + _SCRIPTS[operation]
    timeout_seconds = _resolve_subprocess_timeout_seconds(operation)
    try:
        completed = subprocess.run(
            [_resolve_saber_python_path(project_root), "-c", script],
            cwd=str(saber_root),
            capture_output=True,
            env=_build_saber_subprocess_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            input=json.dumps(payload, ensure_ascii=False),
            timeout=timeout_seconds if timeout_seconds > 0 else None,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Saber task timed out: {operation} ({error.timeout}s)") from error
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        raise RuntimeError(stderr or stdout or f"Saber task failed: {operation}")
    return _extract_json_payload(completed.stdout)
