from pathlib import Path

from PIL import Image, ImageChops

from src.core.pipeline.service import _build_bubbles, preprocess_page, run_page_pipeline


def test_build_bubbles_applies_cli_readability_profile(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "horizontal",
                "font_family": "fonts/思源黑体SourceHanSansK-Bold.TTF",
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "line_spacing": 0.84,
                "text_align": "center",
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
        ["来吧"],
    )

    bubble = bubbles[0]

    assert bubble["fontFamily"] == "fonts/思源黑体SourceHanSansK-Bold.TTF"
    assert bubble["strokeEnabled"] is True
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 1
    assert bubble["lineSpacing"] == 0.84
    assert bubble["textAlign"] == "center"


def test_build_bubbles_normalizes_short_direction_codes_for_rendering(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "auto",
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 40, 60], [50, 20, 120, 60]],
            "bubblePolygons": [
                [[10, 20], [40, 20], [40, 60], [10, 60]],
                [[50, 20], [120, 20], [120, 60], [50, 60]],
            ],
            "autoDirections": ["v", "h"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["さあ", "えっ"],
            "ocrResults": [
                {"text": "さあ", "engine": "manga_ocr"},
                {"text": "えっ", "engine": "manga_ocr"},
            ],
        },
        ["来吧", "诶"],
    )

    assert bubbles[0]["direction"] == "vertical"
    assert bubbles[0]["textDirection"] == "vertical"
    assert bubbles[0]["autoTextDirection"] == "vertical"
    assert bubbles[1]["direction"] == "horizontal"
    assert bubbles[1]["textDirection"] == "horizontal"
    assert bubbles[1]["autoTextDirection"] == "horizontal"


def test_build_bubbles_respects_forced_layout_mode(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "horizontal",
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 40, 60], [50, 20, 120, 60]],
            "bubblePolygons": [
                [[10, 20], [40, 20], [40, 60], [10, 60]],
                [[50, 20], [120, 20], [120, 60], [50, 60]],
            ],
            "autoDirections": ["v", "v"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["さあ", "えっ"],
            "ocrResults": [
                {"text": "さあ", "engine": "manga_ocr"},
                {"text": "えっ", "engine": "manga_ocr"},
            ],
        },
        ["来吧", "诶"],
    )

    assert [bubble["textDirection"] for bubble in bubbles] == ["horizontal", "horizontal"]
    assert [bubble["autoTextDirection"] for bubble in bubbles] == ["vertical", "vertical"]


def test_build_bubbles_uses_vertical_layout2_profile(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "font_family": "fonts/思源黑体SourceHanSansK-Bold.TTF",
                "line_spacing": 0.84,
                "vertical_layout": {
                    "font_family": "fonts/汉仪正圆-65W.TTF",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 80, 160]],
            "bubblePolygons": [[[10, 20], [80, 20], [80, 160], [10, 160]]],
            "autoDirections": ["v"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["ほんとに 正確です なあ"],
            "ocrResults": [{"text": "ほんとに 正確です なあ", "engine": "48px_ocr"}],
        },
        ["真是准确啊"],
    )

    bubble = bubbles[0]
    assert bubble["textDirection"] == "vertical"
    assert bubble["fontFamily"] == "fonts/汉仪正圆-65W.TTF"
    assert bubble["lineSpacing"] == 1.04
    assert bubble["layoutProfile"] == "vertical_layout2"


def test_build_bubbles_uses_vertical_style_when_auto_layout_resolves_to_vertical(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "auto",
                "font_family": "fonts/思源黑体SourceHanSansK-Bold.TTF",
                "line_spacing": 0.84,
                "vertical_layout": {
                    "font_family": "fonts/汉仪正圆-65W.TTF",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 80, 160]],
            "bubblePolygons": [[[10, 20], [80, 20], [80, 160], [10, 160]]],
            "autoDirections": ["v"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["ほんとに 正確です なあ"],
            "ocrResults": [{"text": "ほんとに 正確です なあ", "engine": "48px_ocr"}],
        },
        ["真是准确啊"],
    )

    bubble = bubbles[0]
    assert bubble["textDirection"] == "vertical"
    assert bubble["fontFamily"] == "fonts/汉仪正圆-65W.TTF"
    assert bubble["lineSpacing"] == 1.04
    assert bubble["layoutProfile"] == "vertical_layout2"


