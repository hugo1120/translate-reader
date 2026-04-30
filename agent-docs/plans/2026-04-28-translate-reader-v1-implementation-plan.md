# Translate Reader V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `D:/github/translate-reader/translate-reader` 中构建一个本地 Web 日漫机翻阅读器首版，支持图片目录导入、单页 `检测 -> OCR -> 翻译 -> 擦字 -> 写字`、结果缓存和原图/译图阅读切换。

**Architecture:** 项目采用轻量 Flask 后端和原生静态前端。后端自己维护目录导入、缓存和 HTTP API，算法层使用项目内包装层调用 `Saber-Translator` 的核心检测/OCR/擦字/写字模块，先用最小耦合方式跑通闭环，再决定是否继续内嵌迁移源码。

**Tech Stack:** Python 3.11+, Flask, Flask-CORS, Pillow, NumPy, OpenAI-compatible HTTP client, pytest, 原生 HTML/CSS/JavaScript, `Saber-Translator` 本地源码桥接。

**Note:** 仓库约束要求“除非用户明确要求，否则不执行提交相关操作”，因此本计划不包含 git commit 步骤。

## 当前进度（2026-04-28）

- 已完成 Flask 壳、目录导入、页面详情、缓存骨架、翻译 API、检测/OCR API、整页流水线路由和基础阅读器页面。
- 已补齐 Saber 子进程桥接的真实运行约束：
  - 支持从混杂日志 stdout 中提取 JSON 结果
  - 优先使用 `TRANSLATE_READER_SABER_PYTHON` 或项目内 `.venv310`
- 已用真实样例页跑通 `检测 -> OCR`，本地 Web 前端也已接上“读取文字”按钮、框选叠加和 OCR 结果面板。
- 已完成真实 `擦字 -> 写字` 集成：
  - `src/core/inpaint/service.py` 通过 Saber 子进程产出 `clean` 图
  - `src/core/render/service.py` 通过 Saber 子进程调用 `re_render_with_states()` 产出译图
  - `src/core/pipeline/service.py` 已把产物固定落到 `data/cache/pages/<pageId>/`
- 当前默认擦字模式为 `solid`，与 Saber 默认配置一致；如果后续补齐 `models/lama/*` 和 `litelama`，可通过 `TRANSLATE_READER_INPAINT_METHOD` 切到 `lama_mpe` 或 `litelama`。
- 已完成误检过滤与重做按钮接线：
  - `src/core/pipeline/filtering.py` 会过滤极小噪点框和页边纯数字页码
  - `/api/pipeline/redo-inpaint`、`/api/pipeline/redo-render` 已接入前端按钮
- 已完成首轮 Saber 排版能力迁移：
  - `render` 桥接已开启 `auto_font_size`
  - 单页结果已缓存 `bubbleColors`
  - 若本机未安装 `models/ocr_48px/*`，颜色提取会直接降级为空结果
- 待继续收尾：译文排版质量优化、阅读器 UI 体验。

---

## 文件结构锁定

### 应创建的运行时文件

- `D:/github/translate-reader/translate-reader/requirements.txt`
  - 运行与测试依赖
- `D:/github/translate-reader/translate-reader/app.py`
  - 本地开发入口
- `D:/github/translate-reader/translate-reader/pytest.ini`
  - pytest 配置
- `D:/github/translate-reader/translate-reader/src/app/__init__.py`
  - Flask app factory、目录初始化、蓝图注册
- `D:/github/translate-reader/translate-reader/src/app/routes/health.py`
  - 健康检查
- `D:/github/translate-reader/translate-reader/src/app/routes/library.py`
  - 目录导入、页面列表、页面详情
- `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
  - 分步骤 API 和整页流水线 API
- `D:/github/translate-reader/translate-reader/src/app/static/index.html`
  - 阅读器页面
- `D:/github/translate-reader/translate-reader/src/app/static/app.css`
  - 阅读器样式
- `D:/github/translate-reader/translate-reader/src/app/static/app.js`
  - 前端交互逻辑

### 应创建的核心与存储文件

- `D:/github/translate-reader/translate-reader/src/core/models.py`
  - `PageRecord`、`BubbleRecord`、`OcrResultRecord`
- `D:/github/translate-reader/translate-reader/src/core/translate/openai_compatible.py`
  - 对接 `翻译api.txt` 的翻译适配器
- `D:/github/translate-reader/translate-reader/src/core/detection/service.py`
  - 检测包装层
- `D:/github/translate-reader/translate-reader/src/core/ocr/service.py`
  - OCR 包装层
- `D:/github/translate-reader/translate-reader/src/core/inpaint/service.py`
  - 擦字包装层
- `D:/github/translate-reader/translate-reader/src/core/render/service.py`
  - 写字包装层
- `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
  - 单页完整流水线编排
