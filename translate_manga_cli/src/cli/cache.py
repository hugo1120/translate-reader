import json
from hashlib import sha1
from pathlib import Path


CACHE_SCHEMA_VERSION = 1


class BatchStageCache:
    def __init__(self, cache_root, input_dir, model, base_url, translation_signature=None, preprocess_signature=None):
        self.cache_root = Path(cache_root)
        self.input_dir = Path(input_dir)
        self.model = model
        self.base_url = base_url
        self.translation_signature = str(translation_signature or "").strip() or None
        self.preprocess_signature = str(preprocess_signature or "").strip() or None
        self.job_root = self.cache_root / self._build_job_key()
        self.pages_root = self.job_root / "pages"
        self.pages_root.mkdir(parents=True, exist_ok=True)

    def _build_job_key(self):
        raw = "|".join(
            [
                str(self.input_dir.resolve()).lower(),
                str(self.model or "").strip(),
                str(self.base_url or "").strip(),
                str(self.preprocess_signature or "").strip(),
            ]
        )
        return sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _page_cache_path(self, source_path):
        source_path = Path(source_path)
        source_key = sha1(str(source_path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        return self.pages_root / f"{source_path.stem}-{source_key}.json"

    def _source_metadata(self, source_path):
        source_path = Path(source_path)
        stat = source_path.stat()
        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
        return {
            "path": str(source_path.resolve()),
            "size": int(stat.st_size),
            "mtimeNs": int(mtime_ns),
        }

    def load_best(self, source_path):
        cache_path = self._page_cache_path(source_path)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if payload.get("schemaVersion") != CACHE_SCHEMA_VERSION:
            return None
        if payload.get("source") != self._source_metadata(source_path):
            return None

        stage = payload.get("stage") or "preprocessed"
        if (
            stage == "translated"
            and self.translation_signature
            and payload.get("translationSignature") != self.translation_signature
        ):
            return {
                "stage": "preprocessed",
                "preprocessed": payload.get("preprocessed") or {},
                "translatedTexts": None,
                "translationPayload": None,
            }

        return {
            "stage": stage,
            "preprocessed": payload.get("preprocessed") or {},
            "translatedTexts": payload.get("translatedTexts") if "translatedTexts" in payload else None,
            "translationPayload": payload.get("translationPayload") if isinstance(payload.get("translationPayload"), dict) else None,
        }

    def save_preprocessed(self, source_path, preprocessed_payload):
        self._write(
            source_path,
            {
                "stage": "preprocessed",
                "preprocessed": preprocessed_payload,
            },
        )

    def save_translated(self, source_path, preprocessed_payload, translated_texts, translation_payload=None):
        self._write(
            source_path,
            {
                "stage": "translated",
                "preprocessed": preprocessed_payload,
                "translatedTexts": translated_texts,
                "translationPayload": translation_payload if isinstance(translation_payload, dict) else None,
                "translationSignature": self.translation_signature,
            },
        )

    def _write(self, source_path, payload):
        cache_path = self._page_cache_path(source_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": CACHE_SCHEMA_VERSION,
            "source": self._source_metadata(source_path),
            **payload,
        }
        cache_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
