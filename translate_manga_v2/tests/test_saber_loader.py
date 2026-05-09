import json
import importlib.util
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path

from PIL import Image, ImageChops

import pytest

from translate_manga.integrations import saber_loader


SABER_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "Saber-Translator"
if str(SABER_ROOT) not in sys.path:
    sys.path.insert(0, str(SABER_ROOT))


def test_extract_json_payload_ignores_leading_logs():
    stdout = '\n'.join(
        [
            'CUDA 不可用，回退到 CPU',
            'SaberYOLO 二阶段纠错失败，回退原检测结果',
            '{"bubbleCoords": [[1, 2, 3, 4]], "autoDirections": ["vertical"]}',
        ]
    )

    result = saber_loader._extract_json_payload(stdout)

    assert result == {
        "bubbleCoords": [[1, 2, 3, 4]],
        "autoDirections": ["vertical"],
    }


def test_resolve_saber_python_prefers_env_var(monkeypatch):
    monkeypatch.setenv("TRANSLATE_MANGA_CLI_SABER_PYTHON", "D:/custom/python.exe")

    result = saber_loader._resolve_saber_python_path()

    assert result == "D:/custom/python.exe"


def test_resolve_saber_python_prefers_local_venv310(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSLATE_MANGA_CLI_SABER_PYTHON", raising=False)
    python_path = tmp_path / ".venv310" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    result = saber_loader._resolve_saber_python_path(project_root=tmp_path)

    assert result == str(python_path)


def test_resolve_saber_python_does_not_depend_on_sibling_translate_reader_venv310(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSLATE_MANGA_CLI_SABER_PYTHON", raising=False)
    project_root = tmp_path / "translate_manga_cli"
    sibling_python = tmp_path / "translate-reader" / ".venv310" / "Scripts" / "python.exe"
    sibling_python.parent.mkdir(parents=True)
    sibling_python.write_text("", encoding="utf-8")

    result = saber_loader._resolve_saber_python_path(project_root=project_root)

    assert result == sys.executable


def test_run_saber_task_parses_json_after_logs(monkeypatch):
    captured = {}

    def fake_run(args, cwd, capture_output, env=None, text=True, encoding=None, errors=None, timeout=None, input=None):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["env"] = env
        captured["encoding"] = encoding
        captured["errors"] = errors
        captured["input"] = input
        return SimpleNamespace(
            returncode=0,
            stdout='日志\\n{"bubbleCoords": [[10, 20, 30, 40]]}',
            stderr="",
        )

    monkeypatch.setattr(saber_loader.subprocess, "run", fake_run)
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: "D:/fake/python.exe")

    result = saber_loader.run_saber_task("detect", {"image_path": "demo.jpg"})

    assert result == {"bubbleCoords": [[10, 20, 30, 40]]}
    assert captured["args"][0] == "D:/fake/python.exe"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert json.loads(captured["input"]) == {"image_path": "demo.jpg"}


def test_saber_ocr_scripts_read_source_language_from_payload():
    expected = 'source_language=payload.get("source_language", "japanese")'
    assert expected in saber_loader._SCRIPTS["ocr"]
    assert expected in saber_loader._SCRIPTS["preprocess"]


def test_run_saber_task_supports_render_single(monkeypatch):
    captured = {}

    def fake_run(args, cwd, capture_output, env=None, text=True, encoding=None, errors=None, timeout=None, input=None):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["env"] = env
        captured["encoding"] = encoding
        captured["errors"] = errors
        captured["input"] = input
        return SimpleNamespace(
            returncode=0,
            stdout='{"translatedImagePath": "page.translated.png", "bubbleStates": []}',
            stderr="",
        )

    monkeypatch.setattr(saber_loader.subprocess, "run", fake_run)
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: "D:/fake/python.exe")

    result = saber_loader.run_saber_task(
        "render_single",
        {
            "clean_image_path": "clean.png",
            "output_path": "page.translated.png",
            "bubble_states": [],
            "bubble_index": 0,
        },
    )

    assert result["translatedImagePath"] == "page.translated.png"
    assert captured["args"][0] == "D:/fake/python.exe"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert json.loads(captured["input"]) == {
        "clean_image_path": "clean.png",
        "output_path": "page.translated.png",
        "bubble_states": [],
        "bubble_index": 0,
    }