def test_resolve_auto_font_settings_uses_vertical_layout2_profile(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "auto_font": {
                    "min_size": 16,
                    "max_size": 72,
                    "padding_ratio": 0.96,
                },
                "vertical_layout": {
                    "auto_font": {
                        "min_size": 14,
                        "max_size": 60,
                        "padding_ratio": 0.86,
                    }
                },
            }
        },
    )

    from src.core.pipeline.service import _resolve_auto_font_settings

    settings = _resolve_auto_font_settings()
    assert settings == {
        "min_size": 14,
        "max_size": 60,
        "padding_ratio": 0.86,
    }


def test_resolve_watermark_style_uses_new_default_text():
    from src.core.pipeline.service import _resolve_watermark_style

    style = _resolve_watermark_style()
    assert style["text"] == "HUGO2233汉化"


def test_build_bubbles_uses_dark_background_adaptive_style():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#eeeeee",
                    "bgColor": "#111111",
                    "autoFgColor": [238, 238, 238],
                    "autoBgColor": [17, 17, 17],
                    "colorConfidence": 0.95,
                }
            ],
        },
        {
            "originalTexts": ["欲望の行方"],
            "ocrResults": [{"text": "欲望の行方", "engine": "48px_ocr"}],
        },
        ["欲望的去向"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#FFFFFF"
    assert bubble["strokeColor"] == "#000000"
    assert bubble["strokeWidth"] == 1


def test_build_bubbles_disables_stroke_for_light_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#f8f8f8",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [248, 248, 248],
                    "colorConfidence": 0.95,
                }
            ],
        },
        {
            "originalTexts": ["毎朝早い"],
            "ocrResults": [{"text": "毎朝早い", "engine": "48px_ocr"}],
        },
        ["每天都起得早"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 0


def test_build_bubbles_falls_back_to_black_text_when_fg_bg_are_same_dark_color():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#020201",
                    "bgColor": "#020201",
                    "autoFgColor": [2, 2, 1],
                    "autoBgColor": [2, 2, 1],
                    "colorConfidence": 0.99,
                }
            ],
        },
        {
            "originalTexts": ["ほんとに 正確です なあ"],
            "ocrResults": [{"text": "ほんとに 正確です なあ", "engine": "48px_ocr"}],
        },
        ["真是准确啊"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 0


def test_build_bubbles_disables_stroke_for_tiny_boxes():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 34, 44]],
            "bubblePolygons": [[[10, 20], [34, 20], [34, 44], [10, 44]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#f4f4f4",
                    "bgColor": "#101010",
                    "autoFgColor": [244, 244, 244],
                    "autoBgColor": [16, 16, 16],
                    "colorConfidence": 0.91,
                }
            ],
        },
        {
            "originalTexts": ["第1話"],
            "ocrResults": [{"text": "第1話", "engine": "48px_ocr"}],
        },
        ["第1话"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#FFFFFF"
    assert bubble["strokeColor"] == "#000000"
    assert bubble["strokeWidth"] == 0


def test_preprocess_page_uses_single_saber_call_and_filters_payload(tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "page.png"
    Image.new("RGB", (794, 1200), "white").save(source_path)

    def fake_run_saber_task(operation, payload, session=None):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["session"] = session
        return {
            "bubbleCoords": [[385, 83, 400, 119], [276, 92, 281, 101], [49, 1135, 70, 1155]],
            "bubblePolygons": [
                [[385, 83], [400, 83], [400, 119], [385, 119]],
                [[276, 92], [281, 92], [281, 101], [276, 101]],
                [[49, 1135], [70, 1135], [70, 1155], [49, 1155]],
            ],
            "autoDirections": ["vertical", "vertical", "vertical"],
            "textlinesPerBubble": [[], [], []],
            "rawMask": None,
            "originalTexts": ["ん？", "", "13"],
            "ocrResults": [
                {"text": "ん？", "engine": "manga_ocr"},
                {"text": "", "engine": "manga_ocr"},
                {"text": "13", "engine": "manga_ocr"},
            ],
            "colors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#ffffff",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [255, 255, 255],
                    "colorConfidence": 0.91,
                },
                {
                    "textColor": "#222222",
                    "bgColor": "#f5f5f5",
                    "autoFgColor": [34, 34, 34],
                    "autoBgColor": [245, 245, 245],
                    "colorConfidence": 0.66,
                },
            ],
        }

    monkeypatch.setattr("src.core.pipeline.service.run_saber_task", fake_run_saber_task)
    monkeypatch.setattr(
        "src.core.pipeline.service.resolve_saber_ocr_options",
        lambda: {
            "ocr_engine": "48px_ocr",
            "enable_hybrid_ocr": True,
            "secondary_ocr_engine": "manga_ocr",
            "hybrid_ocr_threshold": 0.2,
        },
    )

    result = preprocess_page(str(source_path), saber_session="session-token")

    assert captured["operation"] == "preprocess"
    assert captured["payload"] == {
        "image_path": str(source_path),
        "ocr_engine": "48px_ocr",
        "enable_hybrid_ocr": True,
        "secondary_ocr_engine": "manga_ocr",
        "hybrid_ocr_threshold": 0.2,
    }
    assert captured["session"] == "session-token"
    assert result["bubbleCoords"] == [[385, 83, 400, 119]]
    assert result["originalTexts"] == ["ん？"]
    assert result["bubbleColors"] == [
        {
            "textColor": "#111111",
            "bgColor": "#ffffff",
            "autoFgColor": [17, 17, 17],
            "autoBgColor": [255, 255, 255],
            "colorConfidence": 0.91,
        }
    ]


