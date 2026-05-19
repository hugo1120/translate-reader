import csv
import json
import re
from pathlib import Path

from translate_manga.config.settings import load_settings, resolve_translation_config
from translate_manga.core.natural_sort import natural_sort_key
from translate_manga.core.translate.openai_compatible import OpenAICompatibleTranslator, is_translation_failure_text


QUALITY_REVIEW_TSV_NAME = "quality-review.tsv"
QUALITY_REVIEW_REASON_CODES = {
    "quality_mistranslation",
    "quality_inconsistent_name",
    "quality_untranslated_source",
    "quality_awkward_chinese",
    "quality_ocr_noise",
    "quality_too_long_for_bubble",
    "quality_prompt_profile_mismatch",
    "quality_translation_issue",
}
_REASON_ALIASES = {
    "mistranslation": "quality_mistranslation",
    "inconsistent_name": "quality_inconsistent_name",
    "untranslated_source": "quality_untranslated_source",
    "awkward_chinese": "quality_awkward_chinese",
    "ocr_noise": "quality_ocr_noise",
    "too_long_for_bubble": "quality_too_long_for_bubble",
    "prompt_profile_mismatch": "quality_prompt_profile_mismatch",
}
_TSV_COLUMNS = ["sourceName", "outputName", "reasons", "confidence", "comment"]
_JAPANESE_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\uff66-\uff9f]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RESIDUE_RE = re.compile(r"(?<![A-Za-z0-9.])([A-Za-z]{1,3})(?![A-Za-z0-9])")
_TRAILING_DIGIT_RE = re.compile(r"\d{1,3}$")
_SHORT_TITLE_VOLUME_RE = re.compile(r"^[\u3400-\u9fff]{1,8}[传卷话章篇集]\d{1,3}$")
_ALLOWED_SHORT_LATIN_TOKENS = {
    "AI",
    "CD",
    "DNA",
    "DVD",
    "GPS",
    "NG",
    "OK",
    "SNS",
    "TV",
    "VIP",
}
_QUALITY_REVIEW_SYSTEM_PROMPT = """你是专业漫画汉化校对。你的任务是找出“值得重翻并重新嵌字”的页，而不是润色所有句子。

只标记明确问题：误译、人物/术语前后不一致、译文残留日文或英文、OCR 噪声导致译错、中文明显不通顺、气泡内译文明显过长、提示词语言/阅读方向不匹配。
不要因为个人措辞偏好、标点风格、轻微口语差异而标记。
只输出 JSON，不输出解释文本。"""


def _debug_root(output_dir):
    path = Path(output_dir)
    return path if path.name == "_debug" else path / "_debug"


def _clean_text(value):
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _normalize_text_list(values):
    normalized = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_layout_mode(value):
    raw_value = str(value or "").strip().lower()
    if raw_value in {"h", "horizontal"}:
        return "horizontal"
    if raw_value in {"v", "vertical"}:
        return "vertical"
    if raw_value == "auto":
        return "auto"
    return ""


def _bubble_dimensions(coords):
    if not isinstance(coords, (list, tuple)) or len(coords) < 4:
        return 0, 0
    width = max(0, int(coords[2]) - int(coords[0]))
    height = max(0, int(coords[3]) - int(coords[1]))
    return width, height


def _is_dense_long_narration_text(text, coords, direction):
    text_length = len(str(text or "").strip())
    width, height = _bubble_dimensions(coords)
    area = width * height
    normalized_direction = _normalize_layout_mode(direction)

    if text_length >= 120:
        return True
    if text_length >= 80 and area >= 50000:
        return True
    if normalized_direction != "horizontal" and text_length >= 50 and width >= 320 and height >= 180:
        return True
    return False


def _is_japanese_review_profile(style_profile):
    source_language = str((style_profile or {}).get("source_language") or "").strip().lower()
    return source_language in {"", "japanese", "jp", "ja"}


def _has_latin_ocr_residue(text):
    value = str(text or "").strip()
    if not value or _SHORT_TITLE_VOLUME_RE.match(value):
        return False
    for match in _LATIN_RESIDUE_RE.finditer(value):
        if match.group(1).upper() in _ALLOWED_SHORT_LATIN_TOKENS:
            continue
        return True
    return False