def test_run_saber_task_render_script_normalizes_short_direction_codes(monkeypatch, tmp_path):
    clean_path = tmp_path / "clean.png"
    clean_path.write_bytes(b"")
    payload = {
        "clean_image_path": str(clean_path),
        "page_id": "page-0001",
        "output_path": str(tmp_path / "page.translated.png"),
        "auto_font_size": False,
        "bubbles": [
            {
                "coords": [10, 20, 40, 60],
                "translatedText": "来吧",
                "textDirection": "v",
                "autoTextDirection": "v",
                "layoutProfile": "vertical_layout2",
            },
            {
                "coords": [50, 20, 120, 60],
                "translatedText": "诶",
                "textDirection": "h",
                "autoTextDirection": "h",
            },
        ],
    }

    captured = {}

    class FakeImage:
        def copy(self):
            return self

        def convert(self, _mode):
            return self

        def save(self, path):
            captured["saved_path"] = path

    class FakeBubbleState:
        def __init__(self, text_direction, auto_text_direction):
            self.text_direction = text_direction
            self.auto_text_direction = auto_text_direction

        def to_dict(self):
            return {
                "textDirection": self.text_direction,
                "autoTextDirection": self.auto_text_direction,
            }

        @classmethod
        def from_dict(cls, data):
            state = cls(data.get("textDirection"), data.get("autoTextDirection"))
            captured.setdefault("states", []).append(state)
            return state

    def fake_render_with_states(image, bubble_states, use_lama=False, fill_color="#FFFFFF", auto_font_size=False):
        captured["bubble_states"] = bubble_states
        return image

    fake_image = FakeImage()
    monkeypatch.setattr("PIL.Image.open", lambda path: fake_image)
    monkeypatch.setitem(sys.modules, "src.core.config_models", SimpleNamespace(BubbleState=FakeBubbleState))
    monkeypatch.setitem(sys.modules, "src.core.rendering", SimpleNamespace(re_render_with_states=fake_render_with_states))

    script = saber_loader._SCRIPTS["render"]
    globals_dict = {"__name__": "__main__"}
    monkeypatch.setattr(sys, "argv", ["-c", json.dumps(payload)])

    import io
    import contextlib

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exec(script, globals_dict)

    assert [state.text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert [state.auto_text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert getattr(captured["states"][0], "_layout_profile", None) == "vertical_layout2"


def test_run_saber_task_render_vertical_layout2_draws_visible_text(monkeypatch, tmp_path):
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: sys.executable)

    clean_path = tmp_path / "clean.png"
    output_path = tmp_path / "translated.png"
    Image.new("RGB", (220, 260), "white").save(clean_path)

    result = saber_loader.run_saber_task(
        "render",
        {
            "clean_image_path": str(clean_path),
            "page_id": "page-0001",
            "output_path": str(output_path),
            "auto_font_size": False,
            "bubbles": [
                {
                    "coords": [60, 40, 150, 200],
                    "translatedText": "真的很准呢",
                    "textDirection": "vertical",
                    "autoTextDirection": "vertical",
                    "fontSize": 20,
                    "fontFamily": "fonts/汉仪正圆-65W.TTF",
                    "textColor": "#111111",
                    "strokeEnabled": False,
                    "strokeWidth": 0,
                    "lineSpacing": 1.04,
                    "textAlign": "center",
                    "layoutProfile": "vertical_layout2",
                }
            ],
        },
    )

    assert result["translatedImagePath"] == str(output_path)

    clean_image = Image.open(clean_path).convert("RGB")
    translated_image = Image.open(output_path).convert("RGB")
    diff = ImageChops.difference(clean_image, translated_image)

    assert diff.getbbox() is not None


def test_run_saber_task_render_vertical_layout2_keeps_compact_column_spacing(monkeypatch, tmp_path):
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: sys.executable)

    clean_path = tmp_path / "clean.png"
    output_path = tmp_path / "translated.png"
    Image.new("RGB", (260, 260), "white").save(clean_path)

    result = saber_loader.run_saber_task(
        "render",
        {
            "clean_image_path": str(clean_path),
            "page_id": "page-0002",
            "output_path": str(output_path),
            "auto_font_size": False,
            "bubbles": [
                {
                    "coords": [70, 30, 180, 140],
                    "translatedText": "现代人或多或少心里都有空隙",
                    "textDirection": "vertical",
                    "autoTextDirection": "vertical",
                    "fontSize": 20,
                    "fontFamily": "fonts/汉仪正圆-65W.TTF",
                    "textColor": "#111111",
                    "strokeEnabled": False,
                    "strokeWidth": 0,
                    "lineSpacing": 1.04,
                    "textAlign": "center",
                    "layoutProfile": "vertical_layout2",
                }
            ],
        },
    )

    assert result["translatedImagePath"] == str(output_path)

    clean_image = Image.open(clean_path).convert("RGB")
    translated_image = Image.open(output_path).convert("RGB")
    diff = ImageChops.difference(clean_image, translated_image)
    bbox = diff.getbbox()

    assert bbox is not None
    assert (bbox[2] - bbox[0]) <= 80


