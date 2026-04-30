from copy import deepcopy

from src.integrations.saber_loader import run_saber_task


def _clone_bubble_states(result_payload):
    bubble_states = result_payload.get("bubbleStates") or result_payload.get("bubbles") or []
    return [deepcopy(item) for item in bubble_states]


def _sync_list_field(payload, key, bubble_index, value):
    items = list(payload.get(key, []) or [])
    while len(items) <= bubble_index:
        items.append(None)
    items[bubble_index] = value
    payload[key] = items


def update_bubble_state(result_payload, bubble_index, patch):
    updated = deepcopy(result_payload)
    bubble_states = _clone_bubble_states(updated)
    if bubble_index < 0 or bubble_index >= len(bubble_states):
        raise IndexError(f"bubble index out of range: {bubble_index}")

    bubble_states[bubble_index] = {**bubble_states[bubble_index], **(patch or {})}
    current = bubble_states[bubble_index]

    updated["bubbleStates"] = bubble_states
    updated["bubbles"] = bubble_states
    updated["manualEdited"] = True

    if "coords" in current:
        _sync_list_field(updated, "bubbleCoords", bubble_index, current.get("coords"))
    if "polygon" in current:
        _sync_list_field(updated, "bubblePolygons", bubble_index, current.get("polygon"))
    if "translatedText" in current:
        _sync_list_field(updated, "translatedTexts", bubble_index, current.get("translatedText"))
    if "originalText" in current:
        _sync_list_field(updated, "originalTexts", bubble_index, current.get("originalText"))

    return updated


def rerender_single_bubble(clean_image_path, translated_image_path, bubble_states, bubble_index):
    return run_saber_task(
        "render_single",
        {
            "clean_image_path": clean_image_path,
            "output_path": translated_image_path,
            "bubble_states": bubble_states,
            "bubble_index": bubble_index,
        },
    )
