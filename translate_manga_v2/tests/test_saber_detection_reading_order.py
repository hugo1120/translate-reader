import contextlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from translate_manga.integrations import saber_loader


SABER_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "Saber-Translator"
if str(SABER_ROOT) not in sys.path:
    sys.path.insert(0, str(SABER_ROOT))


def test_detect_script_maps_ltr_reading_order_to_left_to_right(monkeypatch):
    captured = {}

    class FakeImage:
        def convert(self, _mode):
            return self

    def fake_detect(image, **kwargs):
        captured["right_to_left"] = kwargs.get("right_to_left")
        return {
            "coords": [],
            "polygons": [],
            "auto_directions": [],
            "textlines_per_bubble": [],
            "raw_mask": None,
        }

    monkeypatch.setattr("PIL.Image.open", lambda path: FakeImage())
    monkeypatch.setitem(
        sys.modules,
        "src.core.detection",
        SimpleNamespace(get_bubble_detection_result_with_auto_directions=fake_detect),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "-c",
            json.dumps({"image_path": "page.jpg", "reading_order": "ltr"}, ensure_ascii=False),
        ],
    )

    with contextlib.redirect_stdout(io.StringIO()):
        exec(saber_loader._SCRIPTS["detect"], {"__name__": "__main__"})

    assert captured["right_to_left"] is False


def test_detection_api_passes_right_to_left_to_detector_and_refinement(monkeypatch):
    from src.core import detection

    captured = {}

    class FakeDetectionResult:
        blocks = []
        mask = None
        raw_lines = []

        def to_legacy_format(self):
            return {
                "coords": [],
                "polygons": [],
                "angles": [],
            }

    def fake_detect(image, **kwargs):
        captured["detect_right_to_left"] = kwargs.get("right_to_left")
        return FakeDetectionResult()

    def fake_refine(image, result, **kwargs):
        captured["refine_right_to_left"] = kwargs.get("right_to_left")
        return result

    monkeypatch.setattr(detection, "detect", fake_detect)
    monkeypatch.setattr(detection, "apply_saber_yolo_refinement", fake_refine)

    result = detection.get_bubble_detection_result_with_auto_directions(
        Image.new("RGB", (32, 32), "white"),
        right_to_left=False,
    )

    assert result["coords"] == []
    assert captured["detect_right_to_left"] is False
    assert captured["refine_right_to_left"] is False


def test_large_image_detection_preserves_sort_direction_after_slicing(monkeypatch):
    from src.core import large_image_detection

    captured = {}

    class FakeLine:
        area = 25
        pts = np.array([[1, 1], [9, 1], [9, 9], [1, 9]], dtype=np.int32)

        def clip(self, width, height):
            captured["clipped"] = (width, height)

    class FakeDetector:
        requires_merge = False

        def _detect_raw(self, patch, **kwargs):
            captured["raw_kwargs"] = dict(kwargs)
            return [FakeLine()], None

    def fake_postprocess_blocks(blocks, im_w, im_h, **kwargs):
        captured["postprocess_kwargs"] = dict(kwargs)
        return blocks

    monkeypatch.setattr(large_image_detection, "check_needs_rearrange", lambda img_cv, target_size: (True, None))
    monkeypatch.setattr(
        large_image_detection,
        "slice_image_for_detection",
        lambda img_cv, tgt_size, verbose=False: ([np.zeros((16, 16, 3), dtype=np.uint8)], SimpleNamespace(is_rearranged=True)),
    )
    monkeypatch.setattr(
        large_image_detection,
        "transform_textlines_to_original",
        lambda patch_textlines, patch_idx, context: patch_textlines,
    )
    monkeypatch.setattr(large_image_detection, "postprocess_blocks", fake_postprocess_blocks)

    wrapper = large_image_detection.LargeImageDetectorWrapper(FakeDetector(), target_size=16)
    result = wrapper.detect(
        Image.new("RGB", (128, 512), "white"),
        merge_lines=False,
        sort_method="reading",
        right_to_left=False,
    )

    assert len(result.blocks) == 1
    assert captured["postprocess_kwargs"]["sort_method"] == "reading"
    assert captured["postprocess_kwargs"]["right_to_left"] is False