- `D:/github/translate-reader/translate-reader/src/integrations/saber_loader.py`
  - 注入 `Saber-Translator` 路径并做懒加载
- `D:/github/translate-reader/translate-reader/src/storage/library_store.py`
  - 当前导入目录、页面索引、资源复制
- `D:/github/translate-reader/translate-reader/src/storage/cache_store.py`
  - 单页 JSON 结果和译图缓存

### 应创建的测试文件

- `D:/github/translate-reader/translate-reader/tests/conftest.py`
- `D:/github/translate-reader/translate-reader/tests/test_app_boot.py`
- `D:/github/translate-reader/translate-reader/tests/test_library_api.py`
- `D:/github/translate-reader/translate-reader/tests/test_translate_api.py`
- `D:/github/translate-reader/translate-reader/tests/test_detect_ocr_api.py`
- `D:/github/translate-reader/translate-reader/tests/test_pipeline_run_page.py`
- `D:/github/translate-reader/translate-reader/tests/test_reader_shell.py`

## 实施任务

### Task 1: 搭建 Flask 壳、目录初始化与测试基线

**Files:**
- Create: `D:/github/translate-reader/translate-reader/requirements.txt`
- Create: `D:/github/translate-reader/translate-reader/app.py`
- Create: `D:/github/translate-reader/translate-reader/pytest.ini`
- Create: `D:/github/translate-reader/translate-reader/src/app/__init__.py`
- Create: `D:/github/translate-reader/translate-reader/src/app/routes/health.py`
- Create: `D:/github/translate-reader/translate-reader/tests/conftest.py`
- Create: `D:/github/translate-reader/translate-reader/tests/test_app_boot.py`

- [ ] **Step 1: 写启动与目录初始化的失败测试**

```python
from pathlib import Path


def test_health_route_and_data_dirs(client, app):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

    data_root = Path(app.config["DATA_ROOT"])
    assert (data_root / "library" / "current" / "pages").exists()
    assert (data_root / "cache" / "pages").exists()
    assert (data_root / "exports").exists()
```

- [ ] **Step 2: 运行测试，确认当前为空项目必然失败**

Run: `pytest "tests/test_app_boot.py" -q`

Expected: FAIL，报错 `ModuleNotFoundError: No module named 'app'` 或 `fixture 'client' not found`

- [ ] **Step 3: 写最小运行壳与健康检查**

`requirements.txt`

```text
flask
flask-cors
pillow
numpy
openai
pytest
requests
```

`src/app/__init__.py`

```python
from pathlib import Path
from flask import Flask
from flask_cors import CORS


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static", static_url_path="")
    CORS(app)

    project_root = Path(__file__).resolve().parents[2]
    data_root = project_root / "data"
    app.config.update(
        DATA_ROOT=str(data_root),
        LIBRARY_ROOT=str(data_root / "library" / "current"),
        CACHE_ROOT=str(data_root / "cache"),
        EXPORT_ROOT=str(data_root / "exports"),
    )
    if test_config:
        app.config.update(test_config)

    _ensure_data_dirs(app)

    from .routes.health import health_bp
    app.register_blueprint(health_bp)

    return app


def _ensure_data_dirs(app):
    data_root = Path(app.config["DATA_ROOT"])
    for path in (
        data_root / "library" / "current" / "pages",
        data_root / "cache" / "pages",
        data_root / "exports",
    ):
        path.mkdir(parents=True, exist_ok=True)
```

`src/app/routes/health.py`

```python
from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health():
    return jsonify({"ok": True})
```

`app.py`

```python
from src.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
```

`tests/conftest.py`

```python
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATA_ROOT": str(tmp_path / "data")})


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 4: 让 `DATA_ROOT` 可被测试覆盖**

把 `src/app/__init__.py` 中配置更新顺序固定为先写默认值，再应用 `test_config`，然后在 `_ensure_data_dirs()` 内从 `app.config` 重新读取路径。

```python
defaults = {
    "DATA_ROOT": str(data_root),
    "LIBRARY_ROOT": str(data_root / "library" / "current"),
    "CACHE_ROOT": str(data_root / "cache"),
    "EXPORT_ROOT": str(data_root / "exports"),
}
app.config.update(defaults)
if test_config:
    app.config.update(test_config)
