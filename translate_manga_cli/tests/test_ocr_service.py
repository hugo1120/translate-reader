from src.core.ocr.service import ocr_page


def test_ocr_page_passes_hybrid_ocr_payload_to_saber(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload, session=None):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["session"] = session
        return {
            "originalTexts": ["こんにちは"],
            "ocrResults": [{"text": "こんにちは", "engine": "48px_ocr"}],
        }

    monkeypatch.setattr("src.core.ocr.service.run_saber_task", fake_run_saber_task)
    monkeypatch.setattr("src.core.ocr.service.has_saber_48px_color_model", lambda: True, raising=False)

    result = ocr_page(
        "demo.png",
        [[10, 20, 40, 60]],
        [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
    )

    assert result["originalTexts"] == ["こんにちは"]
    assert captured["operation"] == "ocr"
    assert captured["payload"] == {
        "image_path": "demo.png",
        "bubble_coords": [[10, 20, 40, 60]],
        "textlines_per_bubble": [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
        "ocr_engine": "48px_ocr",
        "enable_hybrid_ocr": True,
        "secondary_ocr_engine": "manga_ocr",
        "hybrid_ocr_threshold": 0.2,
    }
