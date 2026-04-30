from __future__ import annotations


def empty_usage():
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "estimated": False,
    }


def default_ocr_retry_state():
    return {
        "shouldRetry": False,
        "reasons": [],
        "attempted": False,
        "applied": False,
    }


def normalize_ocr_retry_state(payload):
    state = default_ocr_retry_state()
    if not isinstance(payload, dict):
        return state

    state["shouldRetry"] = bool(payload.get("shouldRetry"))
    state["attempted"] = bool(payload.get("attempted"))
    state["applied"] = bool(payload.get("applied"))
    state["reasons"] = [str(item) for item in (payload.get("reasons") or []) if str(item or "").strip()]
    return state


def build_legacy_translation_payload(translated_texts):
    texts = list(translated_texts or [])
    return {
        "translatedTexts": texts,
        "rounds": [
            {
                "name": "final",
                "translatedTexts": texts,
                "usage": empty_usage(),
            }
        ],
        "tokenUsage": empty_usage(),
        "ocrRetry": default_ocr_retry_state(),
    }


def normalize_translation_payload(payload, translated_texts=None):
    if not isinstance(payload, dict):
        fallback_texts = translated_texts if translated_texts is not None else payload or []
        return build_legacy_translation_payload(fallback_texts)

    normalized_texts = list(payload.get("translatedTexts") or translated_texts or [])
    rounds = []
    for item in payload.get("rounds") or []:
        if not isinstance(item, dict):
            continue
        rounds.append(
            {
                "name": item.get("name") or "final",
                "translatedTexts": list(item.get("translatedTexts") or []),
                "usage": dict(item.get("usage") or empty_usage()),
            }
        )
    if not rounds:
        rounds = [
            {
                "name": "final",
                "translatedTexts": normalized_texts,
                "usage": empty_usage(),
            }
        ]

    return {
        "translatedTexts": normalized_texts,
        "rounds": rounds,
        "tokenUsage": dict(payload.get("tokenUsage") or empty_usage()),
        "ocrRetry": normalize_ocr_retry_state(payload.get("ocrRetry")),
    }