```

- [ ] **Step 5: 运行测试，确认 Flask 壳与目录初始化通过**

Run: `pytest "tests/test_app_boot.py" -q`

Expected: PASS，输出 `1 passed`

### Task 2: 实现目录导入、页面列表、页面详情和本地缓存骨架

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/storage/library_store.py`
- Create: `D:/github/translate-reader/translate-reader/src/storage/cache_store.py`
- Create: `D:/github/translate-reader/translate-reader/src/core/models.py`
- Create: `D:/github/translate-reader/translate-reader/src/app/routes/library.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/__init__.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_library_api.py`

- [ ] **Step 1: 写目录导入与页面读取失败测试**

```python
from io import BytesIO
from PIL import Image


def _png_bytes(color):
    image = Image.new("RGB", (8, 8), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def test_import_list_and_page_detail(client):
    response = client.post(
        "/api/library/import",
        data={
            "files": [
                (_png_bytes("white"), "001.png"),
                (_png_bytes("black"), "002.png"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["imported"] == 2

    pages = client.get("/api/library/pages").get_json()["pages"]
    assert [page["fileName"] for page in pages] == ["001.png", "002.png"]

    detail = client.get(f"/api/library/page/{pages[0]['id']}").get_json()
    assert detail["page"]["fileName"] == "001.png"
    assert detail["page"]["sourceUrl"].startswith("/data/library/current/pages/")
    assert detail["page"]["translatedUrl"] is None
```

- [ ] **Step 2: 运行测试，确认缺少导入与列表接口**

Run: `pytest "tests/test_library_api.py" -q`

Expected: FAIL，报错 `404 NOT FOUND` 或蓝图未注册

- [ ] **Step 3: 定义页面与 OCR 结果基础数据模型**

`src/core/models.py`

```python
from dataclasses import asdict, dataclass, field


@dataclass
class OcrResultRecord:
    text: str = ""
    confidence: float | None = None
    confidenceSupported: bool = False
    engine: str = ""
    primaryEngine: str = ""
    fallbackUsed: bool = False


@dataclass
class BubbleRecord:
    coords: list[int]
    polygon: list[list[int]] = field(default_factory=list)
    direction: str = "vertical"
    textlines: list[dict] = field(default_factory=list)
    originalText: str = ""
    translatedText: str = ""
    ocrResult: dict = field(default_factory=dict)


@dataclass
class PageRecord:
    id: str
    fileName: str
    sourcePath: str
    translatedPath: str | None = None
    status: str = "idle"
    cacheKey: str | None = None

    def to_dict(self):
        return asdict(self)
```

- [ ] **Step 4: 实现目录导入、索引清单与缓存读写骨架**

`src/storage/library_store.py`

```python
import json
import shutil
import uuid
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class LibraryStore:
    def __init__(self, app):
        self.pages_root = Path(app.config["LIBRARY_ROOT"]) / "pages"
        self.manifest_path = Path(app.config["LIBRARY_ROOT"]) / "manifest.json"

    def import_files(self, files):
        shutil.rmtree(self.pages_root, ignore_errors=True)
        self.pages_root.mkdir(parents=True, exist_ok=True)
        pages = []
        for index, file_storage in enumerate(sorted(files, key=lambda item: item.filename)):
            suffix = Path(file_storage.filename).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue
            page_id = f"page-{index + 1:04d}"
            target = self.pages_root / f"{page_id}{suffix}"
            file_storage.save(target)
            pages.append(
                {
                    "id": page_id,
                    "fileName": file_storage.filename,
                    "sourcePath": str(target),
                    "translatedPath": None,
                    "status": "idle",
                    "cacheKey": str(uuid.uuid4()),
                }
            )
        self.manifest_path.write_text(json.dumps({"pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8")
        return pages

    def list_pages(self):
        if not self.manifest_path.exists():
            return []
        return json.loads(self.manifest_path.read_text(encoding="utf-8")).get("pages", [])
```

`src/storage/cache_store.py`

