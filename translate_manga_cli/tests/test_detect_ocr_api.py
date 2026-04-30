from io import BytesIO

from PIL import Image


def _png_bytes(color, size=(8, 8)):
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _import_single_page(client, size=(8, 8)):
    response = client.post(
        "/api/library/import",
        data={"files": [(_png_bytes("white", size=size), "001.png")]},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    return response.get_json()["pages"][0]["id"]


def test_detect_route_returns_bubbles(client, monkeypatch):
    page_id = _import_single_page(client)

    monkeypatch.setattr(
        "src.app.routes.pipeline.detect_page",
        lambda image_path: {
            "bubbleCoords": [[10, 20, 60, 90]],
            "bubblePolygons": [[[10, 20], [60, 20], [60, 90], [10, 90]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
        },
        raising=False,
    )

    response = client.post("/api/pipeline/detect", json={"pageId": page_id})
    assert response.status_code == 200
    assert response.get_json()["bubbleCoords"][0] == [10, 20, 60, 90]


def test_ocr_route_returns_texts(client, monkeypatch):
    page_id = _import_single_page(client)

    monkeypatch.setattr(
        "src.app.routes.pipeline.ocr_page",
        lambda image_path, bubble_coords: {
            "originalTexts": ["さあ…"],
            "ocrResults": [{"text": "さあ…", "engine": "manga_ocr"}],
        },
        raising=False,
    )

    response = client.post(
        "/api/pipeline/ocr",
        json={"pageId": page_id, "bubbleCoords": [[10, 20, 60, 90]]},
    )
    assert response.status_code == 200
    assert response.get_json()["originalTexts"] == ["さあ…"]


def test_detect_route_filters_tiny_noise_boxes(client, monkeypatch):
    page_id = _import_single_page(client, size=(200, 300))

    monkeypatch.setattr(
        "src.app.routes.pipeline.detect_page",
        lambda image_path: {
            "bubbleCoords": [[40, 50, 55, 86], [10, 10, 15, 16]],
            "bubblePolygons": [
                [[40, 50], [55, 50], [55, 86], [40, 86]],
                [[10, 10], [15, 10], [15, 16], [10, 16]],
            ],
            "autoDirections": ["vertical", "vertical"],
            "textlinesPerBubble": [[], []],
        },
        raising=False,
    )

    response = client.post("/api/pipeline/detect", json={"pageId": page_id})
    data = response.get_json()

    assert response.status_code == 200
    assert data["bubbleCoords"] == [[40, 50, 55, 86]]
    assert data["bubblePolygons"] == [[[40, 50], [55, 50], [55, 86], [40, 86]]]


def test_ocr_route_filters_page_numbers_and_returns_filtered_detection(client, monkeypatch):
    page_id = _import_single_page(client, size=(200, 300))

    monkeypatch.setattr(
        "src.app.routes.pipeline.ocr_page",
        lambda image_path, bubble_coords: {
            "originalTexts": ["ん？", "１３"],
            "ocrResults": [
                {"text": "ん？", "engine": "manga_ocr"},
                {"text": "１３", "engine": "manga_ocr"},
            ],
        },
        raising=False,
    )

    response = client.post(
        "/api/pipeline/ocr",
        json={
            "pageId": page_id,
            "bubbleCoords": [[40, 50, 55, 86], [5, 270, 25, 290]],
            "bubblePolygons": [
                [[40, 50], [55, 50], [55, 86], [40, 86]],
                [[5, 270], [25, 270], [25, 290], [5, 290]],
            ],
            "autoDirections": ["vertical", "vertical"],
            "textlinesPerBubble": [[], []],
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["bubbleCoords"] == [[40, 50, 55, 86]]
    assert data["originalTexts"] == ["ん？"]
    assert data["ocrResults"] == [{"text": "ん？", "engine": "manga_ocr"}]
