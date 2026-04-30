from src.core.pipeline.page_classifier import classify_preprocessed_page


def test_classify_preprocessed_page_marks_blank_page_as_skip():
    result = classify_preprocessed_page(
        page_index=1,
        total_pages=120,
        image_size=(794, 1200),
        preprocessed_payload={
            "bubbleCoords": [],
            "originalTexts": [],
        },
    )

    assert result["page_type"] == "blank"
    assert result["should_translate"] is False
    assert result["skip_reason"] == "blank"


def test_classify_preprocessed_page_skips_early_toc_like_page():
    result = classify_preprocessed_page(
        page_index=3,
        total_pages=120,
        image_size=(794, 1200),
        preprocessed_payload={
            "bubbleCoords": [
                [640, 120, 680, 340],
                [590, 140, 628, 360],
                [540, 118, 575, 338],
                [490, 145, 525, 365],
                [440, 122, 478, 342],
                [390, 148, 425, 368],
                [340, 126, 378, 346],
                [290, 152, 325, 372],
            ],
            "originalTexts": [
                "第一章",
                "ある日",
                "第二章",
                "旅立ち",
                "第三章",
                "記録",
                "第四章",
                "終わり",
            ],
        },
    )

    assert result["page_type"] == "frontmatter"
    assert result["should_translate"] is False
    assert result["skip_reason"] == "frontmatter"


def test_classify_preprocessed_page_keeps_story_page_translatable():
    result = classify_preprocessed_page(
        page_index=5,
        total_pages=120,
        image_size=(794, 1200),
        preprocessed_payload={
            "bubbleCoords": [
                [520, 80, 720, 250],
                [120, 180, 320, 360],
                [470, 520, 680, 720],
                [90, 760, 310, 980],
            ],
            "originalTexts": [
                "なんだ？",
                "いや…",
                "また来たのか",
                "早く逃げろ!",
            ],
        },
    )

    assert result["page_type"] == "story"
    assert result["should_translate"] is True
    assert result["skip_reason"] is None


def test_classify_preprocessed_page_keeps_early_dialogue_heavy_page_translatable():
    result = classify_preprocessed_page(
        page_index=3,
        total_pages=188,
        image_size=(794, 1200),
        preprocessed_payload={
            "bubbleCoords": [
                [640, 120, 675, 320],
                [590, 150, 625, 350],
                [540, 140, 575, 340],
                [490, 160, 525, 360],
                [440, 145, 475, 345],
                [390, 170, 425, 370],
                [340, 150, 375, 350],
                [290, 175, 325, 375],
                [240, 155, 275, 355],
                [190, 180, 225, 380],
            ],
            "originalTexts": [
                "休み時間は困る",
                "いよいよ今週だ",
                "やめてよ魔裟死くん",
                "魔裟斗さんの試合",
                "クラウスと戦うＫ－１ワールドマックスだよね",
                "かヤがや",
                "わいわーわ",
                "何もすることがないし",
                "なるべく",
                "誰とも話しをしたくないからだ",
            ],
        },
    )

    assert result["page_type"] == "story"
    assert result["should_translate"] is True
    assert result["skip_reason"] is None


def test_classify_preprocessed_page_keeps_early_short_dialogue_page_translatable():
    result = classify_preprocessed_page(
        page_index=13,
        total_pages=188,
        image_size=(794, 1200),
        preprocessed_payload={
            "bubbleCoords": [
                [640, 120, 675, 300],
                [600, 145, 635, 325],
                [560, 170, 595, 350],
                [520, 195, 555, 375],
                [480, 220, 515, 400],
                [440, 245, 475, 425],
                [400, 270, 435, 450],
                [360, 295, 395, 475],
                [320, 320, 355, 500],
                [280, 345, 315, 525],
                [240, 370, 275, 550],
                [200, 395, 235, 575],
            ],
            "originalTexts": [
                "魔彩死",
                "このデフ",
                "ムカつくぜえっ",
                "ひっ！！",
                "えっ",
                "えっ",
                "分ってんのか数宮",
                "魔栄死",
                "明日はマンガの日だぞ",
                "分ってるよ．．．",
                "二十世紀少年だよね",
                "．．",
            ],
        },
    )

    assert result["page_type"] == "story"
    assert result["should_translate"] is True
    assert result["skip_reason"] is None
