from pathlib import Path

from PIL import Image

import translate_manga.core.multimodal_layout as multimodal_layout
from translate_manga.core.multimodal_layout import (
    apply_multimodal_layout_assist,
    build_bubble_layout_hints,
    normalize_multimodal_layout_response,
    request_multimodal_layout,
)


def test_normalize_multimodal_layout_response_extracts_json_regions():
    response_text = """```json
{
  "regions": [
    {"id": "r1", "role": "page_number", "bbox": [0.90, 0.94, 0.98, 0.99], "orientation": "horizontal", "text": "30"},
    {"id": "r2", "role": "narration", "bbox": [50, 300, 530, 560], "orientation": "horizontal", "text": "说明"}
  ]
}
```"""

    result = normalize_multimodal_layout_response(response_text, image_size=[1000, 1200])

    assert result["status"] == "ok"
    assert result["regions"][0] == {
        "id": "r1",
        "role": "page_number",
        "bbox": [900, 1128, 980, 1188],
        "orientation": "horizontal",
        "text": "30",
        "confidence": None,
    }
    assert result["regions"][1]["role"] == "narration"
    assert result["regions"][1]["bbox"] == [50, 300, 530, 560]


def test_build_bubble_layout_hints_matches_roles_and_directions():
    layout = {
        "status": "ok",
        "regions": [
            {
                "id": "p1",
                "role": "page_number",
                "bbox": [720, 1090, 790, 1130],
                "orientation": "horizontal",
                "text": "30",
                "confidence": 0.9,
            },
            {
                "id": "n1",
                "role": "narration",
                "bbox": [50, 300, 530, 560],
                "orientation": "horizontal",
                "text": "长说明",
                "confidence": 0.8,
            },
            {
                "id": "d1",
                "role": "dialogue",
                "bbox": [550, 50, 740, 170],
                "orientation": "vertical",
                "text": "对白",
                "confidence": 0.8,
            },
        ],
    }

    hints = build_bubble_layout_hints(
        layout,
        bubble_coords=[
            [718, 1088, 792, 1132],
            [58, 306, 528, 560],
            [551, 52, 738, 168],
            [10, 10, 40, 40],
        ],
    )

    assert hints[0]["role"] == "page_number"
    assert hints[0]["suppressTranslation"] is True
    assert hints[1]["role"] == "long_narration"
    assert hints[1]["directionOverride"] == "horizontal"
    assert hints[1]["textAlignOverride"] == "start"
    assert hints[2]["role"] == "dialogue"
    assert hints[2]["directionOverride"] == "vertical"
    assert hints[3] == {}


def test_apply_multimodal_layout_assist_adds_debug_payload_and_hints(tmp_path):
    source_path = tmp_path / "page.jpg"
    source_path.write_bytes(b"not-a-real-image")
    preprocessed = {
        "bubbleCoords": [[10, 10, 50, 50]],
        "originalTexts": ["30"],
    }

    def fake_request(_source_path, _config):
        return {
            "status": "ok",
            "regions": [
                {
                    "id": "p1",
                    "role": "page_number",
                    "bbox": [8, 8, 52, 52],
                    "orientation": "horizontal",
                    "text": "30",
                    "confidence": 0.9,
                }
            ],
        }

    result = apply_multimodal_layout_assist(
        source_path,
        preprocessed,
        config={
            "enabled": True,
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "api_key": "vision-key",
        },
        request_layout=fake_request,
    )

    assert result is not preprocessed
    assert result["multimodalLayout"]["status"] == "ok"
    assert result["bubbleLayoutHints"][0]["role"] == "page_number"
    assert result["bubbleLayoutHints"][0]["suppressTranslation"] is True


def test_apply_multimodal_layout_assist_degrades_when_not_configured(tmp_path):
    source_path = tmp_path / "page.jpg"
    source_path.write_bytes(b"not-a-real-image")
    preprocessed = {"bubbleCoords": [[10, 10, 50, 50]], "originalTexts": ["30"]}

    result = apply_multimodal_layout_assist(
        source_path,
        preprocessed,
        config={"enabled": True, "model": "vision-model", "base_url": ""},
        request_layout=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network should not run")),
    )

    assert result["multimodalLayout"]["status"] == "skipped"
    assert result["multimodalLayout"]["reason"] == "not_configured"
    assert result["bubbleLayoutHints"] == [{}]


def test_apply_multimodal_layout_assist_requires_api_key(tmp_path):
    source_path = tmp_path / "page.jpg"
    source_path.write_bytes(b"not-a-real-image")
    preprocessed = {"bubbleCoords": [[10, 10, 50, 50]], "originalTexts": ["30"]}

    result = apply_multimodal_layout_assist(
        source_path,
        preprocessed,
        config={"enabled": True, "model": "vision-model", "base_url": "https://vision.example/v1", "api_key": ""},
        request_layout=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network should not run")),
    )

    assert result["multimodalLayout"]["status"] == "skipped"
    assert result["multimodalLayout"]["reason"] == "not_configured"
    assert result["bubbleLayoutHints"] == [{}]


def test_apply_multimodal_layout_assist_degrades_on_request_error(tmp_path):
    source_path = tmp_path / "page.jpg"
    source_path.write_bytes(b"not-a-real-image")
    preprocessed = {"bubbleCoords": [[10, 10, 50, 50]], "originalTexts": ["30"]}

    def fail_request(_source_path, _config):
        raise RuntimeError("vision timeout")

    result = apply_multimodal_layout_assist(
        source_path,
        preprocessed,
        config={
            "enabled": True,
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "api_key": "vision-key",
        },
        request_layout=fail_request,
    )

    assert result["multimodalLayout"]["status"] == "failed"
    assert result["multimodalLayout"]["reason"] == "vision timeout"
    assert result["bubbleLayoutHints"] == [{}]


def test_request_multimodal_layout_maps_resized_bboxes_back_to_original(monkeypatch, tmp_path):
    source_path = tmp_path / "page.jpg"
    Image.new("RGB", (2000, 1000), "white").save(source_path)
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return type(
                "Completion",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {
                                "message": type(
                                    "Message",
                                    (),
                                    {
                                        "content": (
                                            '{"regions":[{"id":"r1","role":"dialogue",'
                                            '"bbox":[100,50,300,250],"orientation":"horizontal"}]}'
                                        )
                                    },
                                )()
                            },
                        )()
                    ],
                    "usage": None,
                },
            )()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(multimodal_layout.openai, "OpenAI", FakeClient)

    result = request_multimodal_layout(
        source_path,
        {
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "api_key": "vision-key",
            "max_edge": 1000,
        },
    )

    assert result["regions"][0]["bbox"] == [200, 100, 600, 500]
    assert result["imageSize"] == [2000, 1000]
    assert result["requestImageSize"] == [1000, 500]
    prompt_text = captured["messages"][0]["content"][0]["text"]
    assert "1000x500" in prompt_text
    assert "2000x1000" in prompt_text
