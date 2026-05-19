from pathlib import Path

from PIL import Image, ImageChops

from translate_manga.core.pipeline import service as pipeline_service
from translate_manga.core.pipeline.service import _build_bubbles, preprocess_page, run_page_pipeline


def test_build_bubbles_applies_cli_readability_profile(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
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
            "bubbleCoords": [[10, 20, 90, 120]],
            "bubblePolygons": [[[10, 20], [90, 20], [90, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#eeeeee",
                    "bgColor": "#111111",
                    "autoFgColor": [238, 238, 238],
                    "autoBgColor": [17, 17, 17],
                    "colorConfidence": 0.95,
                    "grayStdDev": 14.0,
                    "edgeDensity": 0.08,
                    "darkPixelRatio": 0.41,
                }
            ],
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
        "translate_manga.core.pipeline.service.load_settings",
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
        "translate_manga.core.pipeline.service.load_settings",
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


def test_build_bubbles_mixes_horizontal_bubbles_under_vertical_layout(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 120, 60], [130, 20, 170, 140]],
            "bubblePolygons": [
                [[10, 20], [120, 20], [120, 60], [10, 60]],
                [[130, 20], [170, 20], [170, 140], [130, 140]],
            ],
            "autoDirections": ["h", "v"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["面白い", "来い"],
            "ocrResults": [
                {"text": "面白い", "engine": "manga_ocr"},
                {"text": "来い", "engine": "manga_ocr"},
            ],
        },
        ["有意思", "过来"],
    )

    assert bubbles[0]["textDirection"] == "horizontal"
    assert bubbles[0]["fontFamily"] == "fonts/horizontal.ttf"
    assert bubbles[0]["lineSpacing"] == 0.84
    assert bubbles[0]["layoutProfile"] is None
    assert bubbles[1]["textDirection"] == "vertical"
    assert bubbles[1]["fontFamily"] == "fonts/vertical.ttf"
    assert bubbles[1]["lineSpacing"] == 1.04
    assert bubbles[1]["layoutProfile"] == "vertical_layout2"


def test_build_bubbles_uses_horizontal_font_override(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "font_family": "fonts/思源黑体SourceHanSansK-Bold.TTF",
                "layout_mode": "horizontal",
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
            "bubbleCoords": [[10, 20, 60, 70]],
            "bubblePolygons": [[[10, 20], [60, 20], [60, 70], [10, 70]]],
            "autoDirections": ["horizontal"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [],
        },
        {"originalTexts": ["HELLO"], "ocrResults": []},
        ["你好"],
        layout_mode_override="horizontal",
        font_family_override="fonts/汉仪正圆-65W.TTF",
    )

    assert bubbles[0]["fontFamily"] == "fonts/汉仪正圆-65W.TTF"


def test_build_bubbles_suppresses_top_header_noise_translation(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[610, 20, 759, 90]],
            "bubblePolygons": [[[758, 92], [608, 89], [610, 20], [759, 23]]],
            "autoDirections": ["h"],
            "textlinesPerBubble": [
                [
                    {"polygon": [[610, 20], [759, 23], [759, 51], [610, 49]], "direction": "h"},
                    {"polygon": [[631, 75], [694, 75], [694, 90], [631, 90]], "direction": "h"},
                ]
            ],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["カムイ伝日 ビーッ"],
            "ocrResults": [{"text": "カムイ伝日 ビーッ", "engine": "48px_ocr", "confidence": 0.45}],
        },
        ["卡姆伊传日 哔—"],
        image_size=(820, 1200),
    )

    assert bubbles[0]["bubbleRole"] == "header_noise"
    assert bubbles[0]["translatedText"] == ""


def test_build_bubbles_suppresses_top_header_noise_with_borderline_confidence(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[646, 16, 792, 79]],
            "bubblePolygons": [[[646, 16], [792, 16], [792, 79], [646, 79]]],
            "autoDirections": ["h"],
            "textlinesPerBubble": [
                [
                    {"polygon": [[646, 16], [792, 16], [792, 48], [646, 48]], "direction": "h"},
                    {"polygon": [[700, 52], [760, 52], [760, 79], [700, 79]], "direction": "h"},
                ]
            ],
            "bubbleColors": [],
        },
        {
            "originalTexts": ["カムイ伝日 キャーン!!"],
            "ocrResults": [{"text": "カムイ伝日 キャーン!!", "engine": "48px_ocr", "confidence": 0.78}],
        },
        ["卡姆伊传日 咻——!!"],
        image_size=(816, 1143),
    )

    assert bubbles[0]["bubbleRole"] == "header_noise"
    assert bubbles[0]["translatedText"] == ""


