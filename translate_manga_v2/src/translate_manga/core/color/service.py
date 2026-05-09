from PIL import Image, ImageDraw, ImageFilter, ImageStat

from translate_manga.integrations.saber_loader import has_saber_48px_color_model, run_saber_task


DEFAULT_BACKGROUND_METRICS = {
    "grayStdDev": 0.0,
    "edgeDensity": 0.0,
    "darkPixelRatio": 0.0,
}


def _empty_color_result():
    return {
        "textColor": None,
        "bgColor": None,
        "autoFgColor": None,
        "autoBgColor": None,
        "colorConfidence": 0.0,
        **DEFAULT_BACKGROUND_METRICS,
    }


def _build_background_mask(size, textlines, offset_x, offset_y):
    mask = Image.new("L", size, 255)
    draw = ImageDraw.Draw(mask)
    for line in textlines or []:
        polygon = line.get("polygon") or []
        points = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            points.append((int(point[0]) - offset_x, int(point[1]) - offset_y))
        if len(points) >= 3:
            draw.polygon(points, fill=0)
    return mask


def _measure_background_metrics(image, coords, textlines):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return dict(DEFAULT_BACKGROUND_METRICS)
    x1, y1, x2, y2 = [int(value) for value in coords[:4]]
    if x2 <= x1 or y2 <= y1:
        return dict(DEFAULT_BACKGROUND_METRICS)

    crop = image.crop((x1, y1, x2, y2)).convert("L")
    mask = _build_background_mask(crop.size, textlines, x1, y1)
    gray_values = list(crop.tobytes())
    mask_values = list(mask.tobytes())
    active_gray_values = [value for index, value in enumerate(gray_values) if mask_values[index] > 0]
    if not active_gray_values:
        return dict(DEFAULT_BACKGROUND_METRICS)

    stat = ImageStat.Stat(crop, mask=mask)
    edges = crop.filter(ImageFilter.FIND_EDGES)
    edge_values = list(edges.tobytes())
    width, height = crop.size
    active_edge_values = [
        value
        for index, value in enumerate(edge_values)
        if mask_values[index] > 0
        and index % width not in {0, width - 1}
        and index // width not in {0, height - 1}
    ]
    return {
        "grayStdDev": float(stat.stddev[0] if stat.stddev else 0.0),
        "edgeDensity": sum(1 for value in active_edge_values if value >= 24) / max(1, len(active_edge_values)),
        "darkPixelRatio": sum(1 for value in active_gray_values if value <= 96) / len(active_gray_values),
    }


def enrich_bubble_colors_with_background_metrics(result, image_path, bubble_coords, textlines_per_bubble):
    colors = result.get("colors", []) if isinstance(result, dict) else []
    if not isinstance(colors, list):
        return result

    try:
        with Image.open(image_path) as image:
            enriched_colors = []
            for index, color in enumerate(colors):
                normalized_color = dict(color) if isinstance(color, dict) else {}
                coords = bubble_coords[index] if index < len(bubble_coords) else []
                textlines = textlines_per_bubble[index] if index < len(textlines_per_bubble) else []
                normalized_color.update(_measure_background_metrics(image, coords, textlines))
                enriched_colors.append(normalized_color)
    except (FileNotFoundError, OSError, ValueError):
        enriched_colors = []
        for color in colors:
            normalized_color = dict(color) if isinstance(color, dict) else {}
            for key, value in DEFAULT_BACKGROUND_METRICS.items():
                normalized_color.setdefault(key, value)
            enriched_colors.append(normalized_color)

    enriched_result = dict(result)
    enriched_result["colors"] = enriched_colors
    return enriched_result


def extract_bubble_colors(image_path, bubble_coords, textlines_per_bubble):
    if not has_saber_48px_color_model():
        return {
            "colors": [
                _empty_color_result()
                for _ in bubble_coords
            ]
        }
    result = run_saber_task(
        "color",
        {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "textlines_per_bubble": textlines_per_bubble,
        },
    )
    return enrich_bubble_colors_with_background_metrics(result, image_path, bubble_coords, textlines_per_bubble)