def _has_trailing_digit_ocr_residue(text):
    value = str(text or "").strip()
    if not value or _SHORT_TITLE_VOLUME_RE.match(value):
        return False
    if not _TRAILING_DIGIT_RE.search(value):
        return False
    if re.search(r"\d+[年月日号]$", value):
        return False
    cjk_count = len(_CJK_RE.findall(value))
    return cjk_count >= 7 or any(marker in value for marker in ("…", "，", ",", "。", "！", "？", "!", "?"))


def _has_suspicious_ocr_residue(text):
    return _has_latin_ocr_residue(text) or _has_trailing_digit_ocr_residue(text)


def _normalize_reason(reason):
    value = str(reason or "").strip()
    if not value:
        return None
    value = _REASON_ALIASES.get(value, value)
    if value not in QUALITY_REVIEW_REASON_CODES:
        return "quality_translation_issue"
    return value


def _normalize_reasons(value):
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []

    reasons = []
    for raw_item in raw_items:
        reason = _normalize_reason(raw_item)
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons or ["quality_translation_issue"]


def _normalize_confidence(value):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def _normalize_entry(payload):
    if not isinstance(payload, dict):
        return None
    source_name = _clean_text(payload.get("sourceName") or payload.get("source"))
    if not source_name:
        return None
    return {
        "sourceName": source_name,
        "outputName": _clean_text(payload.get("outputName") or payload.get("output") or ""),
        "reviewReasons": _normalize_reasons(payload.get("reviewReasons") or payload.get("reasons") or payload.get("reason")),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "comment": _clean_text(payload.get("comment") or payload.get("note") or ""),
    }


def _strip_code_fence(content):
    text = str(content or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_text(content):
    text = _strip_code_fence(content)
    if not text:
        return ""
    if text[0] in "[{":
        return text

    first_object = text.find("{")
    first_array = text.find("[")
    candidates = [index for index in [first_object, first_array] if index >= 0]
    if not candidates:
        return text
    start = min(candidates)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start : end + 1] if end >= start else text[start:]


def _parse_json_response(content):
    try:
        payload = json.loads(_extract_json_text(content))
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict):
        if isinstance(payload.get("issues"), list):
            return payload["issues"]
        if isinstance(payload.get("pages"), list):
            return payload["pages"]
        return []
    if isinstance(payload, list):
        return payload
    return []


def _parse_tsv_response(content):
    lines = [line for line in str(content or "").splitlines() if line.strip()]
    if not lines:
        return []
    rows = []
    if "\t" in lines[0] and "sourceName" in lines[0]:
        reader = csv.DictReader(lines, delimiter="\t")
        rows = list(reader)
    else:
        for line in lines:
            parts = line.split("\t")
            if not parts:
                continue
            rows.append(
                {
                    "sourceName": parts[0] if len(parts) > 0 else "",
                    "reasons": parts[1] if len(parts) > 1 else "",
                    "confidence": parts[2] if len(parts) > 2 else 0,
                    "comment": parts[3] if len(parts) > 3 else "",
                }
            )
    return rows


def parse_quality_review_response(content):
    rows = _parse_json_response(content)
    if rows is None:
        rows = _parse_tsv_response(content)

    entries = []
    for row in rows or []:
        entry = _normalize_entry(row)
        if entry:
            entries.append(entry)
    return _dedupe_entries(entries)


def _entry_to_tsv_row(entry):
    return {
        "sourceName": _clean_text((entry or {}).get("sourceName")),
        "outputName": _clean_text((entry or {}).get("outputName")),
        "reasons": ",".join(_normalize_reasons((entry or {}).get("reviewReasons") or (entry or {}).get("reasons"))),
        "confidence": str(_normalize_confidence((entry or {}).get("confidence"))),
        "comment": _clean_text((entry or {}).get("comment")),
    }


def write_quality_review_tsv(output_dir, entries):
    debug_root = _debug_root(output_dir)
    debug_root.mkdir(parents=True, exist_ok=True)
    path = debug_root / QUALITY_REVIEW_TSV_NAME
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_TSV_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in _dedupe_entries(entries):
            row = _entry_to_tsv_row(entry)
            if row["sourceName"]:
                writer.writerow(row)
    return path


