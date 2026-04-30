from src.core.editing.service import rerender_single_bubble, update_bubble_state


def test_rerender_single_bubble_updates_only_target_index(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return {"translatedImagePath": "page.translated.png", "bubbleStates": payload["bubble_states"]}

    monkeypatch.setattr("src.core.editing.service.run_saber_task", fake_run_saber_task)

    result = rerender_single_bubble(
        clean_image_path="clean.png",
        translated_image_path="page.translated.png",
        bubble_states=[{"translatedText": "A"}, {"translatedText": "B2"}],
        bubble_index=1,
    )

    assert captured["operation"] == "render_single"
    assert captured["payload"]["bubble_index"] == 1
    assert result["bubbleStates"][1]["translatedText"] == "B2"


def test_update_bubble_state_marks_result_manual_and_syncs_aliases():
    result = update_bubble_state(
        {
            "bubbleCoords": [[10, 20, 60, 90]],
            "translatedTexts": ["旧译文"],
            "bubbleStates": [{"coords": [10, 20, 60, 90], "translatedText": "旧译文"}],
        },
        bubble_index=0,
        patch={"coords": [12, 24, 64, 96], "translatedText": "新译文"},
    )

    assert result["manualEdited"] is True
    assert result["bubbleStates"][0]["coords"] == [12, 24, 64, 96]
    assert result["bubbles"][0]["translatedText"] == "新译文"
    assert result["bubbleCoords"][0] == [12, 24, 64, 96]
    assert result["translatedTexts"][0] == "新译文"


def test_rerender_single_bubble_does_not_call_detect_or_translate(monkeypatch):
    called = {"detect": 0, "translate": 0}

    def fake_detect(*args, **kwargs):
        called["detect"] += 1

    def fake_translate(*args, **kwargs):
        called["translate"] += 1

    monkeypatch.setattr("src.core.editing.service.detect_page", fake_detect, raising=False)
    monkeypatch.setattr("src.core.editing.service.translate_texts", fake_translate, raising=False)
    monkeypatch.setattr(
        "src.core.editing.service.run_saber_task",
        lambda operation, payload: {"translatedImagePath": "page.translated.png", "bubbleStates": payload["bubble_states"]},
    )

    rerender_single_bubble(
        clean_image_path="clean.png",
        translated_image_path="page.translated.png",
        bubble_states=[{"translatedText": "A"}],
        bubble_index=0,
    )

    assert called["detect"] == 0
    assert called["translate"] == 0