def test_run_page_pipeline_uses_cache_output_paths(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "source.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda project_root=None: {
            "render": {
                "layout_mode": "horizontal",
                "auto_font": {
                    "min_size": 16,
                    "max_size": 72,
                    "padding_ratio": 0.96,
                },
            }
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda source_path, bubble_coords: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts",
        lambda texts, model, base_url: ["来吧"],
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.extract_bubble_colors",
        lambda source_path, bubble_coords, textlines_per_bubble: {
            "colors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#f9f9f9",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [249, 249, 249],
                    "colorConfidence": 0.88,
                }
            ]
        },
    )

    def fake_inpaint_page(
        image_path,
        bubble_coords,
        raw_mask=None,
        bubble_polygons=None,
        output_path=None,
        method="solid",
        saber_session=None,
    ):
        captured["inpaint"] = {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "bubble_polygons": bubble_polygons,
            "output_path": output_path,
            "method": method,
            "saber_session": saber_session,
        }
        return {"cleanImagePath": output_path}

    def fake_render_page(
        clean_image_path,
        page_id,
        bubbles,
        output_path=None,
        auto_font_size=True,
        auto_font_settings=None,
        saber_session=None,
    ):
        captured["render"] = {
            "clean_image_path": clean_image_path,
            "page_id": page_id,
            "bubbles": bubbles,
            "output_path": output_path,
            "auto_font_size": auto_font_size,
            "auto_font_settings": auto_font_settings,
            "saber_session": saber_session,
        }
        return {"translatedImagePath": output_path}

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("src.core.pipeline.service.render_page", fake_render_page)

    result = run_page_pipeline(app, "page-0001", str(source_path))

    page_cache_dir = Path(app.config["CACHE_ROOT"]) / "pages" / "page-0001"
    assert result["cleanImagePath"] == str(page_cache_dir / "page-0001.clean.png")
    assert result["translatedImagePath"] == str(page_cache_dir / "page-0001.translated.png")
    assert captured["inpaint"]["output_path"] == str(page_cache_dir / "page-0001.clean.png")
    assert captured["render"]["output_path"] == str(page_cache_dir / "page-0001.translated.png")
    assert captured["render"]["auto_font_size"] is True
    assert captured["render"]["auto_font_settings"] == {
        "min_size": 16,
        "max_size": 72,
        "padding_ratio": 0.96,
    }
    assert captured["render"]["bubbles"][0]["translatedText"] == "来吧"
    assert captured["render"]["bubbles"][0]["polygon"] == [[10, 20], [40, 20], [40, 60], [10, 60]]
    assert captured["render"]["bubbles"][0]["textColor"] == "#111111"
    assert captured["render"]["bubbles"][0]["autoFgColor"] == [17, 17, 17]
    assert captured["render"]["bubbles"][0]["autoBgColor"] == [249, 249, 249]


