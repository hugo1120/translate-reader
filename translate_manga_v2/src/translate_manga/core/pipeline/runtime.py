from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class PipelineRuntime:
    def __init__(
        self,
        workspace_root,
        *,
        layout_mode=None,
        style_id=None,
        source_language=None,
        prompt_profile=None,
        reading_order=None,
        ocr_options=None,
        font_family=None,
    ):
        self.workspace_root = Path(workspace_root)
        self.cache_root = self.workspace_root / "cache"
        self.pages_root = self.cache_root / "pages"
        self.pages_root.mkdir(parents=True, exist_ok=True)
        normalized_layout_mode = str(layout_mode or "").strip()
        self.layout_mode = normalized_layout_mode or None
        self.style_id = str(style_id or "").strip() or None
        self.source_language = str(source_language or "").strip() or None
        self.prompt_profile = str(prompt_profile or "").strip() or None
        self.reading_order = str(reading_order or "").strip() or None
        self.ocr_options = deepcopy(ocr_options or {})
        self.font_family = str(font_family or "").strip() or None
        self.config = {
            "WORKSPACE_ROOT": str(self.workspace_root),
            "CACHE_ROOT": str(self.cache_root),
            "CLI_LAYOUT_MODE_OVERRIDE": self.layout_mode,
            "CLI_STYLE_ID": self.style_id,
            "CLI_SOURCE_LANGUAGE": self.source_language,
            "CLI_READING_ORDER": self.reading_order,
        }
        self._pages = []
        self._results = {}

    def seed_pages(self, pages):
        self._pages = [deepcopy(page) for page in (pages or [])]
        return self.list_pages()

    def list_pages(self):
        return [deepcopy(page) for page in self._pages]

    def get_page(self, page_id):
        for page in self._pages:
            if page.get("id") == page_id:
                return page
        return None

    def update_translated_path(self, page_id, translated_path):
        for page in self._pages:
            if page.get("id") != page_id:
                continue
            page["translatedPath"] = translated_path
            page["status"] = "translated"
            return deepcopy(page)
        return None

    def page_dir(self, page_id):
        page_dir = self.pages_root / str(page_id)
        page_dir.mkdir(parents=True, exist_ok=True)
        return page_dir

    def page_cache_paths(self, page_id):
        page_dir = self.page_dir(page_id)
        return {
            "pageCacheDir": page_dir,
            "cleanImagePath": str(page_dir / f"{page_id}.clean.png"),
            "translatedImagePath": str(page_dir / f"{page_id}.translated.png"),
        }

    def load_result(self, page_id):
        if page_id in self._results:
            return deepcopy(self._results[page_id])

        result_path = self.page_dir(page_id) / "result.json"
        if not result_path.exists():
            return None

        payload = json.loads(result_path.read_text(encoding="utf-8"))
        self._results[page_id] = payload
        return deepcopy(payload)

    def load_result_or_default(self, page_id, default=None):
        payload = self.load_result(page_id)
        if payload is None:
            return default
        return payload

    def save_result(self, page_id, payload):
        normalized = deepcopy(payload)
        self._results[page_id] = normalized
        result_path = self.page_dir(page_id) / "result.json"
        result_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return deepcopy(normalized)