```python
import json
from pathlib import Path


class CacheStore:
    def __init__(self, app):
        self.pages_root = Path(app.config["CACHE_ROOT"]) / "pages"
        self.pages_root.mkdir(parents=True, exist_ok=True)

    def page_dir(self, page_id):
        path = self.pages_root / page_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_result(self, page_id):
        result_path = self.page_dir(page_id) / "result.json"
        if not result_path.exists():
            return None
        return json.loads(result_path.read_text(encoding="utf-8"))

    def save_result(self, page_id, payload):
        result_path = self.page_dir(page_id) / "result.json"
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 5: 实现导入、列表、详情路由并注册静态数据目录访问**

`src/app/routes/library.py`

```python
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request
from src.storage.cache_store import CacheStore
from src.storage.library_store import LibraryStore

library_bp = Blueprint("library", __name__)


@library_bp.post("/api/library/import")
def import_library():
    store = LibraryStore(current_app)
    pages = store.import_files(request.files.getlist("files"))
    return jsonify({"imported": len(pages), "pages": pages})


@library_bp.get("/api/library/pages")
def list_pages():
    store = LibraryStore(current_app)
    cache = CacheStore(current_app)
    pages = []
    for page in store.list_pages():
        pages.append(
            {
                "id": page["id"],
                "fileName": page["fileName"],
                "status": page["status"],
                "hasCache": cache.load_result(page["id"]) is not None,
            }
        )
    return jsonify({"pages": pages})


@library_bp.get("/api/library/page/<page_id>")
def get_page(page_id):
    store = LibraryStore(current_app)
    page = next(item for item in store.list_pages() if item["id"] == page_id)
    source_path = Path(page["sourcePath"])
    translated = page.get("translatedPath")
    return jsonify(
        {
            "page": {
                **page,
                "sourceUrl": f"/data/library/current/pages/{source_path.name}",
                "translatedUrl": translated,
            }
        }
    )
```

`src/app/__init__.py` 里补上：

```python
from .routes.library import library_bp
app.register_blueprint(library_bp)
app.add_url_rule("/data/<path:filename>", endpoint="data_files", view_func=_serve_data_file)
```

- [ ] **Step 6: 运行测试，确认目录导入和页面读取闭环通过**

Run: `pytest "tests/test_library_api.py" -q`

Expected: PASS，输出 `1 passed`

### Task 3: 实现翻译适配器与 `/api/pipeline/translate`

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/core/translate/openai_compatible.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/__init__.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_translate_api.py`

- [ ] **Step 1: 写翻译接口失败测试**

```python
def test_translate_route_uses_openai_compatible_client(client, monkeypatch):
    captured = {}

    class FakeTranslator:
        def translate_texts(self, texts, model, base_url):
            captured["texts"] = texts
            captured["model"] = model
            captured["base_url"] = base_url
            return ["你好"]

    monkeypatch.setattr("src.app.routes.pipeline.OpenAICompatibleTranslator", lambda: FakeTranslator())

    response = client.post(
        "/api/pipeline/translate",
        json={
            "texts": ["こんにちは"],
            "model": "mimo-v2.5-pro",
            "baseUrl": "https://your-openai-compatible-base-url/v1",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["translatedTexts"] == ["你好"]
    assert captured["texts"] == ["こんにちは"]
```

- [ ] **Step 2: 运行测试，确认缺少翻译路由**

Run: `pytest "tests/test_translate_api.py" -q`

Expected: FAIL，报错 `404 NOT FOUND`

- [ ] **Step 3: 写最小 OpenAI-compatible 适配器**

`src/core/translate/openai_compatible.py`

```python
from openai import OpenAI


class OpenAICompatibleTranslator:
    def translate_texts(self, texts, model, base_url, api_key="dummy"):
        client = OpenAI(api_key=api_key, base_url=base_url)
        results = []
        for text in texts:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "请将输入翻译成简体中文，只返回译文。"},
                    {"role": "user", "content": text},
                ],
                stream=False,
            )
            results.append(completion.choices[0].message.content.strip())
        return results
```

- [ ] **Step 4: 实现 `/api/pipeline/translate` 路由**

`src/app/routes/pipeline.py`

```python
from flask import Blueprint, jsonify, request
from src.core.translate.openai_compatible import OpenAICompatibleTranslator

pipeline_bp = Blueprint("pipeline", __name__)


@pipeline_bp.post("/api/pipeline/translate")
def translate_texts():
    data = request.get_json() or {}
    texts = data.get("texts", [])
    model = data.get("model", "mimo-v2.5-pro")
    base_url = data.get("baseUrl", "https://your-openai-compatible-base-url/v1")
    translator = OpenAICompatibleTranslator()
    translated = translator.translate_texts(texts=texts, model=model, base_url=base_url)
    return jsonify({"translatedTexts": translated})
```

