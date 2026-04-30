from flask import Blueprint, current_app, jsonify, request
from time import perf_counter

from src.core.detection.service import detect_page
from src.core.editing.service import rerender_single_bubble, update_bubble_state
from src.core.ocr.service import ocr_page
from src.core.pipeline.filtering import filter_detection_payload, filter_ocr_payload, load_image_size
from src.core.pipeline.service import redo_page_inpaint, redo_page_render, run_page_pipeline
from src.core.translate.openai_compatible import OpenAICompatibleTranslator
from src.config.settings import resolve_translation_config
from src.storage.cache_store import CacheStore
from src.storage.library_store import LibraryStore


pipeline_bp = Blueprint("pipeline", __name__)


def _resolve_page_path(page_id):
    page = next((item for item in LibraryStore(current_app).list_pages() if item["id"] == page_id), None)
    if page is None:
        raise ValueError(f"page not found: {page_id}")
    return page["sourcePath"]


def _load_cached_result(page_id):
    payload = CacheStore(current_app).load_result(page_id)
    if payload is None:
        return None
    return payload


def _attach_timing(payload, key, elapsed_seconds):
    updated = dict(payload)
    timings = dict(updated.get("timings") or {})
    timings[key] = elapsed_seconds
    updated["timings"] = timings
    return updated


def _resolve_translation_options(data):
    configured = resolve_translation_config()
    return {
        "model": data.get("model") or configured["model"],
        "base_url": data.get("baseUrl") or configured["base_url"],
        "api_key": data.get("apiKey") or configured["api_key"],
    }


def _call_ocr_page(image_path, bubble_coords, textlines_per_bubble):
    try:
        return ocr_page(image_path, bubble_coords, textlines_per_bubble)
    except TypeError as error:
        if "positional arguments" not in str(error) and "positional argument" not in str(error):
            raise
        return ocr_page(image_path, bubble_coords)


@pipeline_bp.post("/api/pipeline/translate")
def translate_texts():
    data = request.get_json() or {}
    texts = data.get("texts", [])
    options = _resolve_translation_options(data)
    translator = OpenAICompatibleTranslator()
    translated = translator.translate_texts(
        texts=texts,
        model=options["model"],
        base_url=options["base_url"],
        api_key=options["api_key"],
    )
    return jsonify({"translatedTexts": translated})


@pipeline_bp.post("/api/pipeline/detect")
def detect_route():
    data = request.get_json() or {}
    image_path = _resolve_page_path(data["pageId"])
    result = filter_detection_payload(detect_page(image_path), image_size=load_image_size(image_path))
    return jsonify(result)


@pipeline_bp.post("/api/pipeline/ocr")
def ocr_route():
    data = request.get_json() or {}
    image_path = _resolve_page_path(data["pageId"])
    image_size = load_image_size(image_path)
    detection = filter_detection_payload(
        {
            "bubbleCoords": data.get("bubbleCoords", []) or [],
            "bubblePolygons": data.get("bubblePolygons", []) or [],
            "autoDirections": data.get("autoDirections", []) or [],
            "textlinesPerBubble": data.get("textlinesPerBubble", []) or [],
        },
        image_size=image_size,
    )
    ocr = _call_ocr_page(image_path, detection["bubbleCoords"], detection["textlinesPerBubble"])
    result = filter_ocr_payload({**detection, **ocr}, image_size=image_size)
    return jsonify(result)


@pipeline_bp.post("/api/pipeline/run-page")
def run_page():
    data = request.get_json() or {}
    page_id = data["pageId"]
    options = _resolve_translation_options(data)
    payload = run_page_pipeline(
        app=current_app,
        page_id=page_id,
        source_path=_resolve_page_path(page_id),
        model=options["model"],
        base_url=options["base_url"],
        api_key=options["api_key"],
    )
    CacheStore(current_app).save_result(page_id, payload)
    translated_path = payload.get("translatedImagePath")
    if translated_path:
        LibraryStore(current_app).update_translated_path(page_id, translated_path)
    return jsonify(payload)


@pipeline_bp.post("/api/pipeline/redo-inpaint")
def redo_inpaint():
    data = request.get_json() or {}
    page_id = data["pageId"]
    cached_result = _load_cached_result(page_id)
    if cached_result is None:
        return jsonify({"error": "page result not found"}), 404

    started_at = perf_counter()
    payload = redo_page_inpaint(
        current_app,
        page_id,
        _resolve_page_path(page_id),
        cached_result,
    )
    payload = _attach_timing(payload, "redoInpaint", perf_counter() - started_at)
    CacheStore(current_app).save_result(page_id, payload)
    return jsonify(payload)


@pipeline_bp.post("/api/pipeline/redo-render")
def redo_render():
    data = request.get_json() or {}
    page_id = data["pageId"]
    cached_result = _load_cached_result(page_id)
    if cached_result is None:
        return jsonify({"error": "page result not found"}), 404

    started_at = perf_counter()
    payload = redo_page_render(
        current_app,
        page_id,
        _resolve_page_path(page_id),
        cached_result,
    )
    payload = _attach_timing(payload, "redoRender", perf_counter() - started_at)
    CacheStore(current_app).save_result(page_id, payload)
    translated_path = payload.get("translatedImagePath")
    if translated_path:
        LibraryStore(current_app).update_translated_path(page_id, translated_path)
    return jsonify(payload)


@pipeline_bp.post("/api/pipeline/update-bubble")
def update_bubble():
    data = request.get_json() or {}
    page_id = data["pageId"]
    cached_result = _load_cached_result(page_id)
    if cached_result is None:
        return jsonify({"error": "page result not found"}), 404

    started_at = perf_counter()
    payload = update_bubble_state(
        cached_result,
        data["bubbleIndex"],
        data.get("patch", {}) or {},
    )
    payload = _attach_timing(payload, "saveBubble", perf_counter() - started_at)
    CacheStore(current_app).save_result(page_id, payload)
    return jsonify(payload)


@pipeline_bp.post("/api/pipeline/rerender-bubble")
def rerender_bubble():
    data = request.get_json() or {}
    page_id = data["pageId"]
    cached_result = _load_cached_result(page_id)
    if cached_result is None:
        return jsonify({"error": "page result not found"}), 404

    started_at = perf_counter()
    rendered = rerender_single_bubble(
        cached_result["cleanImagePath"],
        cached_result["translatedImagePath"],
        cached_result.get("bubbleStates") or cached_result.get("bubbles") or [],
        data["bubbleIndex"],
    )
    bubble_states = rendered.get("bubbleStates") or cached_result.get("bubbleStates") or cached_result.get("bubbles") or []

    payload = dict(cached_result)
    payload["translatedImagePath"] = rendered["translatedImagePath"]
    payload["bubbleStates"] = bubble_states
    payload["bubbles"] = bubble_states
    payload["manualEdited"] = True
    if bubble_states:
        payload["bubbleCoords"] = [item.get("coords") for item in bubble_states]
        payload["translatedTexts"] = [item.get("translatedText", "") for item in bubble_states]
        if "originalTexts" in payload:
            payload["originalTexts"] = [item.get("originalText", "") for item in bubble_states]

    payload = _attach_timing(payload, "rerenderBubble", perf_counter() - started_at)
    CacheStore(current_app).save_result(page_id, payload)
    translated_path = payload.get("translatedImagePath")
    if translated_path:
        LibraryStore(current_app).update_translated_path(page_id, translated_path)
    return jsonify(payload)


@pipeline_bp.get("/api/page/<page_id>/result")
def get_page_result(page_id):
    payload = CacheStore(current_app).load_result(page_id)
    return jsonify({"result": payload})
