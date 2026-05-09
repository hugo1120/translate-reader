def build_context_snapshot(pages, results_by_page, current_page_id, window=3):
    page_ids = [page["id"] for page in pages]
    if current_page_id not in page_ids:
        return {
            "historyPageIds": [],
            "confirmedTranslations": [],
            "glossary": {},
            "mangaContext": "",
        }

    current_index = page_ids.index(current_page_id)
    history_ids = page_ids[max(0, current_index - window) : current_index]
    confirmed = []
    glossary = {}

    for page_id in history_ids:
        result = results_by_page.get(page_id) or {}
        bubble_states = result.get("bubbleStates") or result.get("bubbles") or []
        for bubble in bubble_states:
            original = (bubble.get("originalText") or "").strip()
            translated = (bubble.get("translatedText") or "").strip()
            if not translated:
                continue
            confirmed.append(translated)
            if result.get("manualEdited") and original:
                glossary[original] = translated

    return {
        "historyPageIds": history_ids,
        "confirmedTranslations": confirmed,
        "glossary": glossary,
        "mangaContext": "",
    }
