from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from src.storage.cache_store import CacheStore
from src.storage.library_store import LibraryStore


library_bp = Blueprint("library", __name__)


@library_bp.post("/api/library/import")
def import_library():
    store = LibraryStore(current_app)
    pages = store.import_files(request.files.getlist("files"))
    return jsonify({"imported": len(pages), "pages": pages})


@library_bp.get("/api/library/pages")
def list_pages():
    store = LibraryStore(current_app)
    cache_store = CacheStore(current_app)
    pages = []
    for page in store.list_pages():
        pages.append(
            {
                "id": page["id"],
                "fileName": page["fileName"],
                "status": page["status"],
                "hasCache": cache_store.load_result(page["id"]) is not None,
            }
        )
    return jsonify({"pages": pages})


@library_bp.get("/api/library/page/<page_id>")
def get_page(page_id):
    store = LibraryStore(current_app)
    page = next((item for item in store.list_pages() if item["id"] == page_id), None)
    if page is None:
        return jsonify({"error": "page not found"}), 404

    source_path = Path(page["sourcePath"])
    translated_path = page.get("translatedPath")
    translated_url = None
    if translated_path:
        translated_name = Path(translated_path).name
        translated_url = f"/data/cache/pages/{page_id}/{translated_name}"

    return jsonify(
        {
            "page": {
                **page,
                "sourceUrl": f"/data/library/current/pages/{source_path.name}",
                "translatedUrl": translated_url,
            }
        }
    )