def test_run_page_pipeline_passes_textlines_to_ocr_page(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "source.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[{"polygon": [[1, 1], [2, 1], [2, 2], [1, 2]], "direction": "v"}]],
            "rawMask": None,
        },
    )

    def fake_ocr_page(source_path, bubble_coords, textlines_per_bubble=None):
        captured["ocr"] = {
            "source_path": source_path,
            "bubble_coords": bubble_coords,
            "textlines_per_bubble": textlines_per_bubble,
        }
        return {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        }

    monkeypatch.setattr("src.core.pipeline.service.ocr_page", fake_ocr_page)
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.extract_bubble_colors",
        lambda source_path, bubble_coords, textlines_per_bubble: {"colors": []},
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.inpaint_page",
        lambda image_path, bubble_coords, raw_mask=None, bubble_polygons=None, output_path=None, method="solid", saber_session=None: {
            "cleanImagePath": output_path
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.render_page",
        lambda clean_image_path, page_id, bubbles, output_path=None, auto_font_size=True, auto_font_settings=None, saber_session=None: {
            "translatedImagePath": output_path,
            "bubbleStates": bubbles,
        },
    )

    run_page_pipeline(app, "page-0001", str(source_path))

    assert captured["ocr"]["textlines_per_bubble"] == [[{"polygon": [[1, 1], [2, 1], [2, 2], [1, 2]], "direction": "v"}]]


def test_run_page_pipeline_applies_render_and_inpaint_config(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "source.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda project_root=None: {
            "render": {
                "layout_mode": "horizontal",
                "font_family": "fonts/custom.ttf",
                "stroke_enabled": False,
                "stroke_color": "#111111",
                "stroke_width": 1,
                "line_spacing": 1.1,
                "text_align": "start",
                "auto_font": {
                    "min_size": 20,
                    "max_size": 64,
                    "padding_ratio": 0.88,
                },
            },
            "inpaint": {
                "method": "litelama",
                "mask_dilate_size": 3,
                "mask_box_expand_ratio": 2,
            },
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda source_path, bubble_coords: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.extract_bubble_colors",
        lambda source_path, bubble_coords, textlines_per_bubble: {"colors": []},
    )

    def fake_inpaint_page(
        image_path,
        bubble_coords,
        raw_mask=None,
        bubble_polygons=None,
        output_path=None,
        method="solid",
        saber_session=None,
        mask_dilate_size=1,
        mask_box_expand_ratio=0,
    ):
        captured["inpaint"] = {
            "method": method,
            "mask_dilate_size": mask_dilate_size,
            "mask_box_expand_ratio": mask_box_expand_ratio,
        }
        return {"cleanImagePath": output_path}

    def fake_render_page(
        clean_image_path,
        page_id,
        bubbles,
        output_path=None,
        auto_font_size=True,
        auto_font_settings=None,
        saber_session=None,
    ):
        captured["render"] = {
            "bubbles": bubbles,
            "auto_font_settings": auto_font_settings,
        }
        return {"translatedImagePath": output_path}

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("src.core.pipeline.service.render_page", fake_render_page)

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert result["translatedTexts"] == ["来吧"]
    assert captured["inpaint"] == {
        "method": "litelama",
        "mask_dilate_size": 3,
        "mask_box_expand_ratio": 2,
    }
    assert captured["render"]["auto_font_settings"] == {
        "min_size": 20,
        "max_size": 64,
        "padding_ratio": 0.88,
    }
    assert captured["render"]["bubbles"][0]["fontFamily"] == "fonts/custom.ttf"
    assert captured["render"]["bubbles"][0]["strokeEnabled"] is False
    assert captured["render"]["bubbles"][0]["strokeColor"] == "#111111"
    assert captured["render"]["bubbles"][0]["strokeWidth"] == 1
    assert captured["render"]["bubbles"][0]["lineSpacing"] == 1.1
    assert captured["render"]["bubbles"][0]["textAlign"] == "start"