def test_build_bubble_text_profiles_keeps_high_confidence_top_left_sfx():
    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[79, 64, 159, 82]],
            "textlinesPerBubble": [
                [{"polygon": [[79, 64], [159, 64], [159, 82], [79, 82]], "direction": "h"}]
            ],
        },
        {
            "originalTexts": ["KAA!!"],
            "ocrResults": [{"text": "KAA!!", "engine": "48px_ocr", "confidence": 0.93}],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "dialogue"
    assert profiles[0]["suppressTranslation"] is False
    assert profiles[0]["sourceText"] == "KAA!!"


def test_build_bubble_text_profiles_keeps_vertical_dominant_mixed_bubble_as_dialogue():
    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[41, 20, 249, 180]],
            "textlinesPerBubble": [
                [
                    {"polygon": [[229, 65], [249, 65], [249, 136], [229, 136]], "direction": "v"},
                    {"polygon": [[204, 66], [224, 66], [224, 164], [204, 164]], "direction": "v"},
                    {"polygon": [[181, 68], [199, 68], [199, 180], [181, 180]], "direction": "v"},
                    {"polygon": [[157, 68], [177, 68], [177, 180], [157, 180]], "direction": "v"},
                    {"polygon": [[133, 66], [154, 66], [152, 127], [131, 126]], "direction": "v"},
                    {"polygon": [[109, 67], [129, 67], [130, 173], [110, 173]], "direction": "v"},
                    {"polygon": [[98, 24], [126, 20], [129, 45], [101, 49]], "direction": "h"},
                    {"polygon": [[41, 21], [72, 21], [72, 49], [41, 49]], "direction": "h"},
                ]
            ],
        },
        {
            "originalTexts": ["long vertical dialogue"],
            "ocrResults": [{"text": "long vertical dialogue", "engine": "48px_ocr", "confidence": 0.82}],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "dialogue"
    assert profiles[0]["directionOverride"] is None
    assert profiles[0]["autoFontSettings"] == {
        "min_size": 7,
        "max_size": 22,
        "padding_ratio": 0.64,
    }
    assert profiles[0]["positionOffset"] == {"x": 0, "y": 40}


def test_build_bubble_text_profiles_normalizes_long_narration_source_text():
    long_text = "どうも、 オオカミの生活 に、 たちいりすぎた ようだ。 しかも、 この白オオカミの成長は、 こ の物語に同時的にあつかわれている。"

    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[80, 300, 640, 720]],
            "textlinesPerBubble": [
                [{"direction": "v"} for _ in range(18)]
            ],
        },
        {
            "originalTexts": [long_text],
            "ocrResults": [
                {"text": long_text, "engine": "manga_ocr", "confidence": 0.66, "fallbackUsed": True}
            ],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "long_narration"
    assert profiles[0]["sourceText"] == "どうも、オオカミの生活に、たちいりすぎたようだ。しかも、この白オオカミの成長は、この物語に同時的にあつかわれている。"


def test_build_bubble_text_profiles_uses_horizontal_prose_for_wide_editorial_narration():
    long_text = (
        "どうも、オオカミの生活に、たちいりすぎたようだ。"
        "しかも、この白オオカミの成長は、この物語に同時的にあつかわれている。"
    ) * 5

    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[72, 678, 748, 1078]],
            "textlinesPerBubble": [[{"direction": "v"} for _ in range(24)]],
            "bubbleColors": [
                {
                    "edgeDensity": 0.09,
                    "darkPixelRatio": 0.001,
                    "grayStdDev": 10.0,
                }
            ],
        },
        {
            "originalTexts": [long_text],
            "ocrResults": [
                {"text": long_text, "engine": "manga_ocr", "confidence": 0.66, "fallbackUsed": True}
            ],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "long_narration"
    assert profiles[0]["directionOverride"] == "horizontal"
    assert profiles[0]["textAlignOverride"] == "start"
    assert profiles[0]["autoFontSettings"] == {
        "min_size": 8,
        "max_size": 20,
        "padding_ratio": 0.84,
    }


def test_build_bubble_text_profiles_uses_horizontal_prose_for_low_confidence_wide_exposition():
    long_text = (
        "百姓といっても、庄屋から下人まで、いろいろに分かれている。"
        "本百姓は高持百姓といって、年貢をおさめる義務をもった者である。"
    ) * 3

    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[409, 583, 742, 828]],
            "textlinesPerBubble": [[{"direction": "v"} for _ in range(13)]],
            "bubbleColors": [
                {
                    "edgeDensity": 0.19,
                    "darkPixelRatio": 0.025,
                    "grayStdDev": 38.0,
                }
            ],
        },
        {
            "originalTexts": [long_text],
            "ocrResults": [
                {"text": long_text, "engine": "manga_ocr", "confidence": 0.34, "fallbackUsed": True}
            ],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "long_narration"
    assert profiles[0]["directionOverride"] == "horizontal"
    assert profiles[0]["textAlignOverride"] == "start"


def test_build_bubble_text_profiles_uses_compact_horizontal_settings_for_chart_lists():
    chart_text = "荒おこし 3月 苗しろ 5月 荒くれかき しろかき 田うえ 水まわし 田の草とり 追肥 病虫害予防 刈りとり 9月 脱穀 10～11月 モミつき 選米"

    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[60, 349, 327, 672]],
            "textlinesPerBubble": [[{"direction": "h"} for _ in range(17)]],
            "bubbleColors": [
                {
                    "edgeDensity": 0.08,
                    "darkPixelRatio": 0.002,
                    "grayStdDev": 8.0,
                }
            ],
        },
        {
            "originalTexts": [chart_text],
            "ocrResults": [
                {"text": chart_text, "engine": "48px_ocr", "confidence": 0.91, "fallbackUsed": False}
            ],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "long_narration"
    assert profiles[0]["directionOverride"] == "horizontal"
    assert profiles[0]["textAlignOverride"] == "start"
    assert profiles[0]["autoFontSettings"] == {
        "min_size": 8,
        "max_size": 14,
        "padding_ratio": 0.74,
    }


def test_build_bubble_text_profiles_applies_multimodal_layout_hints():
    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [
                [718, 1088, 792, 1132],
                [58, 306, 528, 560],
                [551, 52, 738, 168],
            ],
            "textlinesPerBubble": [
                [{"direction": "h"}],
                [{"direction": "v"} for _ in range(12)],
                [{"direction": "v"} for _ in range(4)],
            ],
            "bubbleLayoutHints": [
                {"role": "page_number", "suppressTranslation": True},
                {"role": "long_narration", "directionOverride": "horizontal", "textAlignOverride": "start"},
                {"role": "dialogue", "directionOverride": "vertical"},
            ],
        },
        {
            "originalTexts": ["30", "説明文" * 30, "おめでとう"],
            "ocrResults": [
                {"text": "30", "engine": "48px_ocr", "confidence": 0.99},
                {"text": "説明文" * 30, "engine": "manga_ocr", "confidence": 0.92},
                {"text": "おめでとう", "engine": "48px_ocr", "confidence": 0.9},
            ],
        },
        image_size=(816, 1143),
    )

    assert profiles[0]["role"] == "page_number"
    assert profiles[0]["sourceText"] == ""
    assert profiles[0]["suppressTranslation"] is True
    assert profiles[1]["role"] == "long_narration"
    assert profiles[1]["directionOverride"] == "horizontal"
    assert profiles[1]["textAlignOverride"] == "start"
    assert profiles[2]["role"] == "dialogue"
    assert profiles[2]["directionOverride"] == "vertical"


