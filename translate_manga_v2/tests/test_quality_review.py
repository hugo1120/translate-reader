import json

from translate_manga.cli.quality_review import (
    load_reviewable_page_records,
    parse_quality_review_response,
    read_quality_review_entries,
    run_quality_review,
    write_quality_review_tsv,
)


def test_parse_quality_review_response_accepts_json_issues():
    content = json.dumps(
        {
            "issues": [
                {
                    "sourceName": "002.jpg",
                    "outputName": "002.translated.png",
                    "reasons": ["quality_awkward_chinese", "quality_untranslated_source"],
                    "confidence": 0.91,
                    "comment": "第二句仍有日文，中文也不通顺。",
                },
                {"sourceName": "", "reasons": ["quality_mistranslation"]},
            ]
        },
        ensure_ascii=False,
    )

    entries = parse_quality_review_response(content)

    assert entries == [
        {
            "sourceName": "002.jpg",
            "outputName": "002.translated.png",
            "reviewReasons": ["quality_awkward_chinese", "quality_untranslated_source"],
            "confidence": 0.91,
            "comment": "第二句仍有日文，中文也不通顺。",
        }
    ]


def test_write_and_read_quality_review_tsv(tmp_path):
    output_dir = tmp_path / "out"
    entries = [
        {
            "sourceName": "010.jpg",
            "outputName": "010.translated.png",
            "reviewReasons": ["quality_mistranslation"],
            "confidence": 0.8,
            "comment": "人名译法和前文不一致。",
        }
    ]

    tsv_path = write_quality_review_tsv(output_dir, entries)
    loaded = read_quality_review_entries(output_dir)

    assert tsv_path == output_dir / "_debug" / "quality-review.tsv"
    assert loaded == entries


