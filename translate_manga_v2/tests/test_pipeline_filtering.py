from translate_manga.core.pipeline.filtering import filter_detection_payload, filter_ocr_payload


def test_filter_detection_payload_keeps_small_valid_bubble_but_removes_tiny_noise():
    payload = {
        "bubbleCoords": [[385, 83, 400, 119], [276, 92, 281, 101]],
        "bubblePolygons": [
            [[385, 83], [400, 83], [400, 119], [385, 119]],
            [[276, 92], [281, 92], [281, 101], [276, 101]],
        ],
        "autoDirections": ["vertical", "vertical"],
        "textlinesPerBubble": [[], []],
    }

    filtered = filter_detection_payload(payload, image_size=(794, 1200))

    assert filtered["bubbleCoords"] == [[385, 83, 400, 119]]
    assert filtered["bubblePolygons"] == [[[385, 83], [400, 83], [400, 119], [385, 119]]]
    assert filtered["autoDirections"] == ["vertical"]


def test_filter_ocr_payload_removes_page_number_near_page_edge():
    payload = {
        "bubbleCoords": [[700, 76, 742, 184], [49, 1135, 70, 1155]],
        "bubblePolygons": [
            [[700, 76], [742, 76], [742, 184], [700, 184]],
            [[49, 1135], [70, 1135], [70, 1155], [49, 1155]],
        ],
        "autoDirections": ["vertical", "vertical"],
        "textlinesPerBubble": [[], []],
        "originalTexts": ["だれと話してたんだ？", "１３"],
        "ocrResults": [
            {"text": "だれと話してたんだ？", "engine": "manga_ocr"},
            {"text": "１３", "engine": "manga_ocr"},
        ],
    }

    filtered = filter_ocr_payload(payload, image_size=(794, 1200))

    assert filtered["bubbleCoords"] == [[700, 76, 742, 184]]
    assert filtered["originalTexts"] == ["だれと話してたんだ？"]
    assert filtered["ocrResults"] == [{"text": "だれと話してたんだ？", "engine": "manga_ocr"}]
