import json
from pathlib import Path

from src.core.translation_payload import (
    default_ocr_retry_state as _default_ocr_retry_state,
    empty_usage as _empty_usage,
    normalize_translation_payload as _normalize_payload,
)


def _normalize_texts(texts):
    normalized = []
    for text in texts or []:
        value = str(text or "").strip()
        if value:
            normalized.append(value)
    return normalized


def _base_stem_from_target(target_path):
    name = Path(target_path).name
    if name.endswith(".translated.png"):
        return name[: -len(".translated.png")]
    return Path(target_path).stem

def _normalize_translation_payload(payload, translated_texts):
    normalized = _normalize_payload(payload, translated_texts=translated_texts)
    return {
        "translatedTexts": _normalize_texts(normalized.get("translatedTexts") or []),
        "rounds": [
            {
                "name": item.get("name") or "final",
                "translatedTexts": _normalize_texts(item.get("translatedTexts") or []),
                "usage": dict(item.get("usage") or _empty_usage()),
            }
            for item in (normalized.get("rounds") or [])
            if isinstance(item, dict)
        ],
        "tokenUsage": dict(normalized.get("tokenUsage") or _empty_usage()),
        "ocrRetry": dict(normalized.get("ocrRetry") or _default_ocr_retry_state()),
    }