def test_build_bubbles_keeps_vertical_dense_long_narration_in_vertical_style(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "vertical",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    original_text = "どうも、 オオカミの生活 に、 たちいりすぎた ようだ。 しかも、 この白オオカミの成長は、 こ の物語に同時的にあつかわれている。"
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[40, 220, 720, 700]],
            "bubblePolygons": [[[40, 220], [720, 220], [720, 700], [40, 700]]],
            "autoDirections": ["v"],
            "textlinesPerBubble": [
                [{"direction": "v"} for _ in range(18)]
            ],
            "bubbleColors": [],
        },
        {
            "originalTexts": [original_text],
            "ocrResults": [
                {"text": original_text, "engine": "manga_ocr", "confidence": 0.66, "fallbackUsed": True}
            ],
        },
        ["这是一个很长的说明文块。"],
        image_size=(816, 1143),
    )

    assert bubbles[0]["bubbleRole"] == "long_narration"
    assert bubbles[0]["textDirection"] == "vertical"
    assert bubbles[0]["fontFamily"] == "fonts/vertical.ttf"
    assert bubbles[0]["layoutProfile"] == "vertical_layout2"
    assert bubbles[0]["textAlign"] == "center"
    assert bubbles[0]["autoFontSettings"] == {
        "min_size": 8,
        "max_size": 16,
        "padding_ratio": 0.78,
    }


