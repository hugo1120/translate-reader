import json
import re
import subprocess

import openai

from translate_manga.config.settings import _DEFAULT_TRANSLATION_PROMPTS, resolve_translation_config, resolve_translation_prompt_config


TRANSLATION_PROMPT_SIGNATURE = "multi-round-v1"
TRANSLATION_FAILURE_TEXT = "【翻译失败】请检查终端中的错误日志"
REQUEST_TIMEOUT_SECONDS = 90.0
_CURL_TIMEOUT_SECONDS = 95
MULTI_ROUND_MAX_TEXTS = 5
MULTI_ROUND_DENSE_TEXT_LIMIT = 6
MULTI_ROUND_DENSE_CHAR_LIMIT = 120

SABER_BATCH_SYSTEM_TEMPLATE = _DEFAULT_TRANSLATION_PROMPTS["system"]

_ROUND_PROMPTS = _DEFAULT_TRANSLATION_PROMPTS["rounds"]

_PUNCT_TRANSLATION_TABLE = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
        "【": "[",
        "】": "]",
        "｛": "{",
        "｝": "}",
        "．": ".",
        "、": ",",
    }
)
_CJK_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
_LATIN_FRAGMENT_PATTERN = re.compile(r"^[A-Za-z0-9\-_./]+$")


def _build_context_block(context_snapshot):
    if not context_snapshot:
        return ""

    lines = []
    confirmed = context_snapshot.get("confirmedTranslations", []) or []
    glossary = context_snapshot.get("glossary", {}) or {}
    manga_context = str(context_snapshot.get("mangaContext") or "").strip()

    if manga_context:
        lines.append("漫画背景:")
        lines.append(manga_context)

    if confirmed:
        lines.append("邻近页确认译文:")
        lines.extend(f"- {item}" for item in confirmed if str(item or "").strip())

    if glossary:
        lines.append("术语映射:")
        lines.extend(
            f"- {original} -> {translated}"
            for original, translated in glossary.items()
            if str(original or "").strip() and str(translated or "").strip()
        )

    return "\n".join(lines).strip()


def _build_numbered_block(texts):
    return [f"<|{index}|>{text}" for index, text in enumerate(texts, start=1)]


def _build_user_lines(header, numbered_texts, context_snapshot=None, extra_sections=None):
    lines = [header, "请只输出编号译文。"]
    context_block = _build_context_block(context_snapshot)
    if context_block:
        lines.append(context_block)
    for title, section_lines in extra_sections or []:
        if not section_lines:
            continue
        lines.append(title)
        lines.extend(section_lines)
    lines.extend(_build_numbered_block(numbered_texts))
    return "\n".join(lines)


def _normalize_prompt_config(prompt_config):
    prompt_config = prompt_config or {}
    rounds = prompt_config.get("rounds") or {}
    return {
        "system": str(prompt_config.get("system") or SABER_BATCH_SYSTEM_TEMPLATE),
        "rounds": {
            "draft": str(rounds.get("draft") or _ROUND_PROMPTS["draft"]),
            "contextual": str(rounds.get("contextual") or _ROUND_PROMPTS["contextual"]),
            "final": str(rounds.get("final") or _ROUND_PROMPTS["final"]),
        },
    }


def _resolve_prompt_profile(context_snapshot):
    if not isinstance(context_snapshot, dict):
        return None

    for key in ("promptPreset", "promptProfile"):
        value = str(context_snapshot.get(key) or "").strip()
        if value:
            return value
    return None


def _resolve_prompt_config_for_context(context_snapshot):
    prompt_profile = _resolve_prompt_profile(context_snapshot)
    if prompt_profile:
        return resolve_translation_prompt_config(prompt_profile=prompt_profile)
    return resolve_translation_prompt_config()


def _resolve_translation_quality(context_snapshot):
    if not isinstance(context_snapshot, dict):
        return "high"
    value = str(context_snapshot.get("translationQuality") or "high").strip().lower()
    return value if value in {"fast", "balanced", "high"} else "high"


