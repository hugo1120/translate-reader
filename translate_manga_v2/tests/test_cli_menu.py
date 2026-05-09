import json
from pathlib import Path

from translate_manga.cli import menu
from translate_manga.core.translate.openai_compatible import TRANSLATION_FAILURE_TEXT


def _stub_settings():
    return {
        "paths": {},
        "render": {"layout_mode": "vertical"},
        "pipeline": {"overwrite_existing": False},
    }


def _summary(total=1, succeeded=1, skipped=0, failed=0):
    return {"total": total, "succeeded": succeeded, "skipped": skipped, "failed": failed}


def test_menu_new_task_accepts_multiple_dirs_defaults_output_to_out_and_saves_session(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir_one = tmp_path / "book-1" / "01"
    input_dir_two = tmp_path / "book-2" / "01"
    input_dir_one.mkdir(parents=True)
    input_dir_two.mkdir(parents=True)
    prompts = iter(["2", str(input_dir_one), str(input_dir_two), "", "2", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        return _summary(total=3, succeeded=3)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    normal_calls = [call for call in captured_calls if not call.get("retry_review_pages")]
    assert len(normal_calls) == 2
    assert normal_calls[0]["input_dir"] == input_dir_one
    assert normal_calls[0]["output_dir"] == input_dir_one / "out"
    assert normal_calls[0]["layout_mode"] == "vertical"
    assert normal_calls[0]["overwrite_existing"] is False
    assert normal_calls[0]["launch_mode"] == "menu"
    assert normal_calls[1]["input_dir"] == input_dir_two
    assert normal_calls[1]["output_dir"] == input_dir_two / "out"

    session = json.loads((project_root / "config" / "session.json").read_text(encoding="utf-8"))
    assert session["last_input_dirs"] == [
        input_dir_one.resolve().as_posix(),
        input_dir_two.resolve().as_posix(),
    ]
    assert session["last_input_dir"] == input_dir_one.resolve().as_posix()
    assert session["last_output_dir"] == (input_dir_one / "out").resolve().as_posix()
    assert session["last_layout_mode"] == "vertical"
    assert session["last_overwrite_existing"] is False

    combined_output = "".join(output_lines)
    assert "Translate Manga V2" in combined_output
    assert "新建任务" in combined_output
    assert "Summary: total=3 ok=3 skip=0 fail=0" in combined_output


def test_menu_new_task_selects_style3_and_saves_session(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir = tmp_path / "english-book" / "01"
    input_dir.mkdir(parents=True)
    prompts = iter(["2", str(input_dir), "", "3", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    normal_calls = [call for call in captured_calls if not call.get("retry_review_pages")]
    assert len(normal_calls) == 1
    assert normal_calls[0]["style_id"] == "style3"
    assert normal_calls[0]["layout_mode"] == "horizontal"

    session = json.loads((project_root / "config" / "session.json").read_text(encoding="utf-8"))
    assert session["last_style_id"] == "style3"
    assert session["last_layout_mode"] == "horizontal"
    assert "Style 3 horizontal EN" in "".join(output_lines)


def test_menu_new_task_splits_concatenated_pasted_paths(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir_one = tmp_path / "翻译测试日漫" / "武田信玄" / "10"
    input_dir_two = tmp_path / "翻译测试日漫" / "德川家康" / "01"
    input_dir_one.mkdir(parents=True)
    input_dir_two.mkdir(parents=True)
    prompts = iter(["2", f"{input_dir_one}{input_dir_two}", "", "2", "4"])
    captured_calls = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream([]),
        project_root=project_root,
    )

    normal_calls = [call for call in captured_calls if not call.get("retry_review_pages")]
    assert exit_code == 0
    assert [call["input_dir"] for call in normal_calls] == [input_dir_one, input_dir_two]


def test_menu_reuses_saved_multi_dir_task(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir_one = tmp_path / "book-1" / "01"
    input_dir_two = tmp_path / "book-2" / "01"
    input_dir_one.mkdir(parents=True)
    input_dir_two.mkdir(parents=True)
    config_root.joinpath("session.json").write_text(
        json.dumps(
            {
                "last_input_dirs": [input_dir_one.as_posix(), input_dir_two.as_posix()],
                "last_layout_mode": "horizontal",
                "last_overwrite_existing": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prompts = iter(["1", "4"])
    captured_calls = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        return _summary(total=2, succeeded=2)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream([]),
        project_root=project_root,
    )

    assert exit_code == 0
    normal_calls = [call for call in captured_calls if not call.get("retry_review_pages")]
    assert [call["input_dir"] for call in normal_calls] == [input_dir_one, input_dir_two]
    assert [call["output_dir"] for call in normal_calls] == [input_dir_one / "out", input_dir_two / "out"]
    assert all(call["layout_mode"] == "horizontal" for call in normal_calls)
    assert all(call["overwrite_existing"] is False for call in normal_calls)


def test_menu_reuses_saved_style3_task(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "english-book" / "01"
    input_dir.mkdir(parents=True)
    config_root.joinpath("session.json").write_text(
        json.dumps(
            {
                "last_input_dirs": [input_dir.as_posix()],
                "last_style_id": "style3",
                "last_layout_mode": "vertical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prompts = iter(["1", "4"])
    captured_calls = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream([]),
        project_root=project_root,
    )

    assert exit_code == 0
    normal_calls = [call for call in captured_calls if not call.get("retry_review_pages")]
    assert len(normal_calls) == 1
    assert normal_calls[0]["style_id"] == "style3"
    assert normal_calls[0]["layout_mode"] == "horizontal"


def test_menu_scan_and_fix_uses_saved_task_and_retry_review_pages(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    input_dir.mkdir(parents=True)
    debug_root = input_dir / "out" / "_debug"
    debug_root.mkdir(parents=True)
    (debug_root / "failed-translations.tsv").write_text(
        "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath\n"
        f"001.jpg\t001.translated.png\ttranslated\ttranslation_failed\t{input_dir / '001.jpg'}\t{input_dir / 'out' / '001.translated.png'}\n",
        encoding="utf-8",
    )
    config_root.joinpath("session.json").write_text(
        json.dumps({"last_input_dirs": [input_dir.as_posix()], "last_layout_mode": "vertical"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompts = iter(["3", "1", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        (debug_root / "failed-translations.tsv").write_text(
            "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath\n",
            encoding="utf-8",
        )
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert len(captured_calls) == 1
    assert captured_calls[0]["input_dir"] == input_dir
    assert captured_calls[0]["output_dir"] == input_dir / "out"
    assert captured_calls[0]["retry_review_pages"] is True
    assert captured_calls[0]["overwrite_existing"] is True
    assert captured_calls[0]["launch_mode"] == "menu-scan-fix"
    combined_output = "".join(output_lines)
    assert "扫描并纠正错误" in combined_output
    assert "RETRY [1/1] round=1/5 review_pages=1" in combined_output
    assert "未发现遗留错误" in combined_output


def test_menu_scan_and_fix_falls_back_to_page_json_when_review_files_are_empty(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    input_dir.mkdir(parents=True)
    debug_root = input_dir / "out" / "_debug"
    pages_root = debug_root / "pages"
    pages_root.mkdir(parents=True)
    (debug_root / "review-pages.txt").write_text("", encoding="utf-8")
    (pages_root / "001.json").write_text(
        json.dumps(
            {
                "sourceName": "001.jpg",
                "status": "translated",
                "needsReview": False,
                "reviewReasons": [],
                "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                "translation": {
                    "translatedTexts": [TRANSLATION_FAILURE_TEXT],
                    "ocrRetry": {"reasons": ["translation_failed"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_root.joinpath("session.json").write_text(
        json.dumps({"last_input_dirs": [input_dir.as_posix()], "last_layout_mode": "vertical"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompts = iter(["3", "1", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        (pages_root / "001.json").write_text(
            json.dumps(
                {
                    "sourceName": "001.jpg",
                    "status": "translated",
                    "needsReview": False,
                    "reviewReasons": [],
                    "translatedTexts": ["修复后译文"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert len(captured_calls) == 1
    assert captured_calls[0]["retry_review_pages"] is True
    assert "RETRY [1/1] round=1/5 review_pages=1" in "".join(output_lines)


def test_menu_scan_and_fix_detects_missing_output_pages(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    output_dir = input_dir / "out"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (input_dir / "001.jpg").write_bytes(b"source")
    (input_dir / "002.jpg").write_bytes(b"source")
    (output_dir / "001.translated.png").write_bytes(b"translated")
    config_root.joinpath("session.json").write_text(
        json.dumps({"last_input_dirs": [input_dir.as_posix()], "last_layout_mode": "vertical"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompts = iter(["3", "1", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        (output_dir / "002.translated.png").write_bytes(b"translated")
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert len(captured_calls) == 1
    assert captured_calls[0]["retry_review_pages"] is True
    combined_output = "".join(output_lines)
    assert "RETRY [1/1] round=1/5 review_pages=1" in combined_output
    assert "未发现遗留错误" in combined_output


def test_menu_missing_output_scan_uses_numeric_output_padding(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    config_root.mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    output_dir = input_dir / "out"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    for name in ["1.jpg", "2.jpg", "10.jpg"]:
        (input_dir / name).write_bytes(b"source")
    (output_dir / "01.translated.png").write_bytes(b"translated")
    (output_dir / "10.translated.png").write_bytes(b"translated")
    config_root.joinpath("session.json").write_text(
        json.dumps({"last_input_dirs": [input_dir.as_posix()], "last_layout_mode": "vertical"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompts = iter(["3", "1", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        (output_dir / "02.translated.png").write_bytes(b"translated")
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert len(captured_calls) == 1
    combined_output = "".join(output_lines)
    assert "RETRY [1/1] round=1/5 review_pages=1" in combined_output
    assert "未发现遗留错误" in combined_output


def test_menu_full_translation_auto_retries_review_pages_until_clean(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    input_dir.mkdir(parents=True)
    debug_root = input_dir / "out" / "_debug"
    prompts = iter(["2", str(input_dir), "", "1", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def write_failed_debug(source_name):
        debug_root.mkdir(parents=True, exist_ok=True)
        (debug_root / "failed-translations.tsv").write_text(
            "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath\n"
            f"{source_name}\t{Path(source_name).stem}.translated.png\ttranslated\ttranslation_failed\t{input_dir / source_name}\t{input_dir / 'out' / (Path(source_name).stem + '.translated.png')}\n",
            encoding="utf-8",
        )

    def clear_failed_debug():
        debug_root.mkdir(parents=True, exist_ok=True)
        (debug_root / "failed-translations.tsv").write_text(
            "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath\n",
            encoding="utf-8",
        )

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        if kwargs.get("retry_review_pages"):
            clear_failed_debug()
            return _summary(total=1, succeeded=1)
        write_failed_debug("001.jpg")
        return _summary(total=10, succeeded=10)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    assert len(captured_calls) == 2
    assert captured_calls[0]["retry_review_pages"] is False
    assert captured_calls[0]["layout_mode"] == "horizontal"
    assert captured_calls[1]["retry_review_pages"] is True
    assert captured_calls[1]["overwrite_existing"] is True
    assert captured_calls[1]["launch_mode"] == "menu-auto-retry"
    combined_output = "".join(output_lines)
    assert "RETRY [1/1] round=1/5 review_pages=1" in combined_output
    assert "未发现遗留错误" in combined_output


def test_menu_auto_retry_stops_after_five_rounds_and_reports_remaining(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    input_dir = tmp_path / "book" / "01"
    input_dir.mkdir(parents=True)
    debug_root = input_dir / "out" / "_debug"
    prompts = iter(["2", str(input_dir), "", "2", "4"])
    captured_calls = []
    output_lines = []

    monkeypatch.setattr(menu, "load_settings", lambda project_root=None: _stub_settings())

    def write_failed_debug():
        debug_root.mkdir(parents=True, exist_ok=True)
        (debug_root / "failed-translations.tsv").write_text(
            "sourceName\toutputName\tstatus\treasons\tsourcePath\toutputPath\n"
            f"001.jpg\t001.translated.png\ttranslated\ttranslation_failed\t{input_dir / '001.jpg'}\t{input_dir / 'out' / '001.translated.png'}\n",
            encoding="utf-8",
        )

    def fake_run_batch_translation(**kwargs):
        captured_calls.append(kwargs)
        write_failed_debug()
        return _summary(total=1, succeeded=1)

    monkeypatch.setattr(menu, "run_batch_translation", fake_run_batch_translation)

    exit_code = menu.run_interactive_menu(
        input_func=lambda prompt="": next(prompts),
        output_stream=menu._MemoryStream(output_lines),
        project_root=project_root,
    )

    assert exit_code == 0
    retry_calls = [call for call in captured_calls if call.get("retry_review_pages")]
    assert len(retry_calls) == 5
    combined_output = "".join(output_lines)
    assert "仍有 1 页需要人工复查" in combined_output
    assert str(debug_root / "failed-translations.tsv") in combined_output