def test_build_bubbles_trims_l_shaped_vertical_long_narration_render_box(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "auto",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    textlines = []
    for x in range(746, 430, -24):
        textlines.append({"direction": "v", "polygon": [[x, 850], [x + 18, 850], [x + 18, 1058], [x, 1058]]})
    for x in range(408, 74, -24):
        textlines.append({"direction": "v", "polygon": [[x, 612], [x + 18, 612], [x + 18, 1058], [x, 1058]]})

    original_text = "当時、非人はもっとも 身分のひくいものとされ 死牛馬のあと始末、皮革 竹細工、染物を職業とする者がおおかった。"
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[75, 610, 762, 1068]],
            "bubblePolygons": [[[78, 1069], [75, 611], [760, 606], [763, 1064]]],
            "autoDirections": ["v"],
            "textlinesPerBubble": [textlines],
            "bubbleColors": [],
        },
        {
            "originalTexts": [original_text],
            "ocrResults": [
                {"text": original_text, "engine": "manga_ocr", "confidence": 0.68, "fallbackUsed": True}
            ],
        },
        ["当时，非人被视为身份最低下者，多从事死牛马处理和皮革竹细工。"],
        image_size=(816, 1152),
    )

    assert bubbles[0]["bubbleRole"] == "long_narration"
    assert bubbles[0]["textDirection"] == "vertical"
    assert bubbles[0]["coords"][0] <= 75
    assert bubbles[0]["coords"][2] < 470


def test_build_bubble_text_profiles_suppresses_low_confidence_micro_kana_noise():
    profiles = pipeline_service.build_bubble_text_profiles(
        {
            "bubbleCoords": [[611, 817, 654, 831]],
            "textlinesPerBubble": [
                [{"direction": "h", "polygon": [[611, 817], [654, 817], [654, 831], [611, 831]]}]
            ],
        },
        {
            "originalTexts": ["ッ"],
            "ocrResults": [
                {"text": "ッ", "engine": "manga_ocr", "confidence": 0.16, "fallbackUsed": True}
            ],
        },
        image_size=(816, 1152),
    )

    assert profiles[0]["role"] == "ocr_noise"
    assert profiles[0]["suppressTranslation"] is True
    assert profiles[0]["sourceText"] == ""