def _build_batch_messages(texts, context_snapshot=None, prompt_config=None):
    prompts = _normalize_prompt_config(prompt_config)
    return [
        {"role": "system", "content": prompts["system"]},
        {
            "role": "user",
            "content": _build_user_lines(
                prompts["rounds"]["draft"],
                texts,
                context_snapshot=context_snapshot,
            ),
        },
    ]


def _build_contextual_messages(texts, draft_texts, context_snapshot=None, prompt_config=None):
    prompts = _normalize_prompt_config(prompt_config)
    return [
        {"role": "system", "content": prompts["system"]},
        {
            "role": "user",
            "content": _build_user_lines(
                prompts["rounds"]["contextual"],
                texts,
                context_snapshot=context_snapshot,
                extra_sections=[
                    ("第1轮草稿:", _build_numbered_block(draft_texts)),
                ],
            ),
        },
    ]


def _build_final_messages(texts, contextual_texts, context_snapshot=None, prompt_config=None):
    prompts = _normalize_prompt_config(prompt_config)
    return [
        {"role": "system", "content": prompts["system"]},
        {
            "role": "user",
            "content": _build_user_lines(
                prompts["rounds"]["final"],
                texts,
                context_snapshot=context_snapshot,
                extra_sections=[
                    ("第2轮修订稿:", _build_numbered_block(contextual_texts)),
                ],
            ),
        },
    ]


