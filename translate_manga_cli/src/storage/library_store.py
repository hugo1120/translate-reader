import json
import shutil
import uuid
from pathlib import Path

from src.core.natural_sort import natural_sort_key


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class LibraryStore:
    def __init__(self, app):
        self.pages_root = Path(app.config["LIBRARY_ROOT"]) / "pages"
        self.manifest_path = Path(app.config["LIBRARY_ROOT"]) / "manifest.json"

    def import_files(self, files):
        shutil.rmtree(self.pages_root, ignore_errors=True)
        self.pages_root.mkdir(parents=True, exist_ok=True)

        pages = []
        valid_files = [file_storage for file_storage in files if Path(file_storage.filename).suffix.lower() in IMAGE_EXTENSIONS]
        for index, file_storage in enumerate(sorted(valid_files, key=lambda item: natural_sort_key(item.filename)), start=1):
            suffix = Path(file_storage.filename).suffix.lower()
            page_id = f"page-{index:04d}"
            target = self.pages_root / f"{page_id}{suffix}"
            file_storage.save(target)
            pages.append(
                {
                    "id": page_id,
                    "fileName": file_storage.filename,
                    "sourcePath": str(target),
                    "translatedPath": None,
                    "status": "idle",
                    "cacheKey": str(uuid.uuid4()),
                }
            )

        self._write_manifest(pages)
        return pages

    def list_pages(self):
        if not self.manifest_path.exists():
            return []
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return manifest.get("pages", [])

    def update_translated_path(self, page_id, translated_path):
        pages = self.list_pages()
        for page in pages:
            if page["id"] == page_id:
                page["translatedPath"] = translated_path
                page["status"] = "translated"
        self._write_manifest(pages)

    def seed_pages(self, pages):
        normalized_pages = list(pages or [])
        self._write_manifest(normalized_pages)
        return normalized_pages

    def _write_manifest(self, pages):
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pages": pages}
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