def test_load_reviewable_page_records_reads_debug_pages_in_page_order(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    for source_name, page_index in [("010.jpg", 10), ("002.jpg", 2)]:
        (pages_root / f"{source_name.removesuffix('.jpg')}.json").write_text(
            json.dumps(
                {
                    "sourceName": source_name,
                    "outputName": f"{source_name.removesuffix('.jpg')}.translated.png",
                    "pageIndex": page_index,
                    "status": "translated",
                    "needsReview": False,
                    "originalTexts": [f"原文{page_index}"],
                    "translatedTexts": [f"译文{page_index}"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    records = load_reviewable_page_records(tmp_path / "out")

    assert [record["sourceName"] for record in records] == ["002.jpg", "010.jpg"]
    assert records[0]["originalTexts"] == ["原文2"]
    assert records[0]["translatedTexts"] == ["译文2"]


def test_run_quality_review_invokes_injected_reviewer_and_writes_only_flagged_pages(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    for source_name, original, translated in [
        ("001.jpg", "殿", "主公"),
        ("002.jpg", "行くぞ", "イクゾ"),
    ]:
        (pages_root / f"{source_name.removesuffix('.jpg')}.json").write_text(
            json.dumps(
                {
                    "sourceName": source_name,
                    "outputName": f"{source_name.removesuffix('.jpg')}.translated.png",
                    "pageIndex": int(source_name[:3]),
                    "status": "translated",
                    "needsReview": False,
                    "originalTexts": [original],
                    "translatedTexts": [translated],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    calls = []

    def fake_reviewer(*, messages, model, base_url, api_key):
        calls.append(messages)
        return json.dumps(
            {
                "issues": [
                    {
                        "sourceName": "002.jpg",
                        "reasons": ["quality_untranslated_source"],
                        "confidence": 0.95,
                        "comment": "译文仍是片假名。",
                    }
                ]
            },
            ensure_ascii=False,
        )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=fake_reviewer,
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
        chunk_size=1,
    )

    assert len(calls) == 2
    assert entries == [
        {
            "sourceName": "002.jpg",
            "outputName": "002.translated.png",
            "reviewReasons": ["quality_untranslated_source"],
            "confidence": 0.96,
            "comment": "译文仍含日文假名，可能是未翻译拟声词或原文残留。; 译文仍是片假名。",
        }
    ]
    assert read_quality_review_entries(tmp_path / "out") == entries


def test_run_quality_review_adds_prompt_profile_mismatch_heuristic(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "outputName": "001.translated.png",
                "pageIndex": 1,
                "status": "translated",
                "needsReview": False,
                "originalTexts": ["面白い", "来い"],
                "translatedTexts": ["很有意思", "过来"],
                "preprocessedPayload": {
                    "bubbleCoords": [[10, 20, 100, 150], [130, 20, 170, 140]],
                    "autoDirections": ["h", "v"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=lambda **kwargs: '{"issues":[]}',
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
        style_profile={"style_id": "style2", "layout_mode": "vertical", "reading_order": "rtl", "source_language": "japanese"},
    )

    assert entries == [
        {
            "sourceName": "001.jpg",
            "outputName": "001.translated.png",
            "reviewReasons": ["quality_prompt_profile_mismatch"],
            "confidence": 0.95,
            "comment": "页面包含横排气泡，当前竖排样式可能导致嵌字方向不匹配。",
        }
    ]


def test_run_quality_review_flags_low_confidence_fallback_ocr_noise(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "outputName": "001.translated.png",
                "pageIndex": 1,
                "status": "translated",
                "needsReview": False,
                "originalTexts": ["インター くっ！？"],
                "translatedTexts": ["哒 咕!?"],
                "preprocessedPayload": {
                    "bubbleCoords": [[10, 20, 100, 150]],
                    "autoDirections": ["v"],
                    "ocrResults": [
                        {
                            "text": "インター くっ！？",
                            "engine": "manga_ocr",
                            "confidence": 0.014,
                            "fallbackUsed": True,
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=lambda **kwargs: '{"issues":[]}',
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
    )

    assert entries == [
        {
            "sourceName": "001.jpg",
            "outputName": "001.translated.png",
            "reviewReasons": ["quality_ocr_noise"],
            "confidence": 0.9,
            "comment": "页面包含低置信 OCR 回退结果，当前译文可能直接放大了 OCR 噪声。",
        }
    ]


def test_run_quality_review_flags_untranslated_kana_residual(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "outputName": "001.translated.png",
                "pageIndex": 1,
                "status": "translated",
                "needsReview": False,
                "originalTexts": ["ワウン ワウン"],
                "translatedTexts": ["ワウン ワウン"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=lambda **kwargs: '{"issues":[]}',
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
    )

    assert entries == [
        {
            "sourceName": "001.jpg",
            "outputName": "001.translated.png",
            "reviewReasons": ["quality_untranslated_source"],
            "confidence": 0.96,
            "comment": "译文仍含日文假名，可能是未翻译拟声词或原文残留。",
        }
    ]


def test_run_quality_review_flags_latin_and_numeric_ocr_residue(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    for source_name, page_index, original, translated in [
        ("001.jpg", 1, "t", "t"),
        ("002.jpg", 2, "いまごろ クマが…12", "这种时候居然有熊…1"),
        ("003.jpg", 3, "テレビ", "看TV"),
        ("004.jpg", 4, "カムイ伝2", "卡姆伊传2"),
    ]:
        (pages_root / f"{source_name.removesuffix('.jpg')}.json").write_text(
            json.dumps(
                {
                    "sourceName": source_name,
                    "outputName": f"{source_name.removesuffix('.jpg')}.translated.png",
                    "pageIndex": page_index,
                    "status": "translated",
                    "needsReview": False,
                    "originalTexts": [original],
                    "translatedTexts": [translated],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=lambda **kwargs: '{"issues":[]}',
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
        style_profile={"source_language": "japanese"},
    )

    assert entries == [
        {
            "sourceName": "001.jpg",
            "outputName": "001.translated.png",
            "reviewReasons": ["quality_ocr_noise"],
            "confidence": 0.91,
            "comment": "译文包含孤立拉丁字母或尾部数字残留，疑似 OCR 噪声未清理。",
        },
        {
            "sourceName": "002.jpg",
            "outputName": "002.translated.png",
            "reviewReasons": ["quality_ocr_noise"],
            "confidence": 0.91,
            "comment": "译文包含孤立拉丁字母或尾部数字残留，疑似 OCR 噪声未清理。",
        },
    ]


def test_run_quality_review_flags_dense_long_narration_block(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    long_text = (
        "どうも、オオカミの生活にたちいりすぎたようだ。"
        "しかも、この白オオカミの成長は、この物語に同時的にあつかわれている人間社会の部分とは関係していない。"
        "したがって白オオカミが仲間からうけた試練や、その生活の推移だけを見てほしい。"
    )
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "outputName": "001.translated.png",
                "pageIndex": 1,
                "status": "translated",
                "needsReview": False,
                "originalTexts": [long_text],
                "translatedTexts": ["这是一大段说明文，目前被直接整块塞进同一个框里。"],
                "preprocessedPayload": {
                    "bubbleCoords": [[40, 240, 700, 680]],
                    "autoDirections": ["v"],
                    "ocrResults": [
                        {
                            "text": long_text,
                            "engine": "manga_ocr",
                            "confidence": 0.62,
                            "fallbackUsed": True,
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = run_quality_review(
        tmp_path / "out",
        reviewer=lambda **kwargs: '{"issues":[]}',
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
    )

    assert entries == [
        {
            "sourceName": "001.jpg",
            "outputName": "001.translated.png",
            "reviewReasons": ["quality_ocr_noise", "quality_too_long_for_bubble"],
            "confidence": 0.92,
            "comment": (
                "页面包含长说明块 OCR 回退结果，当前译文可能直接放大了 OCR 噪声。;"
                " 页面包含长说明块，当前译文可能被整段塞入单个气泡。"
            ),
        }
    ]


def test_run_quality_review_reports_chunk_progress(tmp_path):
    pages_root = tmp_path / "out" / "_debug" / "pages"
    pages_root.mkdir(parents=True)
    for source_name in ["001.jpg", "002.jpg"]:
        (pages_root / f"{source_name.removesuffix('.jpg')}.json").write_text(
            json.dumps(
                {
                    "sourceName": source_name,
                    "outputName": f"{source_name.removesuffix('.jpg')}.translated.png",
                    "pageIndex": int(source_name[:3]),
                    "status": "translated",
                    "needsReview": False,
                    "originalTexts": [source_name],
                    "translatedTexts": [f"译文{source_name}"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    events = []

    def fake_reviewer(*, messages, model, base_url, api_key):
        return '{"issues":[]}'

    run_quality_review(
        tmp_path / "out",
        reviewer=fake_reviewer,
        model="test-model",
        base_url="https://example.test/v1",
        api_key="test-key",
        chunk_size=1,
        progress_callback=events.append,
    )

    assert events == [
        {"event": "start", "totalPages": 2, "totalChunks": 2},
        {
            "event": "chunk_start",
            "currentChunk": 1,
            "totalChunks": 2,
            "pageCount": 1,
            "firstSourceName": "001.jpg",
            "lastSourceName": "001.jpg",
        },
        {
            "event": "chunk_done",
            "currentChunk": 1,
            "totalChunks": 2,
            "flaggedPages": 0,
        },
        {
            "event": "chunk_start",
            "currentChunk": 2,
            "totalChunks": 2,
            "pageCount": 1,
            "firstSourceName": "002.jpg",
            "lastSourceName": "002.jpg",
        },
        {
            "event": "chunk_done",
            "currentChunk": 2,
            "totalChunks": 2,
            "flaggedPages": 0,
        },
        {"event": "done", "flaggedPages": 0},
    ]