def test_build_bubbles_keeps_tall_vertical_long_narration_in_vertical_style(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {
            "render": {
                "layout_mode": "auto",
                "font_family": "fonts/horizontal.ttf",
                "line_spacing": 0.84,
                "stroke_enabled": True,
                "stroke_color": "#FFFFFF",
                "stroke_width": 1,
                "text_align": "center",
                "vertical_layout": {
                    "font_family": "fonts/vertical.ttf",
                    "line_spacing": 1.04,
                },
            }
        },
    )

    original_text = "すりゃ、 年を 生 こしても 米がくえる だ……。 誕 そう言われるのですが、スタジューではなくなりませんが、 ウーム、 十年に一ぺん とれるか とれんかの みのりじゃ。"
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[12, 20, 183, 907]],
            "bubblePolygons": [[[14, 907], [11, 20], [182, 19], [184, 906]]],
            "autoDirections": ["v"],
            "textlinesPerBubble": [
                [{"direction": direction} for direction in ["v", "v", "h", "v", "v", "v", "h", "v", "v", "v", "v", "v"]]
            ],
            "bubbleColors": [],
        },
        {
            "originalTexts": [original_text],
            "ocrResults": [
                {"text": original_text, "engine": "48px_ocr", "confidence": 0.92, "fallbackUsed": False}
            ],
        },
        ["有这米，就算上了年纪也能吃上饭了。"],
        image_size=(816, 1143),
    )

    assert bubbles[0]["bubbleRole"] == "long_narration"
    assert bubbles[0]["textDirection"] == "vertical"
    assert bubbles[0]["fontFamily"] == "fonts/vertical.ttf"
    assert bubbles[0]["layoutProfile"] == "vertical_layout2"
    assert bubbles[0]["autoFontSettings"] == {
        "min_size": 8,
        "max_size": 16,
        "padding_ratio": 0.78,
    }


def test_preprocess_page_passes_style_ocr_options(monkeypatch, tmp_path):
    from PIL import Image

    from translate_manga.core.pipeline import service as pipeline_service

    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (80, 80), "white").save(image_path)
    captured = {}

    def fake_run_saber_task(operation, payload, session=None):
        captured["operation"] = operation
        captured["payload"] = payload
        return {
            "bubbleCoords": [],
            "bubblePolygons": [],
            "autoDirections": [],
            "textlinesPerBubble": [],
            "originalTexts": [],
            "ocrResults": [],
            "colors": [],
        }

    monkeypatch.setattr(pipeline_service, "run_saber_task", fake_run_saber_task)

    pipeline_service.preprocess_page(
        image_path,
        ocr_options={
            "source_language": "english",
            "engine": "paddle_ocr",
            "enable_hybrid": False,
            "secondary_engine": None,
        },
    )

    assert captured["operation"] == "preprocess"
    assert captured["payload"]["source_language"] == "english"
    assert captured["payload"]["ocr_engine"] == "paddle_ocr"
    assert captured["payload"]["enable_hybrid_ocr"] is False
    assert "secondary_ocr_engine" not in captured["payload"]


def test_build_bubbles_uses_vertical_layout2_profile(monkeypatch):
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
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
        "translate_manga.core.pipeline.service.load_settings",
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
        "translate_manga.core.pipeline.service.load_settings",
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

    from translate_manga.core.pipeline.service import _resolve_auto_font_settings

    settings = _resolve_auto_font_settings()
    assert settings == {
        "min_size": 14,
        "max_size": 60,
        "padding_ratio": 0.86,
    }


def test_resolve_watermark_style_uses_new_default_text():
    from translate_manga.core.pipeline.service import _resolve_watermark_style

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
                    "grayStdDev": 14.0,
                    "edgeDensity": 0.08,
                    "darkPixelRatio": 0.41,
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

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
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
                    "grayStdDev": 4.0,
                    "edgeDensity": 0.01,
                    "darkPixelRatio": 0.02,
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


def test_enrich_bubble_color_metrics_fast_mode_skips_simple_white_bubbles(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    Image.new("RGB", (120, 120), "white").save(source_path)
    called = {"count": 0}

    def fake_enrich(payload, source_path, bubble_coords, textlines_per_bubble):
        called["count"] += 1
        return payload

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.enrich_bubble_colors_with_background_metrics",
        fake_enrich,
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {"pipeline": {"color_fast_mode": True}},
    )

    payload = {
        "bubbleColors": [
            {
                "bgColor": "#FFFFFF",
                "textColor": "#111111",
                "autoBgColor": [255, 255, 255],
                "autoFgColor": [17, 17, 17],
                "colorConfidence": 0.95,
            }
        ],
        "bubbleCoords": [[10, 10, 80, 80]],
        "textlinesPerBubble": [[]],
    }

    result = pipeline_service._enrich_bubble_color_metrics(payload, source_path)

    assert called["count"] == 0
    assert result["bubbleColors"][0]["grayStdDev"] == 0.0
    assert result["bubbleColors"][0]["edgeDensity"] == 0.0
    assert result["bubbleColors"][0]["darkPixelRatio"] == 0.0


