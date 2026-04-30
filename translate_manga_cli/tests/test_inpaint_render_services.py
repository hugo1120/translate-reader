from src.core.color.service import extract_bubble_colors
from src.core.inpaint.service import inpaint_page
from src.core.render.service import render_page


def test_inpaint_page_delegates_to_saber(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return {"cleanImagePath": "D:/cache/page-0001.clean.png"}

    monkeypatch.setattr("src.core.inpaint.service.run_saber_task", fake_run_saber_task)

    result = inpaint_page(
        image_path="D:/pages/source.png",
        bubble_coords=[[10, 20, 40, 60]],
        raw_mask="mask-base64",
        bubble_polygons=[[[10, 20], [40, 20], [40, 60], [10, 60]]],
        output_path="D:/cache/page-0001.clean.png",
        method="solid",
        mask_dilate_size=2,
        mask_box_expand_ratio=8,
    )

    assert result == {"cleanImagePath": "D:/cache/page-0001.clean.png"}
    assert captured["operation"] == "inpaint"
    assert captured["payload"]["image_path"] == "D:/pages/source.png"
    assert captured["payload"]["output_path"] == "D:/cache/page-0001.clean.png"
    assert captured["payload"]["bubble_coords"] == [[10, 20, 40, 60]]
    assert captured["payload"]["raw_mask"] == "mask-base64"
    assert captured["payload"]["bubble_polygons"] == [[[10, 20], [40, 20], [40, 60], [10, 60]]]
    assert captured["payload"]["method"] == "solid"
    assert captured["payload"]["mask_dilate_size"] == 2
    assert captured["payload"]["mask_box_expand_ratio"] == 8


def test_render_page_delegates_to_saber(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return {"translatedImagePath": "D:/cache/page-0001.translated.png"}

    monkeypatch.setattr("src.core.render.service.run_saber_task", fake_run_saber_task)

    bubbles = [
        {
            "coords": [10, 20, 40, 60],
            "polygon": [[10, 20], [40, 20], [40, 60], [10, 60]],
            "direction": "vertical",
            "textlines": [],
            "originalText": "さあ",
            "translatedText": "来吧",
            "ocrResult": {"text": "さあ", "engine": "manga_ocr"},
        }
    ]

    result = render_page(
        clean_image_path="D:/cache/page-0001.clean.png",
        page_id="page-0001",
        bubbles=bubbles,
        output_path="D:/cache/page-0001.translated.png",
    )

    assert result == {"translatedImagePath": "D:/cache/page-0001.translated.png"}
    assert captured["operation"] == "render"
    assert captured["payload"]["clean_image_path"] == "D:/cache/page-0001.clean.png"
    assert captured["payload"]["page_id"] == "page-0001"
    assert captured["payload"]["output_path"] == "D:/cache/page-0001.translated.png"
    assert captured["payload"]["bubbles"] == bubbles
    assert captured["payload"]["auto_font_size"] is True


def test_extract_bubble_colors_delegates_to_saber(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return {
            "colors": [
                {
                    "textColor": "#101010",
                    "bgColor": "#fefefe",
                    "autoFgColor": [16, 16, 16],
                    "autoBgColor": [254, 254, 254],
                    "colorConfidence": 0.92,
                }
            ]
        }

    monkeypatch.setattr("src.core.color.service.has_saber_48px_color_model", lambda: True)
    monkeypatch.setattr("src.core.color.service.run_saber_task", fake_run_saber_task)

    result = extract_bubble_colors(
        image_path="D:/pages/source.png",
        bubble_coords=[[10, 20, 40, 60]],
        textlines_per_bubble=[[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
    )

    assert result["colors"][0]["textColor"] == "#101010"
    assert captured["operation"] == "color"
    assert captured["payload"]["image_path"] == "D:/pages/source.png"
    assert captured["payload"]["bubble_coords"] == [[10, 20, 40, 60]]
    assert captured["payload"]["textlines_per_bubble"] == [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]]


def test_extract_bubble_colors_returns_empty_colors_when_48px_model_missing(monkeypatch):
    monkeypatch.setattr("src.core.color.service.has_saber_48px_color_model", lambda: False)

    result = extract_bubble_colors(
        image_path="D:/pages/source.png",
        bubble_coords=[[10, 20, 40, 60], [50, 60, 80, 100]],
        textlines_per_bubble=[[], []],
    )

    assert result == {
        "colors": [
            {
                "textColor": None,
                "bgColor": None,
                "autoFgColor": None,
                "autoBgColor": None,
                "colorConfidence": 0.0,
            },
            {
                "textColor": None,
                "bgColor": None,
                "autoFgColor": None,
                "autoBgColor": None,
                "colorConfidence": 0.0,
            },
        ]
    }
