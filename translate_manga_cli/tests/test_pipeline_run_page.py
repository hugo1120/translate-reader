from io import BytesIO

from PIL import Image

from tests.test_constants import TEST_BASE_URL
from src.storage.cache_store import CacheStore


def _png_bytes(color):
    image = Image.new("RGB", (8, 8), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _import_single_page(client):
    response = client.post(
        "/api/library/import",
        data={"files": [(_png_bytes("white"), "001.png")]},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    return response.get_json()["pages"][0]["id"]


def test_run_page_pipeline_persists_result(client, monkeypatch):
    page_id = _import_single_page(client)

    monkeypatch.setattr(
        "src.app.routes.pipeline.run_page_pipeline",
        lambda app, page_id, source_path, model="mimo-v2.5-pro", base_url=TEST_BASE_URL, api_key="": {
            "pageId": page_id,
            "translatedTexts": ["白色的夜晚"],
            "translatedImagePath": "translated.png",
        },
        raising=False,
    )

    response = client.post("/api/pipeline/run-page", json={"pageId": page_id})
    data = response.get_json()

    assert response.status_code == 200
    assert data["translatedTexts"] == ["白色的夜晚"]
    assert data["translatedImagePath"] == "translated.png"


def test_page_result_endpoint_returns_cached_payload(client, monkeypatch):
    page_id = _import_single_page(client)

    monkeypatch.setattr(
        "src.app.routes.pipeline.run_page_pipeline",
        lambda app, page_id, source_path, model="mimo-v2.5-pro", base_url=TEST_BASE_URL, api_key="": {
            "pageId": page_id,
            "translatedTexts": [],
            "translatedImagePath": "translated.png",
        },
        raising=False,
    )

    client.post("/api/pipeline/run-page", json={"pageId": page_id})
    result = client.get(f"/api/page/{page_id}/result").get_json()["result"]
    assert result["translatedImagePath"] == "translated.png"


def test_redo_inpaint_route_rebuilds_clean_image_from_cached_result(client, monkeypatch):
    page_id = _import_single_page(client)
    cache_store = CacheStore(client.application)
    cache_store.save_result(
        page_id,
        {
            "pageId": page_id,
            "bubbleCoords": [[10, 20, 60, 90]],
            "bubblePolygons": [[[10, 20], [60, 20], [60, 90], [10, 90]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "originalTexts": ["白い夜"],
            "ocrResults": [{"text": "白い夜", "engine": "manga_ocr"}],
            "translatedTexts": ["白色的夜晚"],
            "bubbles": [
                {
                    "coords": [10, 20, 60, 90],
                    "polygon": [[10, 20], [60, 20], [60, 90], [10, 90]],
                    "direction": "vertical",
                    "textlines": [],
                    "originalText": "白い夜",
                    "translatedText": "白色的夜晚",
                    "ocrResult": {"text": "白い夜", "engine": "manga_ocr"},
                }
            ],
            "cleanImagePath": "clean-old.png",
            "translatedImagePath": "translated-old.png",
        },
    )

    monkeypatch.setattr(
        "src.app.routes.pipeline.redo_page_inpaint",
        lambda app, page_id, source_path, cached_result: {
            **cached_result,
            "cleanImagePath": "clean-new.png",
        },
        raising=False,
    )

    response = client.post("/api/pipeline/redo-inpaint", json={"pageId": page_id})
    data = response.get_json()
    cached = client.get(f"/api/page/{page_id}/result").get_json()["result"]

    assert response.status_code == 200
    assert data["cleanImagePath"] == "clean-new.png"
    assert cached["cleanImagePath"] == "clean-new.png"


def test_redo_render_route_rebuilds_translated_image_from_cached_result(client, monkeypatch):
    page_id = _import_single_page(client)
    cache_store = CacheStore(client.application)
    cache_store.save_result(
        page_id,
        {
            "pageId": page_id,
            "bubbleCoords": [[10, 20, 60, 90]],
            "bubblePolygons": [[[10, 20], [60, 20], [60, 90], [10, 90]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "originalTexts": ["白い夜"],
            "ocrResults": [{"text": "白い夜", "engine": "manga_ocr"}],
            "translatedTexts": ["白色的夜晚"],
            "bubbles": [
                {
                    "coords": [10, 20, 60, 90],
                    "polygon": [[10, 20], [60, 20], [60, 90], [10, 90]],
                    "direction": "vertical",
                    "textlines": [],
                    "originalText": "白い夜",
                    "translatedText": "白色的夜晚",
                    "ocrResult": {"text": "白い夜", "engine": "manga_ocr"},
                }
            ],
            "cleanImagePath": "clean-old.png",
            "translatedImagePath": "translated-old.png",
        },
    )

    monkeypatch.setattr(
        "src.app.routes.pipeline.redo_page_render",
        lambda app, page_id, source_path, cached_result: {
            **cached_result,
            "translatedImagePath": f"D:/cache/pages/{page_id}/{page_id}.translated.png",
        },
        raising=False,
    )

    response = client.post("/api/pipeline/redo-render", json={"pageId": page_id})
    data = response.get_json()
    detail = client.get(f"/api/library/page/{page_id}").get_json()["page"]

    assert response.status_code == 200
    assert data["translatedImagePath"].endswith(f"/{page_id}.translated.png")
    assert detail["translatedUrl"] == f"/data/cache/pages/{page_id}/{page_id}.translated.png"


def test_update_bubble_route_persists_manual_edit(client, monkeypatch):
    page_id = _import_single_page(client)
    cache_store = CacheStore(client.application)
    cache_store.save_result(
        page_id,
        {
            "pageId": page_id,
            "bubbleStates": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文"}],
            "bubbles": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文"}],
            "translatedTexts": ["旧译文"],
            "bubbleCoords": [[10, 20, 60, 90]],
            "manualEdited": False,
        },
    )

    monkeypatch.setattr(
        "src.app.routes.pipeline.update_bubble_state",
        lambda result, bubble_index, patch: {
            **result,
            "bubbleStates": [{"coords": [12, 24, 64, 96], "translatedText": patch["translatedText"]}],
            "bubbles": [{"coords": [12, 24, 64, 96], "translatedText": patch["translatedText"]}],
            "translatedTexts": [patch["translatedText"]],
            "bubbleCoords": [[12, 24, 64, 96]],
            "manualEdited": True,
        },
        raising=False,
    )

    response = client.post(
        "/api/pipeline/update-bubble",
        json={"pageId": page_id, "bubbleIndex": 0, "patch": {"translatedText": "新译文"}},
    )
    data = response.get_json()
    cached = client.get(f"/api/page/{page_id}/result").get_json()["result"]

    assert response.status_code == 200
    assert data["manualEdited"] is True
    assert data["bubbleStates"][0]["translatedText"] == "新译文"
    assert cached["translatedTexts"] == ["新译文"]
    assert data["timings"]["saveBubble"] >= 0


def test_rerender_bubble_route_updates_translated_image_and_bubble_states(client, monkeypatch):
    page_id = _import_single_page(client)
    cache_store = CacheStore(client.application)
    cache_store.save_result(
        page_id,
        {
            "pageId": page_id,
            "cleanImagePath": "clean.png",
            "translatedImagePath": "translated-old.png",
            "bubbleStates": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文"}],
            "bubbles": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文"}],
            "manualEdited": False,
        },
    )

    monkeypatch.setattr(
        "src.app.routes.pipeline.rerender_single_bubble",
        lambda clean_image_path, translated_image_path, bubble_states, bubble_index: {
            "translatedImagePath": f"D:/cache/pages/{page_id}/{page_id}.translated.png",
            "bubbleStates": [{**bubble_states[0], "translatedText": "新译文"}],
        },
        raising=False,
    )

    response = client.post(
        "/api/pipeline/rerender-bubble",
        json={"pageId": page_id, "bubbleIndex": 0},
    )
    data = response.get_json()
    detail = client.get(f"/api/library/page/{page_id}").get_json()["page"]

    assert response.status_code == 200
    assert data["manualEdited"] is True
    assert data["bubbleStates"][0]["translatedText"] == "新译文"
    assert detail["translatedUrl"] == f"/data/cache/pages/{page_id}/{page_id}.translated.png"
    assert data["timings"]["rerenderBubble"] >= 0


def test_rerender_bubble_route_syncs_translation_payload(client, monkeypatch):
    page_id = _import_single_page(client)
    cache_store = CacheStore(client.application)
    cache_store.save_result(
        page_id,
        {
            "pageId": page_id,
            "cleanImagePath": "clean.png",
            "translatedImagePath": "translated-old.png",
            "bubbleStates": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文", "originalText": "原文"}],
            "bubbles": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文", "originalText": "原文"}],
            "translatedTexts": ["旧译文"],
            "originalTexts": ["原文"],
            "translation": {
                "translatedTexts": ["旧译文"],
                "rounds": [
                    {"name": "draft", "translatedTexts": ["草稿"], "usage": {}},
                    {"name": "contextual", "translatedTexts": ["旧译文"], "usage": {}},
                    {"name": "final", "translatedTexts": ["旧译文"], "usage": {}},
                ],
            },
            "manualEdited": False,
        },
    )

    monkeypatch.setattr(
        "src.app.routes.pipeline.rerender_single_bubble",
        lambda clean_image_path, translated_image_path, bubble_states, bubble_index: {
            "translatedImagePath": f"D:/cache/pages/{page_id}/{page_id}.translated.png",
            "bubbleStates": [{**bubble_states[0], "translatedText": "新译文"}],
        },
        raising=False,
    )

    response = client.post(
        "/api/pipeline/rerender-bubble",
        json={"pageId": page_id, "bubbleIndex": 0},
    )
    data = response.get_json()
    cached = client.get(f"/api/page/{page_id}/result").get_json()["result"]

    assert response.status_code == 200
    assert data["translation"]["translatedTexts"] == ["新译文"]
    assert data["translation"]["rounds"][1]["translatedTexts"] == ["新译文"]
    assert data["translation"]["rounds"][2]["translatedTexts"] == ["新译文"]
    assert cached["translation"]["translatedTexts"] == ["新译文"]