def test_build_bubbles_uses_white_stroke_for_light_but_busy_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#efefef",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [239, 239, 239],
                    "colorConfidence": 0.88,
                    "grayStdDev": 28.0,
                    "edgeDensity": 0.17,
                    "darkPixelRatio": 0.16,
                }
            ],
        },
        {
            "originalTexts": ["見えるか"],
            "ocrResults": [{"text": "見えるか", "engine": "48px_ocr"}],
        },
        ["看得见吗"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 1


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
                    "grayStdDev": 5.0,
                    "edgeDensity": 0.01,
                    "darkPixelRatio": 0.03,
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


def test_build_bubbles_uses_complexity_fallback_when_color_is_unreliable():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120], [160, 20, 290, 120]],
            "bubblePolygons": [
                [[10, 20], [140, 20], [140, 120], [10, 120]],
                [[160, 20], [290, 20], [290, 120], [160, 120]],
            ],
            "autoDirections": ["vertical", "vertical"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [
                {
                    "textColor": "#020201",
                    "bgColor": "#020201",
                    "autoFgColor": [2, 2, 1],
                    "autoBgColor": [2, 2, 1],
                    "colorConfidence": 0.12,
                    "grayStdDev": 5.0,
                    "edgeDensity": 0.01,
                    "darkPixelRatio": 0.03,
                },
                {
                    "textColor": "#020201",
                    "bgColor": "#020201",
                    "autoFgColor": [2, 2, 1],
                    "autoBgColor": [2, 2, 1],
                    "colorConfidence": 0.12,
                    "grayStdDev": 34.0,
                    "edgeDensity": 0.21,
                    "darkPixelRatio": 0.24,
                },
            ],
        },
        {
            "originalTexts": ["ほんとに", "騒ぐな"],
            "ocrResults": [
                {"text": "ほんとに", "engine": "48px_ocr"},
                {"text": "騒ぐな", "engine": "48px_ocr"},
            ],
        },
        ["真的", "别吵"],
    )

    assert bubbles[0]["textColor"] == "#111111"
    assert bubbles[0]["strokeColor"] == "#FFFFFF"
    assert bubbles[0]["strokeWidth"] == 0
    assert bubbles[1]["textColor"] == "#111111"
    assert bubbles[1]["strokeColor"] == "#FFFFFF"
    assert bubbles[1]["strokeWidth"] == 1


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
                    "grayStdDev": 18.0,
                    "edgeDensity": 0.11,
                    "darkPixelRatio": 0.48,
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

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.run_saber_task", fake_run_saber_task)
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.resolve_saber_ocr_options",
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
            "grayStdDev": 0.0,
            "edgeDensity": 0.0,
            "darkPixelRatio": 0.0,
        }
    ]


def test_run_page_pipeline_uses_cache_output_paths(app, tmp_path, monkeypatch):
    captured = {}
    source_path = tmp_path / "source.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
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
        "translate_manga.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[{"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "direction": "v"}]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda source_path, bubble_coords: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts",
        lambda texts, model, base_url: ["来吧"],
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.extract_bubble_colors",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", fake_render_page)

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
        "translate_manga.core.pipeline.service.detect_page",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.ocr_page", fake_ocr_page)
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.extract_bubble_colors",
        lambda source_path, bubble_coords, textlines_per_bubble: {"colors": []},
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.inpaint_page",
        lambda image_path, bubble_coords, raw_mask=None, bubble_polygons=None, output_path=None, method="solid", saber_session=None: {
            "cleanImagePath": output_path
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.render_page",
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
        "translate_manga.core.pipeline.service.load_settings",
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
        "translate_manga.core.pipeline.service.detect_page",
        lambda source_path: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda source_path, bubble_coords: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.extract_bubble_colors",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", fake_render_page)

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
    assert captured["render"]["bubbles"][0]["strokeColor"] == "#FFFFFF"
    assert captured["render"]["bubbles"][0]["strokeWidth"] == 0
    assert captured["render"]["bubbles"][0]["lineSpacing"] == 1.1
    assert captured["render"]["bubbles"][0]["textAlign"] == "start"


