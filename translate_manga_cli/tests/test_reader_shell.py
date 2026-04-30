from pathlib import Path


def test_reader_shell_contains_primary_actions(client):
    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "读取文字" in html
    assert "整页翻译" in html
    assert "重做擦字" in html
    assert "重做写字" in html
    assert "原图" in html
    assert "译图" in html
    assert 'id="ocrResultList"' in html
    assert 'id="statusText"' in html


def test_reader_bundle_wires_detect_and_ocr_actions():
    bundle_path = Path(__file__).resolve().parents[1] / "src" / "app" / "static" / "app.js"
    source = bundle_path.read_text(encoding="utf-8")

    assert "/api/pipeline/detect" in source
    assert "/api/pipeline/ocr" in source
    assert "readTextBtn" in source


def test_reader_bundle_wires_redo_actions():
    bundle_path = Path(__file__).resolve().parents[1] / "src" / "app" / "static" / "app.js"
    source = bundle_path.read_text(encoding="utf-8")

    assert "/api/pipeline/redo-inpaint" in source
    assert "/api/pipeline/redo-render" in source
    assert "redoInpaintBtn" in source
    assert "redoRenderBtn" in source


def test_reader_shell_contains_editor_and_timing_panels(client):
    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="bubbleEditorPanel"' in html
    assert 'id="timingPanel"' in html
    assert "当前气泡" in html
    assert "阶段耗时" in html


def test_reader_bundle_wires_bubble_edit_actions():
    bundle_path = Path(__file__).resolve().parents[1] / "src" / "app" / "static" / "app.js"
    source = bundle_path.read_text(encoding="utf-8")

    assert "/api/pipeline/update-bubble" in source
    assert "/api/pipeline/rerender-bubble" in source
    assert "selectedBubbleIndex" in source


def test_reader_bundle_reports_total_timing_and_manual_actions():
    bundle_path = Path(__file__).resolve().parents[1] / "src" / "app" / "static" / "app.js"
    source = bundle_path.read_text(encoding="utf-8")

    assert "当前页总耗时" in source
    assert "saveBubble" in source
    assert "rerenderBubble" in source