def read_quality_review_entries(output_dir):
    path = _debug_root(output_dir) / QUALITY_REVIEW_TSV_NAME
    if not path.exists():
        return []
    entries = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                entry = _normalize_entry(row)
                if entry:
                    entries.append(entry)
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    return _dedupe_entries(entries)


def clear_quality_review_entries(output_dir, source_names=None):
    if source_names is None:
        write_quality_review_tsv(output_dir, [])
        return []
    source_name_set = {str(name or "").strip() for name in source_names if str(name or "").strip()}
    remaining = [
        entry
        for entry in read_quality_review_entries(output_dir)
        if entry.get("sourceName") not in source_name_set
    ]
    write_quality_review_tsv(output_dir, remaining)
    return remaining


def _record_translated_texts(record):
    texts = list((record or {}).get("translatedTexts") or [])
    translation = (record or {}).get("translation")
    if isinstance(translation, dict):
        texts.extend(translation.get("translatedTexts") or [])
        for round_payload in translation.get("rounds") or []:
            if isinstance(round_payload, dict):
                texts.extend(round_payload.get("translatedTexts") or [])
    normalized = []
    for text in texts:
        value = str(text or "").strip()
        if not value or is_translation_failure_text(value):
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized


def load_reviewable_page_records(output_dir):
    pages_root = _debug_root(output_dir) / "pages"
    if not pages_root.exists():
        return []

    records = []
    for page_json_path in pages_root.glob("*.json"):
        try:
            record = json.loads(page_json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if str(record.get("status") or "").strip().lower() == "failed":
            continue
        source_name = _clean_text(record.get("sourceName"))
        original_texts = _normalize_text_list(record.get("originalTexts") or [])
        translated_texts = _record_translated_texts(record)
        payload = record.get("preprocessedPayload") if isinstance(record.get("preprocessedPayload"), dict) else {}
        if not source_name:
            continue
        records.append(
            {
                "sourceName": source_name,
                "outputName": _clean_text(record.get("outputName")),
                "pageIndex": int(record.get("pageIndex") or 0),
                "status": _clean_text(record.get("status")),
                "originalTexts": original_texts,
                "translatedTexts": translated_texts,
                "reviewReasons": list(record.get("reviewReasons") or []),
                "autoDirections": list(payload.get("autoDirections") or []),
                "bubbleCoords": list(payload.get("bubbleCoords") or []),
                "ocrResults": list(payload.get("ocrResults") or []),
            }
        )
    return sorted(
        records,
        key=lambda record: (
            int(record.get("pageIndex") or 0) if int(record.get("pageIndex") or 0) > 0 else 10**9,
            natural_sort_key(record.get("sourceName") or ""),
        ),
    )


def _chunk_records(records, chunk_size):
    chunk_size = max(1, int(chunk_size or 30))
    for index in range(0, len(records), chunk_size):
        yield records[index : index + chunk_size]


def _emit_progress(progress_callback, payload):
    if progress_callback is None:
        return
    progress_callback(dict(payload))


def _build_review_messages(records, style_profile=None):
    style_profile = style_profile or {}
    review_payload = {
        "styleId": style_profile.get("style_id"),
        "sourceLanguage": style_profile.get("source_language"),
        "layoutMode": style_profile.get("layout_mode"),
        "readingOrder": style_profile.get("reading_order"),
        "pages": [
            {
                "sourceName": record["sourceName"],
                "outputName": record.get("outputName") or "",
                "pageIndex": record.get("pageIndex") or None,
                "originalTexts": record.get("originalTexts") or [],
                "translatedTexts": record.get("translatedTexts") or [],
            }
            for record in records
        ],
    }
    user_prompt = (
        "请审核以下漫画页的汉化质量。只返回需要重翻的页。\n"
        "输出格式必须是 JSON："
        '{"issues":[{"sourceName":"001.jpg","reasons":["quality_mistranslation"],'
        '"confidence":0.8,"comment":"简短原因"}]}\n'
        "如果没有问题，返回 {\"issues\":[]}。\n\n"
        f"{json.dumps(review_payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": _QUALITY_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _call_reviewer(reviewer, *, messages, model, base_url, api_key):
    if reviewer is not None:
        response = reviewer(messages=messages, model=model, base_url=base_url, api_key=api_key)
        if isinstance(response, tuple):
            return str(response[0] or "")
        return str(response or "")

    content, _usage = OpenAICompatibleTranslator()._request_completion(
        model=model,
        base_url=base_url,
        api_key=api_key,
        messages=messages,
    )
    return content


def _build_heuristic_quality_entries(records, style_profile=None):
    style_profile = style_profile or {}
    layout_mode = _normalize_layout_mode(style_profile.get("layout_mode") or style_profile.get("layoutMode"))
    is_japanese_review = _is_japanese_review_profile(style_profile)
    entries = []
    for record in records or []:
        source_name = _clean_text((record or {}).get("sourceName"))
        if not source_name:
            continue
        output_name = _clean_text((record or {}).get("outputName"))
        original_texts = _normalize_text_list((record or {}).get("originalTexts") or [])
        translated_texts = _normalize_text_list((record or {}).get("translatedTexts") or [])
        status = _clean_text((record or {}).get("status")).lower()
        auto_directions = [
            _normalize_layout_mode(direction)
            for direction in ((record or {}).get("autoDirections") or [])
        ]
        auto_directions = [direction for direction in auto_directions if direction]
        bubble_coords = list((record or {}).get("bubbleCoords") or [])
        ocr_results = list((record or {}).get("ocrResults") or [])

        if status == "skipped-existing" and not original_texts and not translated_texts:
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_translation_issue"],
                    "confidence": 1.0,
                    "comment": "已存在输出，但缺少 OCR/译文调试记录，当前无法验证质量。",
                }
            )
            continue

        if any(_JAPANESE_SCRIPT_RE.search(text) for text in translated_texts):
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_untranslated_source"],
                    "confidence": 0.96,
                    "comment": "译文仍含日文假名，可能是未翻译拟声词或原文残留。",
                }
            )

        if is_japanese_review and any(_has_suspicious_ocr_residue(text) for text in translated_texts):
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_ocr_noise"],
                    "confidence": 0.91,
                    "comment": "译文包含孤立拉丁字母或尾部数字残留，疑似 OCR 噪声未清理。",
                }
            )

        has_low_confidence_fallback_ocr = False
        has_long_narration_fallback_ocr = False
        has_dense_long_narration_bubble = False
        for index, original_text in enumerate(original_texts):
            coords = bubble_coords[index] if index < len(bubble_coords) else []
            direction = auto_directions[index] if index < len(auto_directions) else ""
            if _is_dense_long_narration_text(original_text, coords, direction):
                has_dense_long_narration_bubble = True
        for index, ocr_result in enumerate(ocr_results):
            if not isinstance(ocr_result, dict):
                continue
            try:
                confidence = float(ocr_result.get("confidence", 1.0) or 1.0)
            except (TypeError, ValueError):
                confidence = 1.0
            original_text = original_texts[index] if index < len(original_texts) else ""
            coords = bubble_coords[index] if index < len(bubble_coords) else []
            direction = auto_directions[index] if index < len(auto_directions) else ""
            if bool(ocr_result.get("fallbackUsed")) and confidence < 0.05:
                has_low_confidence_fallback_ocr = True
            if (
                bool(ocr_result.get("fallbackUsed"))
                and confidence < 0.7
                and _is_dense_long_narration_text(original_text, coords, direction)
            ):
                has_long_narration_fallback_ocr = True

        if has_long_narration_fallback_ocr:
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_ocr_noise"],
                    "confidence": 0.92,
                    "comment": "页面包含长说明块 OCR 回退结果，当前译文可能直接放大了 OCR 噪声。",
                }
            )
        elif has_low_confidence_fallback_ocr:
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_ocr_noise"],
                    "confidence": 0.9,
                    "comment": "页面包含低置信 OCR 回退结果，当前译文可能直接放大了 OCR 噪声。",
                }
            )

        if has_dense_long_narration_bubble:
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_too_long_for_bubble"],
                    "confidence": 0.88,
                    "comment": "页面包含长说明块，当前译文可能被整段塞入单个气泡。",
                }
            )

        has_tall_horizontal_bubble = False
        for index, direction in enumerate(auto_directions):
            if direction != "horizontal" or index >= len(bubble_coords):
                continue
            coords = bubble_coords[index]
            if not isinstance(coords, (list, tuple)) or len(coords) < 4:
                continue
            width = max(0, int(coords[2]) - int(coords[0]))
            height = max(0, int(coords[3]) - int(coords[1]))
            translated_text = translated_texts[index] if index < len(translated_texts) else ""
            if height >= 40 and height >= int(width * 0.45) and len(translated_text) >= 4:
                has_tall_horizontal_bubble = True
                break

        if layout_mode == "vertical" and has_tall_horizontal_bubble:
            entries.append(
                {
                    "sourceName": source_name,
                    "outputName": output_name,
                    "reviewReasons": ["quality_prompt_profile_mismatch"],
                    "confidence": 0.95,
                    "comment": "页面包含横排气泡，当前竖排样式可能导致嵌字方向不匹配。",
                }
            )
    return _dedupe_entries(entries)