class BatchDebugArtifactWriter:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.debug_root = self.output_dir / "_debug"
        self.pages_root = self.debug_root / "pages"
        self.texts_root = self.debug_root / "texts"
        self.manifest_path = self.debug_root / "pages.jsonl"
        self.summary_path = self.debug_root / "summary.json"
        self.book_ocr_path = self.debug_root / "book.ocr.txt"
        self.book_translation_path = self.debug_root / "book.translation.txt"
        self.review_pages_path = self.debug_root / "review-pages.txt"
        self.pages_root.mkdir(parents=True, exist_ok=True)
        self.texts_root.mkdir(parents=True, exist_ok=True)
        self.records = {}
        self.finished_summary = None

    def record_page(
        self,
        *,
        page,
        page_index,
        total_pages,
        source_path,
        target_path,
        status,
        preprocessed_payload=None,
        translated_texts=None,
        translation_payload=None,
        classification=None,
        manga_context=None,
        result=None,
        error=None,
    ):
        preprocessed_payload = preprocessed_payload or {}
        result = result or {}
        original_texts = _normalize_texts(
            preprocessed_payload.get("originalTexts")
            or result.get("originalTexts")
            or []
        )
        translated_texts = _normalize_texts(
            translated_texts
            if translated_texts is not None
            else result.get("translatedTexts") or []
        )
        translation_payload = _normalize_translation_payload(
            translation_payload if translation_payload is not None else result.get("translation"),
            translated_texts,
        )
        if translation_payload.get("translatedTexts"):
            translated_texts = translation_payload["translatedTexts"]
        bubble_coords = preprocessed_payload.get("bubbleCoords") or result.get("bubbleCoords") or []
        timings = result.get("timings")
        if not isinstance(timings, dict):
            timings = preprocessed_payload.get("timings") if isinstance(preprocessed_payload.get("timings"), dict) else {}

        page_type = classification.get("page_type") if isinstance(classification, dict) else None
        skip_reason = classification.get("skip_reason") if isinstance(classification, dict) else None
        should_translate = classification.get("should_translate") if isinstance(classification, dict) else None
        metrics = classification.get("metrics") if isinstance(classification, dict) and isinstance(classification.get("metrics"), dict) else {}

        needs_review, review_reasons = self._build_review_flags(
            status=status,
            page_index=int(page_index),
            page_type=page_type,
            skip_reason=skip_reason,
            should_translate=should_translate,
            bubble_count=len(bubble_coords),
            original_texts=original_texts,
            translated_texts=translated_texts,
            total_chars=sum(len(text) for text in original_texts),
            error=error,
        )

        record = {
            "pageId": page.get("id"),
            "pageIndex": int(page_index),
            "totalPages": int(total_pages),
            "sourceName": Path(source_path).name,
            "sourcePath": str(source_path),
            "outputName": Path(target_path).name,
            "outputPath": str(target_path),
            "status": status,
            "pageType": page_type,
            "skipReason": skip_reason,
            "shouldTranslate": should_translate,
            "bubbleCount": len(bubble_coords),
            "textCount": len(original_texts),
            "charCount": sum(len(text) for text in original_texts),
            "originalTexts": original_texts,
            "translatedTexts": translated_texts,
            "translation": translation_payload,
            "translationRounds": translation_payload.get("rounds") or [],
            "tokenUsage": translation_payload.get("tokenUsage") or _empty_usage(),
            "ocrRetry": translation_payload.get("ocrRetry") or _default_ocr_retry_state(),
            "mangaContext": {
                "path": str((manga_context or {}).get("path")) if (manga_context or {}).get("path") else None,
                "generated": bool((manga_context or {}).get("generated", False)),
                "content": str((manga_context or {}).get("content") or "").strip(),
            },
            "needsReview": needs_review,
            "reviewReasons": review_reasons,
            "metrics": metrics,
            "timings": timings,
            "error": str(error) if error else None,
        }
        self.records[int(page_index)] = record
        self._write_page_files(record)
        self._flush_index()
        return record

    def finish(self, summary=None, records=None):
        if records is not None:
            self.records = self._normalize_records(records)
            for record in [self.records[index] for index in sorted(self.records)]:
                self._write_page_files(record)
        self.finished_summary = summary or None
        self._flush_index()

    def _normalize_records(self, records):
        normalized = {}
        if isinstance(records, dict):
            iterable = records.values()
        else:
            iterable = records

        for record in iterable or []:
            if not isinstance(record, dict):
                continue
            page_index = int(record.get("pageIndex") or 0)
            if page_index <= 0:
                continue
            normalized[page_index] = record
        return normalized

    def _build_review_flags(
        self,
        *,
        status,
        page_index,
        page_type,
        skip_reason,
        should_translate,
        bubble_count,
        original_texts,
        translated_texts,
        total_chars,
        error,
    ):
        reasons = []
        if error:
            reasons.append("error")
        if (
            status == "skipped-existing"
            and page_type is None
            and not original_texts
            and not translated_texts
        ):
            reasons.append("missing_cached_texts")
        if (
            page_type == "frontmatter"
            and skip_reason == "frontmatter"
            and int(page_index or 0) >= 10
            and int(bubble_count or 0) >= 10
            and int(total_chars or 0) >= 60
        ):
            reasons.append("suspicious_frontmatter")
        if should_translate is False:
            return bool(reasons), reasons
        if should_translate is True and not original_texts:
            reasons.append("missing_ocr_text")
        if should_translate is True and original_texts and not translated_texts:
            reasons.append("missing_translation_text")
        if translated_texts and len(translated_texts) != len(original_texts):
            reasons.append("translation_count_mismatch")
        return bool(reasons), reasons

    def _write_page_files(self, record):
        base_stem = _base_stem_from_target(record["outputName"])
        page_json_path = self.pages_root / f"{base_stem}.json"
        page_json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.texts_root / f"{base_stem}.ocr.txt").write_text(
            "\n\n".join(record["originalTexts"]),
            encoding="utf-8",
        )
        (self.texts_root / f"{base_stem}.translation.txt").write_text(
            "\n\n".join(record["translatedTexts"]),
            encoding="utf-8",
        )
        for round_payload in record.get("translationRounds") or []:
            round_name = str(round_payload.get("name") or "final").strip() or "final"
            (self.texts_root / f"{base_stem}.{round_name}.translation.txt").write_text(
                "\n\n".join(round_payload.get("translatedTexts") or []),
                encoding="utf-8",
            )

    def _flush_index(self):
        ordered_records = [self.records[index] for index in sorted(self.records)]
        self.manifest_path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in ordered_records),
            encoding="utf-8",
        )
        self.book_ocr_path.write_text(self._build_book_text(ordered_records, "originalTexts"), encoding="utf-8")
        self.book_translation_path.write_text(
            self._build_book_text(ordered_records, "translatedTexts"),
            encoding="utf-8",
        )
        self.review_pages_path.write_text(
            "\n".join(
                f"{record['sourceName']}\t{','.join(record['reviewReasons'])}"
                for record in ordered_records
                if record.get("needsReview")
            ),
            encoding="utf-8",
        )
        self.summary_path.write_text(
            json.dumps(self._build_summary(ordered_records), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_book_text(self, ordered_records, field_name):
        sections = []
        for record in ordered_records:
            sections.append(f"===== {record['sourceName']} =====")
            sections.append("\n\n".join(record.get(field_name) or []))
        return "\n\n".join(sections).strip()

    def _build_summary(self, ordered_records):
        status_counts = {}
        for record in ordered_records:
            status = record.get("status") or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1

        payload = {
            "recordedPages": len(ordered_records),
            "statusCounts": status_counts,
            "needsReviewPages": [
                {
                    "sourceName": record["sourceName"],
                    "outputName": record["outputName"],
                    "reviewReasons": record["reviewReasons"],
                }
                for record in ordered_records
                if record.get("needsReview")
            ],
        }
        if isinstance(self.finished_summary, dict):
            payload["runSummary"] = self.finished_summary
        return payload