def test_run_saber_task_render_vertical_layout2_prefers_phrase_breaks(monkeypatch, tmp_path):
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: sys.executable)

    clean_path = tmp_path / "clean.png"
    output_path = tmp_path / "translated.png"
    Image.new("RGB", (260, 260), "white").save(clean_path)

    result = saber_loader.run_saber_task(
        "render",
        {
            "clean_image_path": str(clean_path),
            "page_id": "page-0003",
            "output_path": str(output_path),
            "auto_font_size": False,
            "bubbles": [
                {
                    "coords": [70, 30, 180, 150],
                    "translatedText": "每天早上6点30分 从月见丘站出发…",
                    "textDirection": "vertical",
                    "autoTextDirection": "vertical",
                    "fontSize": 20,
                    "fontFamily": "fonts/汉仪正圆-65W.TTF",
                    "textColor": "#111111",
                    "strokeEnabled": False,
                    "strokeWidth": 0,
                    "lineSpacing": 1.04,
                    "textAlign": "center",
                    "layoutProfile": "vertical_layout2",
                }
            ],
        },
    )

    assert result["translatedImagePath"] == str(output_path)

    clean_image = Image.open(clean_path).convert("RGB")
    translated_image = Image.open(output_path).convert("RGB")
    diff = ImageChops.difference(clean_image, translated_image)
    bbox = diff.getbbox()

    assert bbox is not None
    assert (bbox[2] - bbox[0]) <= 88


def test_vertical_layout2_compact_lines_prefers_space_boundaries():
    import importlib.util

    module_path = SABER_ROOT / "src" / "core" / "rendering.py"
    spec = importlib.util.spec_from_file_location("saber_rendering_for_test", module_path)
    rendering = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None

    old_modules = {}
    for package_name, package_path in [
        ("src", SABER_ROOT / "src"),
        ("src.core", SABER_ROOT / "src" / "core"),
        ("src.shared", SABER_ROOT / "src" / "shared"),
    ]:
        old_modules[package_name] = sys.modules.get(package_name)
        package = old_modules[package_name]
        if package is None:
            package = type(sys)(package_name)
            package.__path__ = [str(package_path)]
            sys.modules[package_name] = package
    try:
        spec.loader.exec_module(rendering)
    finally:
        for package_name, old_module in old_modules.items():
            if old_module is None:
                sys.modules.pop(package_name, None)
            else:
                sys.modules[package_name] = old_module

    font = rendering.get_font("fonts/汉仪正圆-65W.TTF", 20)
    lines, heights = rendering._build_vertical_layout2_compact_lines(
        "每天早上6点30分 从月见丘站出发…",
        font,
        120,
        "fonts/汉仪正圆-65W.TTF",
    )

    assert lines == ["每天早上6", "点<H>30</H>分", "从月见丘站", "出发…"]
    assert heights == [105, 63, 105, 63]