def test_run_page_pipeline_filters_noise_before_translate(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (794, 1200), "white").save(source_path)
    captured = {}

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.detect_page",
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
        "translate_manga.core.pipeline.service.ocr_page",
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
        "translate_manga.core.pipeline.service.extract_bubble_colors",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts", fake_translate_texts)
    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", fake_render_page)

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
        "translate_manga.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts",
        lambda *args, **kwargs: ["来吧"],
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.extract_bubble_colors",
        lambda *args, **kwargs: {"colors": []},
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.inpaint_page",
        lambda *args, **kwargs: {"cleanImagePath": "clean.png"},
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.render_page",
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
        "translate_manga.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts", lambda *args, **kwargs: ["来吧"])
    monkeypatch.setattr("translate_manga.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.render_page",
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
        "translate_manga.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[20, 30, 120, 140]],
            "bubblePolygons": [[[20, 30], [120, 30], [120, 140], [20, 140]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["さあ"],
            "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts_multi_round",
        lambda texts, model, base_url, api_key="", context_snapshot=None: {
            "translatedTexts": ["来吧"],
            "rounds": [],
            "tokenUsage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2, "estimated": False},
            "ocrRetry": {"shouldRetry": False, "reasons": [], "attempted": False, "applied": False},
        },
    )
    monkeypatch.setattr("translate_manga.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})

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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", fake_render_page)

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
        "translate_manga.core.pipeline.service.load_settings",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.preprocess_page", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preprocess_page should not run")))
    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("translate_texts should not run")))

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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", fake_inpaint_page)
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", fake_render_page)

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
    assert result["bubbleColors"][0]["grayStdDev"] == 0.0
    assert result["bubbleColors"][0]["edgeDensity"] == 0.0
    assert result["bubbleColors"][0]["darkPixelRatio"] == 0.0
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
    app.seed_pages(
        [
            {"id": "page-0001", "fileName": "001.jpg", "sourcePath": "001.jpg", "translatedPath": None, "status": "idle"},
            {"id": "page-0002", "fileName": "002.jpg", "sourcePath": "002.jpg", "translatedPath": None, "status": "idle"},
        ]
    )
    app.save_result(
        "page-0001",
        {
            "manualEdited": True,
            "bubbleStates": [{"originalText": "先輩", "translatedText": "学姐"}],
        },
    )

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["先輩"],
            "ocrResults": [{"text": "先輩", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("translate_manga.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})

    def fake_translate_texts(texts, model, base_url, context_snapshot=None):
        captured["context_snapshot"] = context_snapshot
        return ["学姐"]

    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts", fake_translate_texts)

    result = run_page_pipeline(app, "page-0002", str(source_path))

    assert captured["context_snapshot"]["glossary"]["先輩"] == "学姐"
    assert result["contextInputs"]["confirmedTranslations"] == ["学姐"]


def test_run_page_pipeline_persists_multiround_translation_metadata(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.detect_page",
        lambda _: {
            "bubbleCoords": [[10, 20, 40, 60]],
            "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "rawMask": None,
        },
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.ocr_page",
        lambda *_: {
            "originalTexts": ["こんにちは"],
            "ocrResults": [{"text": "こんにちは", "engine": "manga_ocr"}],
        },
    )
    monkeypatch.setattr("translate_manga.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.translate_texts_multi_round",
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})
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

    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.core.pipeline.service.retry_preprocess_page_for_ocr", lambda *args, **kwargs: retry_payload)

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

    monkeypatch.setattr("translate_manga.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("translate_manga.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})

    def fake_translate_texts_multi_round(texts, model, base_url, context_snapshot=None):
        if texts == ["SN"]:
            return {
                "translatedTexts": ["SN"],
                "rounds": [{"name": "final", "translatedTexts": ["SN"], "usage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False}}],
                "tokenUsage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25, "estimated": False},
                "ocrRetry": {"attempted": False, "applied": False, "shouldRetry": True, "reasons": ["too_many_latin_fragments"]},
            }
        raise RuntimeError("retry translate failed")

    monkeypatch.setattr("translate_manga.core.pipeline.service.translate_texts_multi_round", fake_translate_texts_multi_round)
    monkeypatch.setattr("translate_manga.core.pipeline.service.retry_preprocess_page_for_ocr", lambda *args, **kwargs: retry_payload)

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