def test_run_page_pipeline_filters_noise_before_translate(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (794, 1200), "white").save(source_path)
    captured = {}

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[385, 83, 400, 119], [276, 92, 281, 101], [49, 1135, 70, 1155]],
            "bubblePolygons": [
                [[385, 83], [400, 83], [400, 119], [385, 119]],
                [[276, 92], [281, 92], [281, 101], [276, 101]],
                [[49, 1135], [70, 1135], [70, 1155], [49, 1155]],
            ],
            "autoDirections": ["vertical", "vertical", "vertical"],
            "textlinesPerBubble": [[], [], []],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda source_path, bubble_coords: {
            "originalTexts": ["ん？", "１３"],
            "ocrResults": [
                {"text": "ん？", "engine": "manga_ocr"},
                {"text": "１３", "engine": "manga_ocr"},
            ],
        },
    )

    def fake_translate_texts(texts, model, base_url):
        captured["translated_texts_input"] = texts
        return ["嗯？"]

    monkeypatch.setattr(
        "src.core.pipeline.service.extract_bubble_colors",
        lambda source_path, bubble_coords, textlines_per_bubble: {
            "colors": [
                {
                    "textColor": "#0f0f0f",
                    "bgColor": "#ffffff",
                    "autoFgColor": [15, 15, 15],
                    "autoBgColor": [255, 255, 255],
                    "colorConfidence": 0.95,
                }
            ]
        },
    )

    def fake_inpaint_page(
        image_path,
        bubble_coords,
        raw_mask=None,
        bubble_polygons=None,
        output_path=None,
        method="solid",
        saber_session=None,
    ):
        captured["inpaint"] = {
            "bubble_coords": bubble_coords,
            "bubble_polygons": bubble_polygons,
            "output_path": output_path,
            "saber_session": saber_session,
        }
        return {"cleanImagePath": output_path}

    def fake_render_page(
        clean_image_path,
        page_id,
        bubbles,
        output_path=None,
        auto_font_size=True,
        auto_font_settings=None,
        saber_session=None,
    ):
        captured["render"] = {
            "bubbles": bubbles,
            "output_path": output_path,
            "auto_font_size": auto_font_size,
            "auto_font_settings": auto_font_settings,
            "saber_session": saber_session,
        }
        return {"translatedImagePath": output_path}

    monkeypatch.setattr("src.core.pipeline.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("src.core.pipeline.service.render_page", fake_render_page)

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert captured["translated_texts_input"] == ["ん？"]
    assert captured["inpaint"]["bubble_coords"] == [[385, 83, 400, 119]]
    assert captured["inpaint"]["bubble_polygons"] == [[[385, 83], [400, 83], [400, 119], [385, 119]]]
    assert len(captured["render"]["bubbles"]) == 1
    assert captured["render"]["auto_font_size"] is True
    assert captured["render"]["bubbles"][0]["textColor"] == "#111111"
    assert captured["render"]["bubbles"][0]["strokeColor"] == "#FFFFFF"
    assert captured["render"]["bubbles"][0]["strokeWidth"] == 0
    assert result["bubbleCoords"] == [[385, 83, 400, 119]]
    assert result["originalTexts"] == ["ん？"]
    assert result["translatedTexts"] == ["嗯？"]


def test_run_page_pipeline_returns_timings_and_bubble_states(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts",
        lambda *args, **kwargs: ["来吧"],
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.extract_bubble_colors",
        lambda *args, **kwargs: {"colors": []},
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.inpaint_page",
        lambda *args, **kwargs: {"cleanImagePath": "clean.png"},
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.render_page",
        lambda *args, **kwargs: {"translatedImagePath": "translated.png"},
    )

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert result["manualEdited"] is False
    assert "bubbleStates" in result
    assert result["bubbleStates"][0]["translatedText"] == "来吧"
    assert set(result["timings"]) == {"detect", "ocr", "translate", "color", "inpaint", "render", "total"}


def test_run_page_pipeline_prefers_rendered_bubble_states(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", lambda *args, **kwargs: ["来吧"])
    monkeypatch.setattr("src.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr(
        "src.core.pipeline.service.render_page",
        lambda *args, **kwargs: {
            "translatedImagePath": "translated.png",
            "bubbleStates": [{"coords": [10, 20, 40, 60], "translatedText": "来吧", "fontSize": 28}],
        },
    )

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert result["bubbleStates"][0]["fontSize"] == 28


def test_run_page_pipeline_adds_watermark_to_rendered_image(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (300, 400), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[20, 30, 120, 140]],
            "bubblePolygons": [[[20, 30], [120, 30], [120, 140], [20, 140]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr("src.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})

    def fake_inpaint_page(
        image_path,
        bubble_coords,
        raw_mask=None,
        bubble_polygons=None,
        output_path=None,
        method="solid",
        saber_session=None,
        **kwargs,
    ):
        Image.new("RGB", (300, 400), "white").save(output_path)
        return {"cleanImagePath": output_path}

    def fake_render_page(
        clean_image_path,
        page_id,
        bubbles,
        output_path=None,
        auto_font_size=True,
        auto_font_settings=None,
        saber_session=None,
    ):
        Image.new("RGB", (300, 400), "white").save(output_path)
        return {"translatedImagePath": output_path, "bubbleStates": bubbles}

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("src.core.pipeline.service.render_page", fake_render_page)

    result = run_page_pipeline(app, "page-0001", str(source_path))

    rendered = Image.open(result["translatedImagePath"]).convert("RGB")
    watermark_crop = rendered.crop((150, 320, 300, 400))
    difference = ImageChops.difference(watermark_crop, Image.new("RGB", watermark_crop.size, "white"))

    assert difference.getbbox() is not None


def test_run_page_pipeline_reuses_preprocessed_payload_and_translated_texts(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.load_settings",
        lambda project_root=None: {
            "render": {
                "layout_mode": "horizontal",
                "auto_font": {
                    "min_size": 16,
                    "max_size": 72,
                    "padding_ratio": 0.96,
                },
            }
        },
    )

    preprocessed_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
        "bubbleColors": [
            {
                "textColor": "#111111",
                "bgColor": "#ffffff",
                "autoFgColor": [17, 17, 17],
                "autoBgColor": [255, 255, 255],
                "colorConfidence": 0.88,
            }
        ],
        "originalTexts": ["さあ"],
        "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        "rawMask": None,
    }

    monkeypatch.setattr("src.core.pipeline.service.preprocess_page", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")))
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")))

    def fake_inpaint_page(
        image_path,
        bubble_coords,
        raw_mask=None,
        bubble_polygons=None,
        output_path=None,
        method="solid",
        saber_session=None,
    ):
        captured["inpaint"] = {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "bubble_polygons": bubble_polygons,
            "output_path": output_path,
            "method": method,
            "saber_session": saber_session,
        }
        return {"cleanImagePath": output_path}

    def fake_render_page(
        clean_image_path,
        page_id,
        bubbles,
        output_path=None,
        auto_font_size=True,
        auto_font_settings=None,
        saber_session=None,
    ):
        captured["render"] = {
            "clean_image_path": clean_image_path,
            "page_id": page_id,
            "bubbles": bubbles,
            "output_path": output_path,
            "auto_font_size": auto_font_size,
            "auto_font_settings": auto_font_settings,
            "saber_session": saber_session,
        }
        return {"translatedImagePath": output_path}

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("src.core.pipeline.service.render_page", fake_render_page)

    result = run_page_pipeline(
        app,
        "page-0001",
        str(source_path),
        preprocessed_payload=preprocessed_payload,
        translated_texts=["来吧"],
        context_snapshot={"historyPageIds": [], "confirmedTranslations": [], "glossary": {}},
        saber_session="session-token",
    )

    assert result["translatedTexts"] == ["来吧"]
    assert captured["inpaint"]["saber_session"] == "session-token"
    assert captured["render"]["saber_session"] == "session-token"
    assert captured["render"]["auto_font_settings"] == {
        "min_size": 16,
        "max_size": 72,
        "padding_ratio": 0.96,
    }


def test_run_page_pipeline_passes_context_snapshot_to_translator(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["先輩"],
            "ocrResults": [{"text": "先輩", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("src.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})

    class FakeLibraryStore:
        def __init__(self, app):
            self.app = app

        def list_pages(self):
            return [
                {"id": "page-0001", "fileName": "001.jpg"},
                {"id": "page-0002", "fileName": "002.jpg"},
            ]

    class FakeCacheStore:
        def __init__(self, app):
            self.app = app

        def load_result_or_default(self, page_id, default=None):
            if page_id == "page-0001":
                return {
                    "manualEdited": True,
                    "bubbleStates": [{"originalText": "先輩", "translatedText": "学姐"}],
                }
            return default

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        captured["context_snapshot"] = context_snapshot
        return ["学姐"]

    monkeypatch.setattr("src.core.pipeline.service.LibraryStore", FakeLibraryStore)
    monkeypatch.setattr("src.core.pipeline.service.CacheStore", FakeCacheStore)
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", fake_translate_texts)

    result = run_page_pipeline(app, "page-0002", str(source_path))

    assert captured["context_snapshot"]["glossary"]["先輩"] == "学姐"
    assert result["contextInputs"]["confirmedTranslations"] == ["学姐"]


def test_run_page_pipeline_persists_multiround_translation_metadata(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "src.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "src.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["こんにちは"],
            "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("src.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})
    monkeypatch.setattr(
        "src.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, context_snapshot=None: {
            "translatedTexts": ["你好呀"],
            "rounds": [
                {"name": "draft", "translatedTexts": ["你好"], "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120, "estimated": False}},
                {"name": "contextual", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 140, "outputTokens": 22, "totalTokens": 162, "estimated": False}},
                {"name": "final", "translatedTexts": ["你好呀"], "usage": {"inputTokens": 80, "outputTokens": 10, "totalTokens": 90, "estimated": False}},
            ],
            "tokenUsage": {"inputTokens": 320, "outputTokens": 52, "totalTokens": 372, "estimated": False},
            "ocrRetry": {"attempted": False, "applied": False, "reasons": []},
        },
    )

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert result["translatedTexts"] == ["你好呀"]
    assert result["translation"]["rounds"][0]["name"] == "draft"
    assert result["translation"]["rounds"][1]["translatedTexts"] == ["你好呀"]
    assert result["translation"]["tokenUsage"]["totalTokens"] == 372
    assert result["ocrRetry"]["attempted"] is False


def test_run_page_pipeline_retries_ocr_once_when_multiround_translation_requests_it(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    first_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["SN"],
        "ocrResults": [{"text": "SN", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    retry_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["こんにちは"],
        "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
        "rawMask": None,
    }

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})
    translate_calls = []

    def fake_translate_texts_multi_round(texts, model, base_url, context_snapshot=None):
        translate_calls.append(list(texts))
        if texts == ["SN"]:
            return {
                "translatedTexts": ["SN"],
                "rounds": [{"name": "final", "translatedTexts": ["SN"], "usage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False}}],
                "tokenUsage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False},
                "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": True, "reasons": ["too_many_latin_fragments"]},
            }
        return {
            "translatedTexts": ["你好"],
            "rounds": [{"name": "final", "translatedTexts": ["你好"], "usage": {"inputTokens": 30, "outputTokens": 6, "totalTokens": 36, "estimated": False}}],
            "tokenUsage": {"inputTokens": 30, "outputTokens": 6, "totalTokens": 36, "estimated": False},
            "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": False, "reasons": []},
        }

    monkeypatch.setattr("src.core.pipeline.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.core.pipeline.service.retry_preprocess_page_for_ocr", lambda *args, **kwargs: retry_payload)

    result = run_page_pipeline(
        app,
        "page-0001",
        str(source_path),
        preprocessed_payload=first_payload,
        context_snapshot={"historyPageIds": [], "confirmedTranslations": [], "glossary": {}},
    )

    assert translate_calls == [["SN"], ["こんにちは"]]
    assert result["originalTexts"] == ["こんにちは"]
    assert result["translatedTexts"] == ["你好"]
    assert result["ocrRetry"]["attempted"] is True
    assert result["ocrRetry"]["applied"] is True
    assert result["ocrRetry"]["reasons"] == ["too_many_latin_fragments"]


def test_run_page_pipeline_keeps_original_ocr_when_retry_translation_fails(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    first_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["SN"],
        "ocrResults": [{"text": "SN", "engine": "manga_ocr"}],
        "rawMask": None,
    }
    retry_payload = {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "bubbleColors": [],
        "originalTexts": ["こんにちは"],
        "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
        "rawMask": None,
    }

    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})

    def fake_translate_texts_multi_round(texts, model, base_url, context_snapshot=None):
        if texts == ["SN"]:
            return {
                "translatedTexts": ["SN"],
                "rounds": [{"name": "final", "translatedTexts": ["SN"], "usage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False}}],
                "tokenUsage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False},
                "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": True, "reasons": ["too_many_latin_fragments"]},
            }
        raise RuntimeError("retry translate failed")

    monkeypatch.setattr("src.core.pipeline.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("src.core.pipeline.service.retry_preprocess_page_for_ocr", lambda *args, **kwargs: retry_payload)

    result = run_page_pipeline(
        app,
        "page-0001",
        str(source_path),
        preprocessed_payload=first_payload,
        context_snapshot={"historyPageIds": [], "confirmedTranslations": [], "glossary": {}},
    )

    assert result["originalTexts"] == ["SN"]
    assert result["translatedTexts"] == ["SN"]
    assert result["ocrRetry"]["attempted"] is True
    assert result["ocrRetry"]["applied"] is False
