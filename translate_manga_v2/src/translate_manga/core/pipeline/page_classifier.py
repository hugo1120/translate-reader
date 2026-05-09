EARLY_FRONTMATTER_PAGE_LIMIT = 16


def classify_preprocessed_page(page_index, total_pages, image_size, preprocessed_payload, skip_frontmatter=True):
    bubble_coords = preprocessed_payload.get("bubbleCoords", []) or []
    original_texts = preprocessed_payload.get("originalTexts", []) or []
    texts = [str(text or "").strip() for text in original_texts if str(text or "").strip()]

    if not bubble_coords or not texts:
        return {
            "page_type": "blank",
            "should_translate": False,
            "skip_reason": "blank",
            "metrics": {
                "bubble_count": len(bubble_coords),
                "text_count": len(texts),
                "total_chars": sum(len(text) for text in texts),
            },
        }

    page_width, page_height = image_size or (0, 0)
    page_area = max(1, int(page_width or 1) * int(page_height or 1))
    total_chars = sum(len(text) for text in texts)
    bubble_count = len(bubble_coords)

    area_ratios = []
    tall_narrow_count = 0
    for coords in bubble_coords:
        if not isinstance(coords, (list, tuple)) or len(coords) < 4:
            continue
        x1, y1, x2, y2 = [int(value) for value in coords[:4]]
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        area_ratios.append((width * height) / page_area)
        if width > 0 and height >= width * 1.5:
            tall_narrow_count += 1

    max_area_ratio = max(area_ratios) if area_ratios else 0.0
    tall_narrow_ratio = tall_narrow_count / bubble_count if bubble_count else 0.0
    avg_chars = total_chars / len(texts) if texts else 0.0
    short_text_count = sum(1 for text in texts if len(text) <= 6)
    short_text_ratio = short_text_count / len(texts) if texts else 0.0
    early_page = int(page_index or 0) <= EARLY_FRONTMATTER_PAGE_LIMIT

    looks_like_cover = (
        int(page_index or 0) <= 2
        and bubble_count <= 3
        and total_chars <= 16
        and max_area_ratio < 0.03
    )
    looks_like_toc_or_preface = (
        bubble_count >= 6
        and tall_narrow_ratio >= 0.6
        and max_area_ratio < 0.03
        and avg_chars >= 2.0
        and short_text_ratio >= 0.75
        and total_chars <= 80
    )

    if skip_frontmatter and early_page and (looks_like_cover or looks_like_toc_or_preface):
        return {
            "page_type": "frontmatter",
            "should_translate": False,
            "skip_reason": "frontmatter",
            "metrics": {
                "bubble_count": bubble_count,
                "text_count": len(texts),
                "total_chars": total_chars,
                "max_area_ratio": max_area_ratio,
                "tall_narrow_ratio": tall_narrow_ratio,
                "short_text_ratio": short_text_ratio,
            },
        }

    return {
        "page_type": "story",
        "should_translate": True,
        "skip_reason": None,
        "metrics": {
            "bubble_count": bubble_count,
            "text_count": len(texts),
            "total_chars": total_chars,
            "max_area_ratio": max_area_ratio,
            "tall_narrow_ratio": tall_narrow_ratio,
            "short_text_ratio": short_text_ratio,
            "total_pages": int(total_pages or 0),
        },
    }