def _dedupe_entries(entries):
    by_source = {}
    order = []
    for entry in entries or []:
        normalized = _normalize_entry(entry)
        if not normalized:
            continue
        source_name = normalized["sourceName"]
        if source_name not in by_source:
            by_source[source_name] = normalized
            order.append(source_name)
            continue
        current = by_source[source_name]
        current["reviewReasons"] = _merge_reasons(current.get("reviewReasons"), normalized.get("reviewReasons"))
        if normalized.get("confidence", 0.0) > current.get("confidence", 0.0):
            current["confidence"] = normalized["confidence"]
        if normalized.get("comment") and normalized["comment"] not in current.get("comment", ""):
            current["comment"] = "; ".join([item for item in [current.get("comment"), normalized["comment"]] if item])
    return [by_source[source_name] for source_name in order]


def _merge_reasons(left, right):
    reasons = []
    for reason in _normalize_reasons(left) + _normalize_reasons(right):
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def run_quality_review(
    output_dir,
    *,
    reviewer=None,
    model=None,
    base_url=None,
    api_key=None,
    chunk_size=30,
    style_profile=None,
    project_root=None,
    progress_callback=None,
):
    settings = load_settings(project_root=project_root)
    translation = resolve_translation_config(settings=settings)
    model = model or translation["model"]
    base_url = base_url or translation["base_url"]
    if api_key is None:
        api_key = translation["api_key"]

    records = load_reviewable_page_records(output_dir)
    heuristic_entries = _build_heuristic_quality_entries(records, style_profile=style_profile)
    reviewable_records = [
        record for record in records
        if record.get("originalTexts") and record.get("translatedTexts")
    ]
    if not reviewable_records:
        write_quality_review_tsv(output_dir, heuristic_entries)
        _emit_progress(progress_callback, {"event": "start", "totalPages": 0, "totalChunks": 0})
        _emit_progress(progress_callback, {"event": "done", "flaggedPages": len(heuristic_entries)})
        return heuristic_entries

    record_by_source = {record["sourceName"]: record for record in reviewable_records}
    entries = list(heuristic_entries)
    chunks = list(_chunk_records(reviewable_records, chunk_size))
    total_chunks = len(chunks)
    _emit_progress(
        progress_callback,
        {"event": "start", "totalPages": len(reviewable_records), "totalChunks": total_chunks},
    )
    for chunk_index, chunk in enumerate(chunks, start=1):
        chunk_sources = {record["sourceName"] for record in chunk}
        _emit_progress(
            progress_callback,
            {
                "event": "chunk_start",
                "currentChunk": chunk_index,
                "totalChunks": total_chunks,
                "pageCount": len(chunk),
                "firstSourceName": chunk[0]["sourceName"],
                "lastSourceName": chunk[-1]["sourceName"],
            },
        )
        chunk_flagged_count = 0
        response = _call_reviewer(
            reviewer,
            messages=_build_review_messages(chunk, style_profile=style_profile),
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        for entry in parse_quality_review_response(response):
            source_name = entry["sourceName"]
            if source_name not in chunk_sources:
                continue
            if not entry.get("outputName"):
                entry["outputName"] = record_by_source[source_name].get("outputName") or ""
            entries.append(entry)
            chunk_flagged_count += 1
        _emit_progress(
            progress_callback,
            {
                "event": "chunk_done",
                "currentChunk": chunk_index,
                "totalChunks": total_chunks,
                "flaggedPages": chunk_flagged_count,
            },
        )

    entries = _dedupe_entries(entries)
    write_quality_review_tsv(output_dir, entries)
    _emit_progress(progress_callback, {"event": "done", "flaggedPages": len(entries)})
    return entries
