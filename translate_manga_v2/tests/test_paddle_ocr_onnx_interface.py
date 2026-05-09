import sys
from pathlib import Path
from types import SimpleNamespace


SABER_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "Saber-Translator"
if str(SABER_ROOT) not in sys.path:
    sys.path.insert(0, str(SABER_ROOT))

from src.interfaces.paddle_ocr_onnx_interface import PaddleOCRHandlerONNX


def test_english_model_paths_use_v4_detector_and_language_recognizer(tmp_path):
    handler = PaddleOCRHandlerONNX()
    handler.model_base_dir = str(tmp_path / "paddle_ocr_onnx")

    det_path, rec_path, dict_path = handler._get_model_paths("english")

    assert Path(det_path) == tmp_path / "paddle_ocr_onnx" / "detection" / "v4" / "det.onnx"
    assert Path(rec_path) == tmp_path / "paddle_ocr_onnx" / "languages" / "english" / "rec.onnx"
    assert Path(dict_path) == tmp_path / "paddle_ocr_onnx" / "languages" / "english" / "dict.txt"


def test_initialize_uses_config_path_so_rapidocr_receives_custom_model_paths(tmp_path, monkeypatch):
    model_root = tmp_path / "paddle_ocr_onnx"
    det_path = model_root / "detection" / "v4" / "det.onnx"
    rec_path = model_root / "languages" / "english" / "rec.onnx"
    dict_path = model_root / "languages" / "english" / "dict.txt"
    cls_path = model_root / "cls" / "ch_ppocr_mobile_v2.0_cls_infer.onnx"
    for file_path in [det_path, rec_path, dict_path, cls_path]:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("stub", encoding="utf-8")

    captured = {}

    class FakeRapidOCR:
        def __init__(self, config_path=None, **kwargs):
            captured["config_path"] = config_path
            captured["kwargs"] = kwargs
            captured["config_text"] = Path(config_path).read_text(encoding="utf-8")

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", SimpleNamespace(RapidOCR=FakeRapidOCR))

    handler = PaddleOCRHandlerONNX()
    handler.model_base_dir = str(model_root)

    assert handler.initialize("english") is True

    assert captured["kwargs"] == {}
    assert str(det_path).replace("\\", "/") in captured["config_text"].replace("\\", "/")
    assert str(rec_path).replace("\\", "/") in captured["config_text"].replace("\\", "/")
    assert str(dict_path).replace("\\", "/") in captured["config_text"].replace("\\", "/")
