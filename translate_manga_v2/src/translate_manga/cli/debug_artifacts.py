import json
from pathlib import Path

from translate_manga.core.translation_payload import (
    default_ocr_retry_state as _default_ocr_retry_state,
    empty_usage as _empty_usage,
    normalize_translation_payload as _normalize_payload,
)
from translate_manga.core.translate.openai_compatible import is_translation_failure_text


_PREPROCESSED_DEBUG_KEYS = [
    "bubbleCoords",
    "bubblePolygons",
    "autoDirections",
    "textlinesPerBubble",
    "bubbleColors",
    "multimodalLayout",
    "bubbleLayoutHints",
    "originalTexts",
    "ocrResults",
    "timings",
]


def _normalize_texts(texts, *, preserve_empty=False):
    normalized = []
    for text in texts or []:
        value = str(text or "").strip()
        if value or preserve_empty:
            normalized.append(value)
    return normalized


def _base_stem_from_target(target_path):
    name = Path(target_path).name
    if name.endswith(".translated.png"):
        return name[: -len(".translated.png")]
    return Path(target_path).stem


def _read_timing_value(record, name):
    timings = record.get("timings") if isinstance(record.get("timings"), dict) else {}
    try:
        return max(0.0, float(timings.get(name, 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _normalize_translation_payload(payload, translated_texts):
    normalized = _normalize_payload(payload, translated_texts=translated_texts)
    return {
        "translatedTexts": _normalize_texts(normalized.get("translatedTexts") or [], preserve_empty=True),
        "rounds": [
            {
                "name": item.get("name") or "final",
                "translatedTexts": _normalize_texts(item.get("translatedTexts") or [], preserve_empty=True),
                "usage": dict(item.get("usage") or _empty_usage()),
            }
            for item in (normalized.get("rounds") or [])
            if isinstance(item, dict)
        ],
        "tokenUsage": dict(normalized.get("tokenUsage") or _empty_usage()),
        "ocrRetry": dict(normalized.get("ocrRetry") or _default_ocr_retry_state()),
    }


def _build_preprocessed_debug_payload(preprocessed_payload, result):
    source_payload = preprocessed_payload if isinstance(preprocessed_payload, dict) else {}
    result_payload = result if isinstance(result, dict) else {}
    payload = {}
    for key in _PREPROCESSED_DEBUG_KEYS:
        value = source_payload.get(key) if key in source_payload else result_payload.get(key)
        if value is not None:
            payload[key] = value
    payload["rawMask"] = None
    return payload


class BatchDebugArtifactWriter:
    def __init__(self, output_dir, run_options=None, flush_interval=1):
        self.output_dir = Path(output_dir)
        self.debug_root = self.output_dir / "_debug"
        self.pages_root = self.debug_root / "pages"
        self.texts_root = self.debug_root / "texts"
        self.manifest_path = self.debug_root / "pages.jsonl"
        self.summary_path = self.debug_root / "summary.json"
        self.book_ocr_path = self.debug_root / "book.ocr.txt"
        self.book_translation_path = self.debug_root / "book.translation.txt"
        self.review_pages_path = self.debug_root / "review-pages.txt"
        self.failed_translations_path = self.debug_root / "failed-translations.tsv"
        self.final_review_report_path = self.debug_root / "final-review-report.txt"
        self.pages_root.mkdir(parents=True, exist_ok=True)
        self.texts_root.mkdir(parents=True, exist_ok=True)
        self.records = {}
        self.finished_summary = None
        self.run_options = dict(run_options or {})
        self.flush_interval = max(1, int(flush_interval or 1))
        self._dirty_records = 0

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
            else result.get("translatedTexts") or [],
            preserve_empty=True,
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
            translation_payload=translation_payload,
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
            "preprocessedPayload": _build_preprocessed_debug_payload(preprocessed_payload, result),
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
        self._dirty_records += 1
        if self._dirty_records >= self.flush_interval:
            self._flush_index()
            self._dirty_records = 0
        return record

    def finish(self, summary=None, records=None, run_options=None):
        if records is not None:
            self.records = self._normalize_records(records)
            for record in [self.records[index] for index in sorted(self.records)]:
                self._write_page_files(record)
        if isinstance(run_options, dict):
            self.run_options = dict(run_options)
        self.finished_summary = summary or None
        self._flush_index()
        self._dirty_records = 0

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
        translation_payload,
        total_chars,
        error,
    ):
        reasons = []
        def add_reason(reason):
            if reason not in reasons:
                reasons.append(reason)

        if error:
            add_reason("error")
        if (
            page_type == "frontmatter"
            and skip_reason == "frontmatter"
            and int(page_index or 0) >= 10
            and int(bubble_count or 0) >= 10
            and int(total_chars or 0) >= 60
        ):
            add_reason("suspicious_frontmatter")
        retry_state = (translation_payload or {}).get("ocrRetry")
        retry_reasons = retry_state.get("reasons") if isinstance(retry_state, dict) else []
        for reason in retry_reasons or []:
            reason = str(reason or "").strip()
            if reason == "translation_failed":
                add_reason("translation_failed")
        if any(is_translation_failure_text(text) for text in translated_texts or []):
            add_reason("translation_failure_placeholder")
        if status == "skipped-existing":
            return bool(reasons), reasons
        if should_translate is False:
            return bool(reasons), reasons
        if should_translate is True and not original_texts:
            add_reason("missing_ocr_text")
        if should_translate is True and original_texts and not translated_texts:
            add_reason("missing_translation_text")
        if translated_texts and len(translated_texts) != len(original_texts):
            add_reason("translation_count_mismatch")
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
        self.failed_translations_path.write_text(
            self._build_failed_translations_tsv(ordered_records),
            encoding="utf-8",
        )
        self.final_review_report_path.write_text(
            self._build_final_review_report(ordered_records),
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

    def _build_failed_translations_tsv(self, ordered_records):
        rows = ["sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath"]
        for record in ordered_records:
            if not record.get("needsReview"):
                continue
            rows.append(
                "\t".join(
                    [
                        str(record.get("sourceName") or ""),
                        str(record.get("outputName") or ""),
                        str(record.get("status") or ""),
                        ",".join(record.get("reviewReasons") or []),
                        str(record.get("sourcePath") or ""),
                        str(record.get("outputPath") or ""),
                    ]
                )
            )
        return "\n".join(rows)

    def _build_timing_summary(self, ordered_records):
        fields = ["detect", "ocr", "color", "translate", "render", "total"]
        totals = {field: 0.0 for field in fields}
        for record in ordered_records:
            for field in fields:
                totals[field] += _read_timing_value(record, field)

        page_count = len(ordered_records)
        averages = {
            field: (totals[field] / page_count if page_count else 0.0)
            for field in fields
        }
        slowest_records = sorted(
            ordered_records,
            key=lambda record: _read_timing_value(record, "total"),
            reverse=True,
        )[:10]
        return {
            "pageCount": page_count,
            "totals": {field: round(totals[field], 3) for field in fields},
            "averages": {field: round(averages[field], 3) for field in fields},
            "slowestPages": [
                {
                    "sourceName": record.get("sourceName"),
                    "total": round(_read_timing_value(record, "total"), 3),
                    "detect": round(_read_timing_value(record, "detect"), 3),
                    "ocr": round(_read_timing_value(record, "ocr"), 3),
                    "color": round(_read_timing_value(record, "color"), 3),
                    "translate": round(_read_timing_value(record, "translate"), 3),
                    "render": round(_read_timing_value(record, "render"), 3),
                }
                for record in slowest_records
            ],
        }

    def _build_final_review_report(self, ordered_records):
        review_records = [record for record in ordered_records if record.get("needsReview")]
        lines = [
            "# Final Review Report",
            "",
            f"记录页数: {len(ordered_records)}",
            f"仍需复查: {len(review_records)}",
        ]
        if isinstance(self.finished_summary, dict):
            lines.append(
                "本次运行: "
                f"total={self.finished_summary.get('total', 0)} "
                f"ok={self.finished_summary.get('succeeded', 0)} "
                f"skip={self.finished_summary.get('skipped', 0)} "
                f"fail={self.finished_summary.get('failed', 0)}"
            )

        timing_summary = self._build_timing_summary(ordered_records)
        lines.extend(["", "## 阶段耗时汇总"])
        if timing_summary["pageCount"]:
            for field in ["detect", "ocr", "color", "translate", "render", "total"]:
                lines.append(
                    f"{field}: "
                    f"total={timing_summary['totals'][field]:.2f}s "
                    f"avg={timing_summary['averages'][field]:.2f}s"
                )
        else:
            lines.append("- 无")

        lines.extend(["", "## 仍需复查页面"])
        if review_records:
            for record in review_records:
                reasons = ",".join(record.get("reviewReasons") or []) or "unknown"
                lines.append(f"- {record.get('sourceName')} [{record.get('status')}] {reasons}")
        else:
            lines.append("- 无")

        timed_records = []
        for record in ordered_records:
            timings = record.get("timings") if isinstance(record.get("timings"), dict) else {}
            total_seconds = float(timings.get("total", 0.0) or 0.0)
            if total_seconds > 0:
                timed_records.append((total_seconds, record))
        timed_records.sort(key=lambda item: item[0], reverse=True)

        lines.extend(["", "## 页面耗时 Top 10"])
        if timed_records:
            for total_seconds, record in timed_records[:10]:
                lines.append(f"- {record.get('sourceName')}: {total_seconds:.2f}s")
        else:
            lines.append("- 无")

        return "\n".join(lines).strip() + "\n"

    def _build_summary(self, ordered_records):
        status_counts = {}
        review_reason_counts = {}
        for record in ordered_records:
            status = record.get("status") or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            for reason in record.get("reviewReasons") or []:
                review_reason_counts[reason] = review_reason_counts.get(reason, 0) + 1

        payload = {
            "recordedPages": len(ordered_records),
            "statusCounts": status_counts,
            "reviewReasonCounts": review_reason_counts,
            "needsReviewPages": [
                {
                    "sourceName": record["sourceName"],
                    "outputName": record["outputName"],
                    "reviewReasons": record["reviewReasons"],
                }
                for record in ordered_records
                if record.get("needsReview")
            ],
            "timingSummary": self._build_timing_summary(ordered_records),
        }
        if isinstance(self.finished_summary, dict):
            payload["runSummary"] = self.finished_summary
        if isinstance(self.run_options, dict) and self.run_options:
            payload["runOptions"] = self.run_options
        return payload