同时在 `src/app/__init__.py` 注册蓝图：

```python
from .routes.pipeline import pipeline_bp
app.register_blueprint(pipeline_bp)
```

- [ ] **Step 5: 运行翻译接口测试**

Run: `pytest "tests/test_translate_api.py" -q`

Expected: PASS，输出 `1 passed`

### Task 4: 接入 Saber 检测/OCR 包装层和对应步骤 API

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/integrations/saber_loader.py`
- Create: `D:/github/translate-reader/translate-reader/src/core/detection/service.py`
- Create: `D:/github/translate-reader/translate-reader/src/core/ocr/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_detect_ocr_api.py`

- [ ] **Step 1: 写检测与 OCR 包装路由失败测试**

```python
def test_detect_route_returns_bubbles(client, monkeypatch):
    monkeypatch.setattr(
        "src.app.routes.pipeline.detect_page",
        lambda image_path: {
            "bubbleCoords": [[10, 20, 60, 90]],
            "bubblePolygons": [[[10, 20], [60, 20], [60, 90], [10, 90]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
        },
    )
    response = client.post("/api/pipeline/detect", json={"pageId": "page-0001"})
    assert response.status_code == 200
    assert response.get_json()["bubbleCoords"][0] == [10, 20, 60, 90]


def test_ocr_route_returns_texts(client, monkeypatch):
    monkeypatch.setattr(
        "src.app.routes.pipeline.ocr_page",
        lambda image_path, bubble_coords: {
            "originalTexts": ["さあ…"],
            "ocrResults": [{"text": "さあ…", "engine": "manga_ocr"}],
        },
    )
    response = client.post(
        "/api/pipeline/ocr",
        json={"pageId": "page-0001", "bubbleCoords": [[10, 20, 60, 90]]},
    )
    assert response.status_code == 200
    assert response.get_json()["originalTexts"] == ["さあ…"]
```

- [ ] **Step 2: 运行测试，确认缺少检测/OCR 包装路由**

Run: `pytest "tests/test_detect_ocr_api.py" -q`

Expected: FAIL，报错 `AttributeError` 或 `404 NOT FOUND`

- [ ] **Step 3: 写 Saber 懒加载器**

`src/integrations/saber_loader.py`

```python
import sys
from pathlib import Path


def load_saber_module(module_name):
    root = Path(__file__).resolve().parents[3]
    saber_root = root.parent / "Saber-Translator"
    src_path = saber_root / "src"
    if str(saber_root) not in sys.path:
        sys.path.insert(0, str(saber_root))
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    return __import__(module_name, fromlist=["*"])
```

- [ ] **Step 4: 写检测与 OCR 包装层**

`src/core/detection/service.py`

```python
from pathlib import Path
from PIL import Image
from src.integrations.saber_loader import load_saber_module


def detect_page(image_path):
    detection = load_saber_module("src.core.detection")
    image = Image.open(Path(image_path)).convert("RGB")
    result = detection.get_bubble_detection_result_with_auto_directions(image)
    return {
        "bubbleCoords": result.get("coords", []),
        "bubblePolygons": result.get("polygons", []),
        "autoDirections": result.get("auto_directions", []),
        "textlinesPerBubble": result.get("textlines_per_bubble", []),
        "rawMask": result.get("raw_mask"),
    }
```

`src/core/ocr/service.py`

```python
from pathlib import Path
from PIL import Image
from src.integrations.saber_loader import load_saber_module


def ocr_page(image_path, bubble_coords):
    ocr_module = load_saber_module("src.core.ocr")
    ocr_types = load_saber_module("src.core.ocr_types")
    image = Image.open(Path(image_path)).convert("RGB")
    results = ocr_module.recognize_ocr_results_in_bubbles(
        image,
        bubble_coords,
        source_language="japanese",
        ocr_engine="manga_ocr",
    )
    return {
        "originalTexts": ocr_types.extract_texts_from_ocr_results(results),
        "ocrResults": ocr_types.ocr_results_to_dicts(results),
    }
```

- [ ] **Step 5: 实现检测和 OCR 路由**

在 `src/app/routes/pipeline.py` 中加入：

```python
from src.core.detection.service import detect_page
from src.core.ocr.service import ocr_page
from src.storage.library_store import LibraryStore


def _resolve_page_path(page_id):
    page = next(item for item in LibraryStore(current_app).list_pages() if item["id"] == page_id)
    return page["sourcePath"]


@pipeline_bp.post("/api/pipeline/detect")
def detect_route():
    page_id = (request.get_json() or {})["pageId"]
    result = detect_page(_resolve_page_path(page_id))
    return jsonify(result)


@pipeline_bp.post("/api/pipeline/ocr")
def ocr_route():
    data = request.get_json() or {}
    result = ocr_page(_resolve_page_path(data["pageId"]), data.get("bubbleCoords", []))
    return jsonify(result)
```

- [ ] **Step 6: 运行检测/OCR 包装测试**

Run: `pytest "tests/test_detect_ocr_api.py" -q`

Expected: PASS，输出 `2 passed`

### Task 5: 接入 Saber 擦字/写字包装层，并实现整页流水线与缓存保存

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/core/inpaint/service.py`
- Create: `D:/github/translate-reader/translate-reader/src/core/render/service.py`
- Create: `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
- Modify: `D:/github/translate-reader/translate-reader/src/storage/library_store.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_pipeline_run_page.py`

- [ ] **Step 1: 写整页流水线失败测试**

```python
def test_run_page_pipeline_persists_result(client, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.service.detect_page", lambda path: {
        "bubbleCoords": [[10, 20, 60, 90]],
        "bubblePolygons": [],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "rawMask": None,
    })
    monkeypatch.setattr("src.core.pipeline.service.ocr_page", lambda path, bubble_coords: {
        "originalTexts": ["白い夜"],
        "ocrResults": [{"text": "白い夜", "engine": "manga_ocr"}],
    })
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", lambda texts, model, base_url: ["白色的夜晚"])
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda path, bubble_coords, raw_mask=None: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda clean_image_path, page_id, bubbles: {"translatedImagePath": "translated.png"})

    response = client.post("/api/pipeline/run-page", json={"pageId": "page-0001"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["translatedTexts"] == ["白色的夜晚"]
    assert data["translatedImagePath"] == "translated.png"
```

- [ ] **Step 2: 运行测试，确认缺少整页流水线**

Run: `pytest "tests/test_pipeline_run_page.py" -q`

Expected: FAIL，报错 `404 NOT FOUND`

- [ ] **Step 3: 写擦字和写字包装层**

`src/core/inpaint/service.py`

```python
from pathlib import Path
from PIL import Image
from src.integrations.saber_loader import load_saber_module


def inpaint_page(image_path, bubble_coords, raw_mask=None):
    module = load_saber_module("src.core.inpainting")
    image = Image.open(Path(image_path)).convert("RGB")
    cleaned, _ = module.inpaint_bubbles(image, bubble_coords, precise_mask=raw_mask)
    output_path = Path(image_path).with_name(f"{Path(image_path).stem}.clean.png")
    cleaned.save(output_path)
    return {"cleanImagePath": str(output_path)}
```

`src/core/render/service.py`

```python
from pathlib import Path
from PIL import Image
from src.integrations.saber_loader import load_saber_module


def render_page(clean_image_path, page_id, bubbles):
    module = load_saber_module("src.core.rendering")
    image = Image.open(Path(clean_image_path)).convert("RGB")
    bubble_texts = [bubble["translatedText"] for bubble in bubbles]
    bubble_coords = [bubble["coords"] for bubble in bubbles]
    rendered = module.re_render_text_in_bubbles(
        image,
        bubble_texts,
        bubble_coords,
        font_family=None,
        font_size=28,
        text_direction="vertical",
    )
    output_path = Path(clean_image_path).with_name(f"{page_id}.translated.png")
    rendered.save(output_path)
    return {"translatedImagePath": str(output_path)}
```

- [ ] **Step 4: 写完整编排服务并保存缓存**

`src/core/pipeline/service.py`

```python
from src.core.detection.service import detect_page
from src.core.ocr.service import ocr_page
from src.core.inpaint.service import inpaint_page
from src.core.render.service import render_page
from src.core.translate.openai_compatible import OpenAICompatibleTranslator
from src.storage.cache_store import CacheStore


def run_page_pipeline(app, page_id, source_path, model="mimo-v2.5-pro", base_url="https://your-openai-compatible-base-url/v1"):
    detection = detect_page(source_path)
    ocr = ocr_page(source_path, detection["bubbleCoords"])
    translated_texts = OpenAICompatibleTranslator().translate_texts(
        texts=ocr["originalTexts"],
        model=model,
        base_url=base_url,
    )
    bubbles = []
    for index, coords in enumerate(detection["bubbleCoords"]):
        bubbles.append(
            {
                "coords": coords,
                "polygon": detection["bubblePolygons"][index] if index < len(detection["bubblePolygons"]) else [],
                "direction": detection["autoDirections"][index] if index < len(detection["autoDirections"]) else "vertical",
                "textlines": detection["textlinesPerBubble"][index] if index < len(detection["textlinesPerBubble"]) else [],
                "originalText": ocr["originalTexts"][index],
                "translatedText": translated_texts[index],
                "ocrResult": ocr["ocrResults"][index],
            }
        )
    clean = inpaint_page(source_path, detection["bubbleCoords"], detection.get("rawMask"))
    rendered = render_page(clean["cleanImagePath"], page_id, bubbles)
    payload = {
        "pageId": page_id,
        "bubbleCoords": detection["bubbleCoords"],
        "bubblePolygons": detection["bubblePolygons"],
        "autoDirections": detection["autoDirections"],
        "textlinesPerBubble": detection["textlinesPerBubble"],
        "originalTexts": ocr["originalTexts"],
        "ocrResults": ocr["ocrResults"],
        "translatedTexts": translated_texts,
        "translatedImagePath": rendered["translatedImagePath"],
        "cleanImagePath": clean["cleanImagePath"],
        "bubbles": bubbles,
    }
    CacheStore(app).save_result(page_id, payload)
    return payload
```

- [ ] **Step 5: 暴露 `run-page` 与缓存读取接口**

在 `src/app/routes/pipeline.py` 中加入：

```python
from flask import current_app
from src.core.pipeline.service import run_page_pipeline
from src.storage.cache_store import CacheStore


@pipeline_bp.post("/api/pipeline/run-page")
def run_page():
    data = request.get_json() or {}
    page_id = data["pageId"]
    source_path = _resolve_page_path(page_id)
    payload = run_page_pipeline(
        app=current_app,
        page_id=page_id,
        source_path=source_path,
        model=data.get("model", "mimo-v2.5-pro"),
        base_url=data.get("baseUrl", "https://your-openai-compatible-base-url/v1"),
    )
    return jsonify(payload)


@pipeline_bp.get("/api/page/<page_id>/result")
def get_page_result(page_id):
    payload = CacheStore(current_app).load_result(page_id)
    return jsonify({"result": payload})
```

- [ ] **Step 6: 在页面清单中映射缓存译图路径**

在 `src/storage/library_store.py` 中加入一个更新方法：

```python
def update_translated_path(self, page_id, translated_path):
    manifest = {"pages": self.list_pages()}
    for page in manifest["pages"]:
        if page["id"] == page_id:
            page["translatedPath"] = translated_path
            page["status"] = "translated"
    self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
```

并在 `run_page_pipeline()` 返回后由路由调用：

```python
LibraryStore(current_app).update_translated_path(page_id, payload["translatedImagePath"])
```

- [ ] **Step 7: 运行整页流水线测试**

Run: `pytest "tests/test_pipeline_run_page.py" -q`

Expected: PASS，输出 `1 passed`

### Task 6: 构建阅读器前端壳与调试图层

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/app/static/index.html`
- Create: `D:/github/translate-reader/translate-reader/src/app/static/app.css`
- Create: `D:/github/translate-reader/translate-reader/src/app/static/app.js`
- Modify: `D:/github/translate-reader/translate-reader/src/app/__init__.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_reader_shell.py`

- [ ] **Step 1: 写前端壳失败测试**

```python
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
```

- [ ] **Step 2: 运行测试，确认主页未提供阅读器壳**

Run: `pytest "tests/test_reader_shell.py" -q`

Expected: FAIL，报错 `404 NOT FOUND`

- [ ] **Step 3: 写最小阅读器结构**

`src/app/static/index.html`

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>translate-reader</title>
    <link rel="stylesheet" href="/app.css" />
  </head>
  <body>
    <header class="topbar">
      <label class="importer">
        <input id="folderInput" type="file" webkitdirectory multiple hidden />
        <span>导入目录</span>
      </label>
      <button id="readTextBtn">读取文字</button>
      <button id="runPageBtn">整页翻译</button>
      <button id="redoInpaintBtn">重做擦字</button>
      <button id="redoRenderBtn">重做写字</button>
      <button id="showSourceBtn">原图</button>
      <button id="showTranslatedBtn">译图</button>
    </header>
    <main class="layout">
      <aside id="pageList" class="sidebar"></aside>
      <section class="viewer">
        <img id="pageImage" alt="当前页" />
        <canvas id="overlay"></canvas>
      </section>
      <aside class="inspector">
        <pre id="debugPanel"></pre>
      </aside>
    </main>
    <script src="/app.js"></script>
  </body>
</html>
```

- [ ] **Step 4: 写静态样式与前端交互**

`src/app/static/app.css`

```css
:root {
  --bg: #f0eee8;
  --panel: #fbfaf6;
  --line: #d7d2c7;
  --text: #16130f;
  --accent: #a33a2b;
}

body {
  margin: 0;
  background: radial-gradient(circle at top, #fffaf1 0%, var(--bg) 70%);
  color: var(--text);
  font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif;
}
```

`src/app/static/app.js`

```javascript
const state = { pages: [], currentPageId: null, currentResult: null, view: "source" };

async function refreshPages() {
  const response = await fetch("/api/library/pages");
  const data = await response.json();
  state.pages = data.pages;
  renderPageList();
}

async function importFolder(files) {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  await fetch("/api/library/import", { method: "POST", body: form });
  await refreshPages();
}
```

- [ ] **Step 5: 将首页指向静态阅读器壳**

在 `src/app/__init__.py` 中加入：

```python
from flask import send_from_directory


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")
```

- [ ] **Step 6: 运行前端壳测试**

Run: `pytest "tests/test_reader_shell.py" -q`

Expected: PASS，输出 `1 passed`

### Task 7: 做一次以样例页为中心的端到端烟测收尾

**Files:**
- Modify: `D:/github/translate-reader/agent-docs/index.md`
- Test: `D:/github/translate-reader/translate-reader/tests/test_pipeline_run_page.py`

- [ ] **Step 1: 扩展整页流水线测试，校验缓存接口可回读**

```python
def test_page_result_endpoint_returns_cached_payload(client, monkeypatch):
    monkeypatch.setattr("src.core.pipeline.service.detect_page", lambda path: {
        "bubbleCoords": [],
        "bubblePolygons": [],
        "autoDirections": [],
        "textlinesPerBubble": [],
        "rawMask": None,
    })
    monkeypatch.setattr("src.core.pipeline.service.ocr_page", lambda path, bubble_coords: {
        "originalTexts": [],
        "ocrResults": [],
    })
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", lambda texts, model, base_url: [])
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda path, bubble_coords, raw_mask=None: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda clean_image_path, page_id, bubbles: {"translatedImagePath": "translated.png"})

    client.post("/api/pipeline/run-page", json={"pageId": "page-0001"})
    result = client.get("/api/page/page-0001/result").get_json()["result"]
    assert result["translatedImagePath"] == "translated.png"
```

- [ ] **Step 2: 运行当前全量测试集**

Run: `pytest "tests" -q`

Expected: PASS，输出形如 `7 passed`

- [ ] **Step 3: 用真实样例页做手工烟测**

Run:

```powershell
python "app.py"
```

Expected:

- 控制台出现 Flask 本地服务地址 `http://127.0.0.1:5000`
- 浏览器可打开阅读器壳
- 通过“导入目录”选中 `D:/github/translate-reader/翻译测试日漫`
- `读取文字` 至少返回可见 OCR 结果
- `整页翻译` 后生成译图与缓存文件

- [ ] **Step 4: 记录运行注意事项到索引文档**

在 [agent-docs/index.md](/D:/github/translate-reader/agent-docs/index.md:1) 追加一条运行记忆：

```md
- `translate-reader` 首版通过浏览器目录导入（`webkitdirectory`）把本地图片复制到 `data/library/current/pages`，不是直接读取用户任意磁盘路径。
```

## 自检

### Spec coverage

- 本地 Web 工具：Task 1、Task 6
- 本地图片目录导入与阅读：Task 2、Task 6
- 分步骤 API：Task 3、Task 4、Task 5
- 单页完整流水线：Task 5
- 缓存读取与复用：Task 2、Task 5、Task 7
- 调试图层与原图/译图切换：Task 6
- 典型日漫页烟测：Task 7

### Placeholder scan

- 未使用 `TBD` / `TODO`
- 未引用“类似前一任务”之类省略表述
- 每个代码步骤都给了具体文件和示例代码

### Type consistency

- 页面主键统一为 `pageId`
- 检测输出统一为 `bubbleCoords / bubblePolygons / autoDirections / textlinesPerBubble`
- OCR 输出统一为 `originalTexts / ocrResults`
- 翻译输出统一为 `translatedTexts`