def _clean_response_text(content):
    cleaned = re.sub(r"(</think>)?<think>.*?</think>", "", str(content or ""), flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _compact_punctuation(text):
    normalized = str(text or "").strip().translate(_PUNCT_TRANSLATION_TABLE)
    normalized = normalized.replace("......", "…").replace(".....", "…")
    normalized = normalized.replace("……", "…").replace("。。。", "…")
    normalized = re.sub(r"\.{3,}", "…", normalized)
    normalized = re.sub(r"…{2,}", "…", normalized)
    normalized = re.sub(r"\s*([,.;:!?…])\s*", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def _parse_numbered_translations(content, expected_count):
    cleaned = _clean_response_text(content)
    matches = list(re.finditer(r"<\|(\d+)\|>", cleaned))

    if not matches:
        if expected_count == 1 and cleaned:
            return [_compact_punctuation(cleaned)]
        return [TRANSLATION_FAILURE_TEXT] * expected_count

    translations = [TRANSLATION_FAILURE_TEXT] * expected_count
    for index, match in enumerate(matches):
        item_number = int(match.group(1)) - 1
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        if 0 <= item_number < expected_count:
            value = cleaned[start:end].strip()
            translations[item_number] = _compact_punctuation(value) if value else TRANSLATION_FAILURE_TEXT

    return translations


def _normalize_usage(usage, messages, content):
    def _read(value, *names):
        for name in names:
            if isinstance(value, dict) and name in value:
                return value[name]
            if hasattr(value, name):
                return getattr(value, name)
        return None

    prompt_tokens = _read(usage, "prompt_tokens", "input_tokens", "inputTokens")
    completion_tokens = _read(usage, "completion_tokens", "output_tokens", "outputTokens")
    total_tokens = _read(usage, "total_tokens", "totalTokens")

    estimated = False
    if prompt_tokens is None:
        prompt_chars = sum(len(str(item.get("content") or "")) for item in messages or [])
        prompt_tokens = max(1, round(prompt_chars / 4))
        estimated = True
    if completion_tokens is None:
        completion_tokens = max(1, round(len(str(content or "")) / 4))
        estimated = True
    if total_tokens is None:
        total_tokens = int(prompt_tokens) + int(completion_tokens)
        estimated = True

    return {
        "inputTokens": int(prompt_tokens),
        "outputTokens": int(completion_tokens),
        "totalTokens": int(total_tokens),
        "estimated": bool(estimated),
    }


def _sum_usage(usages):
    total = {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "estimated": False,
    }
    for usage in usages:
        usage = usage or {}
        total["inputTokens"] += int(usage.get("inputTokens", 0) or 0)
        total["outputTokens"] += int(usage.get("outputTokens", 0) or 0)
        total["totalTokens"] += int(usage.get("totalTokens", 0) or 0)
        total["estimated"] = total["estimated"] or bool(usage.get("estimated"))
    return total


def _empty_usage():
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "estimated": False,
    }


def _default_ocr_retry_state():
    return {
        "shouldRetry": False,
        "reasons": [],
        "attempted": False,
        "applied": False,
    }


def _should_fallback_via_curl(error):
    if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if type(error) is openai.APIError:
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and status_code >= 500


def _normalize_ocr_retry_state(payload):
    state = _default_ocr_retry_state()
    if isinstance(payload, dict):
        state["shouldRetry"] = bool(payload.get("shouldRetry"))
        state["attempted"] = bool(payload.get("attempted"))
        state["applied"] = bool(payload.get("applied"))
        reasons = payload.get("reasons") or []
        state["reasons"] = [str(item) for item in reasons if str(item or "").strip()]
    return state


def _merge_slot_results(total_count, non_empty_items, batch_results):
    merged = [""] * total_count
    for (index, _), translated_text in zip(non_empty_items, batch_results):
        merged[index] = translated_text
    return merged


def _extract_non_empty_items(texts):
    return [(index, text) for index, text in enumerate(texts or []) if str(text or "").strip()]


def _chunk_non_empty_items(non_empty_items, chunk_size):
    chunk_size = max(1, int(chunk_size or 1))
    for index in range(0, len(non_empty_items), chunk_size):
        yield non_empty_items[index : index + chunk_size]


def _looks_like_latin_fragment(text):
    candidate = str(text or "").strip()
    if not candidate or _CJK_PATTERN.search(candidate):
        return False
    if len(candidate) > 8:
        return False
    return bool(_LATIN_FRAGMENT_PATTERN.fullmatch(candidate))


def _count_non_empty_chars(non_empty_items):
    return sum(len(str(text or "").strip()) for _, text in non_empty_items)


def _analyze_ocr_retry(original_texts, translated_texts):
    state = _default_ocr_retry_state()
    non_empty_originals = [str(text or "").strip() for text in original_texts or [] if str(text or "").strip()]
    non_empty_translations = [str(text or "").strip() for text in translated_texts or [] if str(text or "").strip()]

    if not non_empty_originals:
        return state

    reasons = []
    latin_like_count = 0
    for original_text, translated_text in zip(original_texts or [], translated_texts or []):
        original_value = str(original_text or "").strip()
        translated_value = str(translated_text or "").strip()
        if _looks_like_latin_fragment(original_value) and (
            not translated_value or translated_value == original_value or _looks_like_latin_fragment(translated_value)
        ):
            latin_like_count += 1

    if latin_like_count >= max(1, len(non_empty_originals) // 2):
        reasons.append("too_many_latin_fragments")

    failure_count = sum(1 for text in non_empty_translations if text == TRANSLATION_FAILURE_TEXT)
    if failure_count >= max(1, len(non_empty_originals) // 2):
        reasons.append("translation_failed")

    if reasons:
        state["shouldRetry"] = True
        state["reasons"] = reasons
    return state


class OpenAICompatibleTranslator:
    def translate_texts(self, texts, model, base_url, api_key=None, context_snapshot=None):
        non_empty_items = _extract_non_empty_items(texts)
        translated = [""] * len(texts or [])
        if not non_empty_items:
            return translated

        prompt_config = _resolve_prompt_config_for_context(context_snapshot)
        batch_texts = [text for _, text in non_empty_items]
        parsed, _usage = self._run_round(
            model=model,
            base_url=base_url,
            api_key=api_key,
            messages=_build_batch_messages(
                batch_texts,
                context_snapshot=context_snapshot,
                prompt_config=prompt_config,
            ),
            expected_count=len(batch_texts),
        )
        return _merge_slot_results(len(texts or []), non_empty_items, parsed)

    def translate_texts_with_metadata(self, texts, model, base_url, api_key=None, context_snapshot=None):
        total_count = len(texts or [])
        non_empty_items = _extract_non_empty_items(texts)
        final_texts = [""] * total_count
        translation_quality = _resolve_translation_quality(context_snapshot)
        if not non_empty_items:
            empty_rounds = [
                {"name": name, "translatedTexts": list(final_texts), "usage": _empty_usage()}
                for name in self._round_names_for_quality(translation_quality)
            ]
            return {
                "translatedTexts": final_texts,
                "rounds": empty_rounds,
                "tokenUsage": _empty_usage(),
                "ocrRetry": _default_ocr_retry_state(),
            }

        dense_batch = (
            len(non_empty_items) > MULTI_ROUND_DENSE_TEXT_LIMIT
            or _count_non_empty_chars(non_empty_items) > MULTI_ROUND_DENSE_CHAR_LIMIT
        )
        if translation_quality == "fast" or (translation_quality == "high" and dense_batch):
            return self._translate_dense_batch_with_single_round(
                texts=texts,
                non_empty_items=non_empty_items,
                model=model,
                base_url=base_url,
                api_key=api_key,
                context_snapshot=context_snapshot,
            )
        if translation_quality == "balanced":
            return self._translate_balanced_batch(
                texts=texts,
                non_empty_items=non_empty_items,
                model=model,
                base_url=base_url,
                api_key=api_key,
                context_snapshot=context_snapshot,
            )

        prompt_config = _resolve_prompt_config_for_context(context_snapshot)
        draft_full = [""] * total_count
        contextual_full = [""] * total_count
        final_texts = [""] * total_count
        draft_usages = []
        contextual_usages = []
        final_usages = []

        for chunk_items in _chunk_non_empty_items(non_empty_items, MULTI_ROUND_MAX_TEXTS):
            batch_texts = [text for _, text in chunk_items]

            draft_texts, draft_usage = self._run_round(
                model=model,
                base_url=base_url,
                api_key=api_key,
                messages=_build_batch_messages(
                    batch_texts,
                    context_snapshot=context_snapshot,
                    prompt_config=prompt_config,
                ),
                expected_count=len(batch_texts),
            )
            for (slot_index, _), translated_text in zip(chunk_items, draft_texts):
                draft_full[slot_index] = translated_text
            draft_usages.append(draft_usage)

            contextual_texts, contextual_usage = self._run_round(
                model=model,
                base_url=base_url,
                api_key=api_key,
                messages=_build_contextual_messages(
                    batch_texts,
                    draft_texts,
                    context_snapshot=context_snapshot,
                    prompt_config=prompt_config,
                ),
                expected_count=len(batch_texts),
            )
            for (slot_index, _), translated_text in zip(chunk_items, contextual_texts):
                contextual_full[slot_index] = translated_text
            contextual_usages.append(contextual_usage)

            final_batch_texts, final_usage = self._run_round(
                model=model,
                base_url=base_url,
                api_key=api_key,
                messages=_build_final_messages(
                    batch_texts,
                    contextual_texts,
                    context_snapshot=context_snapshot,
                    prompt_config=prompt_config,
                ),
                expected_count=len(batch_texts),
            )
            for (slot_index, _), translated_text in zip(chunk_items, final_batch_texts):
                final_texts[slot_index] = translated_text
            final_usages.append(final_usage)

        rounds = [
            {"name": "draft", "translatedTexts": draft_full, "usage": _sum_usage(draft_usages)},
            {"name": "contextual", "translatedTexts": contextual_full, "usage": _sum_usage(contextual_usages)},
            {"name": "final", "translatedTexts": final_texts, "usage": _sum_usage(final_usages)},
        ]

        return {
            "translatedTexts": final_texts,
            "rounds": rounds,
            "tokenUsage": _sum_usage(draft_usages + contextual_usages + final_usages),
            "ocrRetry": _analyze_ocr_retry(texts or [], final_texts),
        }

    def _round_names_for_quality(self, translation_quality):
        if translation_quality == "fast":
            return ["final"]
        if translation_quality == "balanced":
            return ["draft", "final"]
        return ["draft", "contextual", "final"]

    def _translate_balanced_batch(self, *, texts, non_empty_items, model, base_url, api_key, context_snapshot):
        prompt_config = _resolve_prompt_config_for_context(context_snapshot)
        total_count = len(texts or [])
        draft_full = [""] * total_count
        final_texts = [""] * total_count
        draft_usages = []
        final_usages = []

        for chunk_items in _chunk_non_empty_items(non_empty_items, MULTI_ROUND_MAX_TEXTS):
            batch_texts = [text for _, text in chunk_items]
            draft_texts, draft_usage = self._run_round(
                model=model,
                base_url=base_url,
                api_key=api_key,
                messages=_build_batch_messages(
                    batch_texts,
                    context_snapshot=context_snapshot,
                    prompt_config=prompt_config,
                ),
                expected_count=len(batch_texts),
            )
            for (slot_index, _), translated_text in zip(chunk_items, draft_texts):
                draft_full[slot_index] = translated_text
            draft_usages.append(draft_usage)

            final_batch_texts, final_usage = self._run_round(
                model=model,
                base_url=base_url,
                api_key=api_key,
                messages=_build_final_messages(
                    batch_texts,
                    draft_texts,
                    context_snapshot=context_snapshot,
                    prompt_config=prompt_config,
                ),
                expected_count=len(batch_texts),
            )
            for (slot_index, _), translated_text in zip(chunk_items, final_batch_texts):
                final_texts[slot_index] = translated_text
            final_usages.append(final_usage)

        return {
            "translatedTexts": final_texts,
            "rounds": [
                {"name": "draft", "translatedTexts": draft_full, "usage": _sum_usage(draft_usages)},
                {"name": "final", "translatedTexts": final_texts, "usage": _sum_usage(final_usages)},
            ],
            "tokenUsage": _sum_usage(draft_usages + final_usages),
            "ocrRetry": _analyze_ocr_retry(texts or [], final_texts),
        }

    def _translate_dense_batch_with_single_round(self, *, texts, non_empty_items, model, base_url, api_key, context_snapshot):
        prompt_config = _resolve_prompt_config_for_context(context_snapshot)
        batch_texts = [text for _, text in non_empty_items]
        final_batch_texts, final_usage = self._run_round(
            model=model,
            base_url=base_url,
            api_key=api_key,
            messages=_build_batch_messages(
                batch_texts,
                context_snapshot=context_snapshot,
                prompt_config=prompt_config,
            ),
            expected_count=len(batch_texts),
        )
        final_texts = _merge_slot_results(len(texts or []), non_empty_items, final_batch_texts)
        return {
            "translatedTexts": final_texts,
            "rounds": [
                {
                    "name": "final",
                    "translatedTexts": final_texts,
                    "usage": final_usage,
                }
            ],
            "tokenUsage": final_usage,
            "ocrRetry": _analyze_ocr_retry(texts or [], final_texts),
        }

    def _run_round(self, *, model, base_url, api_key, messages, expected_count):
        content, usage = self._request_completion(
            model=model,
            base_url=base_url,
            api_key=api_key,
            messages=messages,
        )
        parsed = _parse_numbered_translations(content, expected_count)
        return parsed, _normalize_usage(usage, messages, content)

    def _request_completion(self, *, model, base_url, api_key, messages):
        translation = resolve_translation_config()
        resolved_api_key = str(api_key if api_key is not None else translation["api_key"]).strip()
        request_timeout_seconds = float(translation["request_timeout_seconds"] or REQUEST_TIMEOUT_SECONDS)
        client = openai.OpenAI(api_key=resolved_api_key or "dummy", base_url=base_url)
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                timeout=request_timeout_seconds,
                temperature=0,
            )
            content = ((completion.choices or [None])[0].message.content or "").strip()
            return content, getattr(completion, "usage", None)
        except openai.APIError as error:
            if not _should_fallback_via_curl(error):
                raise
            return self._request_completion_via_curl(
                model=model,
                base_url=base_url,
                api_key=resolved_api_key,
                messages=messages,
            )

    def _request_completion_via_curl(self, *, model, base_url, api_key, messages):
        translation = resolve_translation_config()
        url = f"{str(base_url or '').rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
        }
        command = [
            "curl.exe",
            "-sS",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
        ]
        if str(api_key or "").strip():
            command.extend(["-H", f"Authorization: Bearer {api_key}"])
        command.extend(
            [
                "-d",
                json.dumps(payload, ensure_ascii=False),
            ]
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(translation["curl_timeout_seconds"] or _CURL_TIMEOUT_SECONDS),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "curl translation request failed")

        response = json.loads(result.stdout or "{}")
        choices = response.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        return str(message.get("content") or "").strip(), response.get("usage")