def test_worker_render_normalizes_short_direction_codes(monkeypatch, tmp_path):
    payload = {
        "operation": "render",
        "payload": {
            "clean_image_path": str(tmp_path / "clean.png"),
            "output_path": str(tmp_path / "page.translated.png"),
            "auto_font_size": False,
            "bubbles": [
                {"coords": [10, 20, 40, 60], "translatedText": "来吧", "textDirection": "v", "autoTextDirection": "v", "layoutProfile": "vertical_layout2"},
                {"coords": [50, 20, 120, 60], "translatedText": "诶", "textDirection": "h", "autoTextDirection": "h"},
            ],
        },
        "id": 1,
    }
    captured = {}

    class FakeImage:
        def copy(self):
            return self

        def convert(self, _mode):
            return self

        def save(self, path):
            captured["saved_path"] = path

    class FakeBubbleState:
        def __init__(self, text_direction, auto_text_direction):
            self.text_direction = text_direction
            self.auto_text_direction = auto_text_direction
            self.translated_text = ""
            self.coords = (0, 0, 0, 0)
            self.font_family = "font.ttf"

        def to_dict(self):
            return {
                "textDirection": self.text_direction,
                "autoTextDirection": self.auto_text_direction,
            }

        @classmethod
        def from_dict(cls, data):
            state = cls(data.get("textDirection"), data.get("autoTextDirection"))
            captured.setdefault("states", []).append(state)
            return state

    def fake_re_render_with_states(image, bubble_states, use_lama=False, auto_font_size=False):
        captured["bubble_states"] = bubble_states
        return image

    monkeypatch.setattr("PIL.Image.open", lambda path: FakeImage())
    monkeypatch.setitem(sys.modules, "src.core.config_models", SimpleNamespace(BubbleState=FakeBubbleState))
    monkeypatch.setitem(
        sys.modules,
        "src.core.rendering",
        SimpleNamespace(
            calculate_auto_font_size=lambda *args, **kwargs: 24,
            re_render_with_states=fake_re_render_with_states,
            render_single_bubble_unified=lambda image, bubble_states, bubble_index: image,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.color_extractor",
        SimpleNamespace(extract_bubble_colors=lambda *args, **kwargs: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.detection",
        SimpleNamespace(get_bubble_detection_result_with_auto_directions=lambda image: {}),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.inpainting",
        SimpleNamespace(inpaint_bubbles=lambda *args, **kwargs: (None, None)),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.ocr",
        SimpleNamespace(recognize_ocr_results_in_bubbles=lambda *args, **kwargs: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.ocr_types",
        SimpleNamespace(
            extract_texts_from_ocr_results=lambda results: [],
            ocr_results_to_dicts=lambda results: [],
        ),
    )

    worker_globals = {"__name__": "__main__"}
    old_stdin = sys.stdin
    try:
        import io
        import contextlib

        sys.stdin = io.StringIO(json.dumps(payload) + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            exec(saber_loader._WORKER_SCRIPT, worker_globals)
    finally:
        sys.stdin = old_stdin

    assert [state.text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert [state.auto_text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert getattr(captured["states"][0], "_layout_profile", None) == "vertical_layout2"


def test_worker_render_single_normalizes_short_direction_codes(monkeypatch, tmp_path):
    payload = {
        "operation": "render_single",
        "payload": {
            "clean_image_path": str(tmp_path / "clean.png"),
            "output_path": str(tmp_path / "page.translated.png"),
            "bubble_index": 0,
            "bubble_states": [
                {"coords": [10, 20, 40, 60], "translatedText": "来吧", "textDirection": "v", "autoTextDirection": "v", "layoutProfile": "vertical_layout2"},
                {"coords": [50, 20, 120, 60], "translatedText": "诶", "textDirection": "h", "autoTextDirection": "h"},
            ],
        },
        "id": 1,
    }
    captured = {}

    class FakeImage:
        def copy(self):
            return self

        def convert(self, _mode):
            return self

        def save(self, path):
            captured["saved_path"] = path

    class FakeBubbleState:
        def __init__(self, text_direction, auto_text_direction):
            self.text_direction = text_direction
            self.auto_text_direction = auto_text_direction
            self.translated_text = "x"
            self.coords = (0, 0, 10, 10)
            self.font_family = "font.ttf"
            self.font_size = 0

        def to_dict(self):
            return {
                "textDirection": self.text_direction,
                "autoTextDirection": self.auto_text_direction,
            }

        @classmethod
        def from_dict(cls, data):
            state = cls(data.get("textDirection"), data.get("autoTextDirection"))
            captured.setdefault("states", []).append(state)
            return state

    monkeypatch.setattr("PIL.Image.open", lambda path: FakeImage())
    monkeypatch.setitem(sys.modules, "src.core.config_models", SimpleNamespace(BubbleState=FakeBubbleState))
    monkeypatch.setitem(
        sys.modules,
        "src.core.rendering",
        SimpleNamespace(
            calculate_auto_font_size=lambda *args, **kwargs: 24,
            re_render_with_states=lambda image, bubble_states, use_lama=False, auto_font_size=False: image,
            render_single_bubble_unified=lambda image, bubble_states, bubble_index: image,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.color_extractor",
        SimpleNamespace(extract_bubble_colors=lambda *args, **kwargs: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.detection",
        SimpleNamespace(get_bubble_detection_result_with_auto_directions=lambda image: {}),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.inpainting",
        SimpleNamespace(inpaint_bubbles=lambda *args, **kwargs: (None, None)),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.ocr",
        SimpleNamespace(recognize_ocr_results_in_bubbles=lambda *args, **kwargs: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.core.ocr_types",
        SimpleNamespace(
            extract_texts_from_ocr_results=lambda results: [],
            ocr_results_to_dicts=lambda results: [],
        ),
    )

    worker_globals = {"__name__": "__main__"}
    old_stdin = sys.stdin
    try:
        import io
        import contextlib

        sys.stdin = io.StringIO(json.dumps(payload) + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            exec(saber_loader._WORKER_SCRIPT, worker_globals)
    finally:
        sys.stdin = old_stdin

    assert [state.text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert [state.auto_text_direction for state in captured["states"]] == ["vertical", "horizontal"]
    assert getattr(captured["states"][0], "_layout_profile", None) == "vertical_layout2"


def test_run_saber_task_raises_runtime_error_on_subprocess_timeout(monkeypatch):
    captured = {}

    def fake_run(args, cwd, capture_output, env=None, text=True, encoding=None, errors=None, timeout=None, input=None):
        captured["timeout"] = timeout
        captured["input"] = input
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    monkeypatch.setattr(saber_loader.subprocess, "run", fake_run)
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: "D:/fake/python.exe")
    monkeypatch.setattr(saber_loader, "_resolve_subprocess_timeout_seconds", lambda operation: 3.5)

    with pytest.raises(RuntimeError, match="timed out"):
        saber_loader.run_saber_task("detect", {"image_path": "demo.jpg"})

    assert captured["timeout"] == 3.5
    assert json.loads(captured["input"]) == {"image_path": "demo.jpg"}


def test_run_saber_task_passes_payload_via_stdin_not_argv(monkeypatch):
    captured = {}
    oversized_payload = {
        "image_path": "demo.jpg",
        "raw_mask": "x" * 40000,
    }

    def fake_run(args, cwd, capture_output, env=None, text=True, encoding=None, errors=None, timeout=None, input=None):
        captured["args"] = args
        captured["input"] = input
        return SimpleNamespace(
            returncode=0,
            stdout='{"cleanImagePath": "page.clean.png"}',
            stderr="",
        )

    monkeypatch.setattr(saber_loader.subprocess, "run", fake_run)
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: "D:/fake/python.exe")

    result = saber_loader.run_saber_task("inpaint", oversized_payload)

    assert result == {"cleanImagePath": "page.clean.png"}
    assert captured["args"][0] == "D:/fake/python.exe"
    assert captured["args"][1] == "-c"
    assert "sys.stdin.read()" in captured["args"][2]
    assert saber_loader._SCRIPTS["inpaint"] in captured["args"][2]
    assert len(captured["args"]) == 3
    assert json.loads(captured["input"]) == oversized_payload


def test_resolve_timeout_seconds_prefers_operation_override(monkeypatch):
    monkeypatch.setattr(
        saber_loader,
        "resolve_runtime_config",
        lambda: {
            "saber_session_timeout_seconds": 45.0,
            "saber_subprocess_timeout_seconds": 45.0,
            "saber_operation_timeout_seconds": {
                "preprocess": 90.0,
            },
        },
    )

    assert saber_loader._resolve_session_timeout_seconds("preprocess") == 90.0
    assert saber_loader._resolve_subprocess_timeout_seconds("preprocess") == 90.0
    assert saber_loader._resolve_session_timeout_seconds("detect") == 45.0
    assert saber_loader._resolve_subprocess_timeout_seconds("render") == 45.0


def test_has_saber_48px_color_model_checks_required_files(tmp_path):
    saber_root = tmp_path / "Saber-Translator"
    model_dir = saber_root / "models" / "ocr_48px"
    model_dir.mkdir(parents=True)

    assert saber_loader.has_saber_48px_color_model(project_root=tmp_path) is False

    (model_dir / "ocr_ar_48px.ckpt").write_text("", encoding="utf-8")
    (model_dir / "alphabet-all-v7.txt").write_text("", encoding="utf-8")

    assert saber_loader.has_saber_48px_color_model(project_root=tmp_path) is True


def test_saber_worker_session_executes_json_rpc(monkeypatch):
    captured = {"writes": []}

    class FakeWriter:
        def write(self, data):
            captured["writes"].append(data)

        def flush(self):
            captured["flushed"] = True

        def close(self):
            captured["stdin_closed"] = True

    class FakeReader:
        def __init__(self, lines):
            self._lines = iter(lines)

        def readline(self):
            return next(self._lines, "")

        def close(self):
            captured["stdout_closed"] = True

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeWriter()
            self.stdout = FakeReader(
                [
                    "worker booting...\n",
                    '{"id": 1, "ok": true, "result": {"bubbleCoords": [[1, 2, 3, 4]]}}\n',
                ]
            )
            self.stderr = FakeReader([])

        def poll(self):
            return None

        def terminate(self):
            captured["terminated"] = True

        def wait(self, timeout=None):
            captured["wait_timeout"] = timeout
            return 0

        def kill(self):
            captured["killed"] = True

    def fake_popen(*args, **kwargs):
        captured["popen_kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(saber_loader.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(saber_loader, "_resolve_saber_python_path", lambda project_root=None: "D:/fake/python.exe")

    session = saber_loader.SaberWorkerSession()
    result = session.execute("detect", {"image_path": "demo.jpg"})
    session.close()

    request = json.loads(captured["writes"][0])
    assert request["operation"] == "detect"
    assert request["payload"] == {"image_path": "demo.jpg"}
    assert result == {"bubbleCoords": [[1, 2, 3, 4]]}
    assert captured["popen_kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["popen_kwargs"]["env"]["PYTHONUTF8"] == "1"
    assert captured["terminated"] is True


def test_run_saber_task_falls_back_to_subprocess_after_worker_timeout(monkeypatch):
    captured = {"execute_calls": 0}

    class FakeSession:
        def __init__(self):
            self.closed = False
            self.disabled_reason = None

        def execute(self, operation, payload):
            captured["execute_calls"] += 1
            time.sleep(0.05)
            return {"from": "worker"}

        def close(self):
            self.closed = True

        def disable(self, reason):
            self.disabled_reason = reason

        def is_disabled(self):
            return self.disabled_reason is not None

    monkeypatch.setattr(saber_loader, "_resolve_session_timeout_seconds", lambda operation: 0.01)
    monkeypatch.setattr(
        saber_loader,
        "_run_saber_subprocess_task",
        lambda operation, payload: {"from": "subprocess", "operation": operation, "payload": payload},
    )

    session = FakeSession()

    result = saber_loader.run_saber_task("preprocess", {"image_path": "demo.jpg"}, session=session)
    result_again = saber_loader.run_saber_task("preprocess", {"image_path": "demo-2.jpg"}, session=session)

    assert result == {
        "from": "subprocess",
        "operation": "preprocess",
        "payload": {"image_path": "demo.jpg"},
    }
    assert result_again == {
        "from": "subprocess",
        "operation": "preprocess",
        "payload": {"image_path": "demo-2.jpg"},
    }
    assert captured["execute_calls"] == 1
    assert session.closed is True
    assert "timed out" in session.disabled_reason


def test_saber_bridge_scripts_preserve_precise_mask_path():
    assert '"rawMask": None' not in saber_loader._SCRIPTS["detect"]
    assert '"rawMask": None' not in saber_loader._SCRIPTS["preprocess"]
    assert "raw_mask" in saber_loader._SCRIPTS["inpaint"]
    assert "precise_mask=" in saber_loader._SCRIPTS["inpaint"]
    assert '"rawMask": None' not in saber_loader._WORKER_SCRIPT
    assert "raw_mask" in saber_loader._WORKER_SCRIPT
    assert "precise_mask=" in saber_loader._WORKER_SCRIPT
