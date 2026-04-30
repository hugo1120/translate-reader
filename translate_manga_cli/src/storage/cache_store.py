import json
from pathlib import Path


class CacheStore:
    def __init__(self, app):
        self.pages_root = Path(app.config["CACHE_ROOT"]) / "pages"
        self.pages_root.mkdir(parents=True, exist_ok=True)

    def page_dir(self, page_id):
        path = self.pages_root / page_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_result(self, page_id):
        result_path = self.page_dir(page_id) / "result.json"
        if not result_path.exists():
            return None
        return json.loads(result_path.read_text(encoding="utf-8"))

    def load_result_or_default(self, page_id, default=None):
        payload = self.load_result(page_id)
        if payload is None:
            return default
        return payload

    def save_result(self, page_id, payload):
        result_path = self.page_dir(page_id) / "result.json"
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
