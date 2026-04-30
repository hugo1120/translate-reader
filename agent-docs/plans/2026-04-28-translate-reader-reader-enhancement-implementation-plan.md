# Translate Reader Reader Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 `translate-reader` 从“能跑通整页翻译的原型”推进成“阅读器优先、支持单框人工微调、具备章节上下文一致性和耗时可视化”的可用产品。

**Architecture:** 保持现有 `Flask + 原生前端 + Saber 子进程桥接` 架构，不引入重型前端框架。新增三块能力：页面级编辑状态与耗时记录、单气泡编辑与重渲染服务、章节上下文一致性服务；前端围绕当前 `app.js` 扩展阅读器工作区，而不是迁整套 Saber 工作台。

**Tech Stack:** Python 3.11+, Flask, Pillow, pytest, 原生 HTML/CSS/JavaScript, `Saber-Translator` 子进程桥接, OpenAI-compatible HTTP API。

**Note:** 仓库约束要求“除非用户明确要求，否则不执行提交相关操作”，因此本计划不包含 git commit 步骤。

---

## 范围与阶段门禁

本规格覆盖 4 个阶段，但执行必须按门禁推进：

- `A1` 阅读器工作区与耗时可视化
- `A2` 单框人工微调闭环
- `B1` 章节上下文一致性
- `C1` 基于真实耗时数据的性能优化

要求：

- `A1` 完成并通过真实章节 smoke 后，才能进入 `A2`
- `A2` 完成后，才能把人工修正结果反哺到 `B1`
- `C1` 不允许在 `A2` 未稳定前抢跑

---

## 文件结构锁定

### 新增文件

- `D:/github/translate-reader/translate-reader/src/core/editing/service.py`
  - 页面级气泡状态编辑、单框更新、单框重渲染编排
- `D:/github/translate-reader/translate-reader/src/core/context/service.py`
  - 章节上下文快照、术语表、已确认译文摘要
- `D:/github/translate-reader/translate-reader/tests/test_editing_service.py`
  - 单框编辑、重渲染、保存页级编辑测试
- `D:/github/translate-reader/translate-reader/tests/test_context_service.py`
  - 章节上下文聚合与术语锁定测试

### 重点修改文件

- `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
- `D:/github/translate-reader/translate-reader/src/core/render/service.py`
- `D:/github/translate-reader/translate-reader/src/core/translate/openai_compatible.py`
- `D:/github/translate-reader/translate-reader/src/integrations/saber_loader.py`
- `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
- `D:/github/translate-reader/translate-reader/src/app/static/index.html`
- `D:/github/translate-reader/translate-reader/src/app/static/app.js`
- `D:/github/translate-reader/translate-reader/src/app/static/app.css`
- `D:/github/translate-reader/translate-reader/src/storage/cache_store.py`
- `D:/github/translate-reader/translate-reader/src/core/models.py`

---

## Task 1: A1 结果结构与耗时记录基础

**Files:**
- Modify: `D:/github/translate-reader/translate-reader/src/core/models.py`
- Modify: `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/storage/cache_store.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_pipeline_service.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_pipeline_run_page.py`

- [x] **Step 1: 先写失败测试，要求整页结果带 `bubbleStates / timings / manualEdited`**

```python
def test_run_page_pipeline_returns_timings_and_bubble_states(app, tmp_path, monkeypatch):
    source_path = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(source_path)

    monkeypatch.setattr("src.core.pipeline.service.detect_page", lambda _: {
        "bubbleCoords": [[10, 20, 40, 60]],
        "bubblePolygons": [[[10, 20], [40, 20], [40, 60], [10, 60]]],
        "autoDirections": ["vertical"],
        "textlinesPerBubble": [[]],
        "rawMask": None,
    })
    monkeypatch.setattr("src.core.pipeline.service.ocr_page", lambda *_: {
        "originalTexts": ["さあ"],
        "ocrResults": [{"text": "さあ", "engine": "manga_ocr"}],
    })
    monkeypatch.setattr("src.core.pipeline.service.translate_texts", lambda *args, **kwargs: ["来吧"])
    monkeypatch.setattr("src.core.pipeline.service.extract_bubble_colors", lambda *args, **kwargs: {"colors": []})
    monkeypatch.setattr("src.core.pipeline.service.inpaint_page", lambda *args, **kwargs: {"cleanImagePath": "clean.png"})
    monkeypatch.setattr("src.core.pipeline.service.render_page", lambda *args, **kwargs: {"translatedImagePath": "translated.png"})

    result = run_page_pipeline(app, "page-0001", str(source_path))

    assert result["manualEdited"] is False
    assert "bubbleStates" in result
    assert result["bubbleStates"][0]["translatedText"] == "来吧"
    assert set(result["timings"]) == {"detect", "ocr", "translate", "color", "inpaint", "render", "total"}
```

- [x] **Step 2: 运行定向测试，确认当前结果结构不满足要求**

Run: `pytest "tests/test_pipeline_service.py::test_run_page_pipeline_returns_timings_and_bubble_states" -q`

Expected: FAIL，缺少 `bubbleStates`、`timings` 或 `manualEdited`

- [x] **Step 3: 扩展结果结构并记录阶段耗时**

在 `src/core/pipeline/service.py` 中引入 `perf_counter()`，记录每个阶段耗时，结果结构统一追加：

```python
payload = {
    ...,
    "bubbleStates": bubble_states,
    "manualEdited": False,
    "timings": {
        "detect": detect_seconds,
        "ocr": ocr_seconds,
        "translate": translate_seconds,
        "color": color_seconds,
        "inpaint": inpaint_seconds,
        "render": render_seconds,
        "total": total_seconds,
    },
}
```

在 `src/core/models.py` 中把 `BubbleRecord` 扩展为兼容阅读器编辑状态：

```python
@dataclass
class BubbleRecord:
    coords: list[int]
    polygon: list[list[int]] = field(default_factory=list)
    direction: str = "vertical"
    textDirection: str = "vertical"
    autoTextDirection: str = "vertical"
    textlines: list[dict] = field(default_factory=list)
    originalText: str = ""
    translatedText: str = ""
    ocrResult: dict = field(default_factory=dict)
    textColor: str | None = None
    fillColor: str | None = None
    fontSize: int | None = None
    lineSpacing: float | None = None
    textAlign: str | None = None
    strokeEnabled: bool | None = None
    strokeColor: str | None = None
    strokeWidth: int | None = None
    position: dict = field(default_factory=dict)
    autoFgColor: list[int] | None = None
    autoBgColor: list[int] | None = None
    colorConfidence: float = 0.0
```

- [x] **Step 4: 让缓存层原样保存增强后的结果**

`src/storage/cache_store.py` 保持 JSON 透传，不增加二次裁剪逻辑；新增一个帮助方法读取不存在字段时返回默认值：

```python
def load_result_or_default(self, page_id, default=None):
    payload = self.load_result(page_id)
    if payload is None:
        return default
    return payload
```

- [x] **Step 5: 回跑相关测试**

Run: `pytest "tests/test_pipeline_service.py" "tests/test_pipeline_run_page.py" -q`

Expected: PASS，且已有整页缓存读取测试不回归

---

## Task 2: A1 阅读器工作区与耗时展示

**Files:**
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/index.html`
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/app.js`
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/app.css`
- Test: `D:/github/translate-reader/translate-reader/tests/test_reader_shell.py`

- [x] **Step 1: 写前端失败测试，要求出现“当前框编辑区”和“阶段耗时区”**

```python
def test_reader_shell_contains_editor_and_timing_panels(client):
    html = client.get("/").data.decode("utf-8")
    assert 'id="bubbleEditorPanel"' in html
    assert 'id="timingPanel"' in html
    assert "当前气泡" in html
    assert "阶段耗时" in html
```

- [x] **Step 2: 运行测试，确认当前壳层缺少这两块面板**

Run: `pytest "tests/test_reader_shell.py::test_reader_shell_contains_editor_and_timing_panels" -q`

Expected: FAIL，缺少面板节点

- [x] **Step 3: 扩展阅读器壳**

在 `src/app/static/index.html` 右侧面板内增加：

```html
<div class="panel-title">当前气泡</div>
<section id="bubbleEditorPanel" class="bubble-editor-panel"></section>
<div class="panel-title">阶段耗时</div>
<section id="timingPanel" class="timing-panel"></section>
```

在 `src/app/static/app.js` 中新增两个渲染函数：

```javascript
function renderTimingPanel() {
  const timings = state.currentResult?.timings || null;
  if (!elements.timingPanel) return;
  if (!timings) {
    elements.timingPanel.innerHTML = '<p class="ocr-empty">当前页还没有耗时数据。</p>';
    return;
  }
  elements.timingPanel.innerHTML = Object.entries(timings)
    .map(([key, value]) => `<div class="timing-item"><span>${escapeHtml(key)}</span><strong>${Number(value).toFixed(2)}s</strong></div>`)
    .join("");
}
```

- [x] **Step 4: 初始实现当前气泡占位面板**

仍在 `app.js` 中加入：

```javascript
state.selectedBubbleIndex = null;

function renderBubbleEditorPanel() {
  if (!elements.bubbleEditorPanel) return;
  if (state.selectedBubbleIndex == null || !state.currentResult?.bubbles?.[state.selectedBubbleIndex]) {
    elements.bubbleEditorPanel.innerHTML = '<p class="ocr-empty">点击画面中的框后，这里会显示当前气泡信息。</p>';
    return;
  }
  const bubble = state.currentResult.bubbles[state.selectedBubbleIndex];
  elements.bubbleEditorPanel.innerHTML = `
    <div class="bubble-field"><label>原文</label><pre>${escapeHtml(bubble.originalText || "")}</pre></div>
    <div class="bubble-field"><label>译文</label><pre>${escapeHtml(bubble.translatedText || "")}</pre></div>
  `;
}
```

- [x] **Step 5: 让点击框可以选中当前气泡**

先在画布点击事件里做最小命中检测：

```javascript
elements.overlay?.addEventListener("click", (event) => {
  const hitIndex = hitTestBubble(event.offsetX, event.offsetY);
  state.selectedBubbleIndex = hitIndex;
  renderBubbleEditorPanel();
  drawOverlay();
});
```

- [x] **Step 6: 回跑前端壳测试**

Run: `pytest "tests/test_reader_shell.py" -q`

Expected: PASS

---

## Task 3: A2 单框编辑后端与 Saber 单框重渲染桥接

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/core/editing/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/integrations/saber_loader.py`
- Modify: `D:/github/translate-reader/translate-reader/src/core/render/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/routes/pipeline.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_editing_service.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_saber_loader.py`

- [x] **Step 1: 写失败测试，要求可以只重渲染一个气泡**

```python
def test_rerender_single_bubble_updates_only_target_index(monkeypatch):
    captured = {}

    def fake_run_saber_task(operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return {"translatedImagePath": "page.translated.png", "bubbleStates": payload["bubble_states"]}

    monkeypatch.setattr("src.core.editing.service.run_saber_task", fake_run_saber_task)

    result = rerender_single_bubble(
        clean_image_path="clean.png",
        translated_image_path="page.translated.png",
        bubble_states=[{"translatedText": "A"}, {"translatedText": "B2"}],
        bubble_index=1,
    )

    assert captured["operation"] == "render_single"
    assert captured["payload"]["bubble_index"] == 1
    assert result["bubbleStates"][1]["translatedText"] == "B2"
```

- [x] **Step 2: 运行测试，确认当前没有单框重渲染服务**

Run: `pytest "tests/test_editing_service.py::test_rerender_single_bubble_updates_only_target_index" -q`

Expected: FAIL，模块或方法不存在

- [x] **Step 3: 新增 `render_single` Saber 子进程操作**

在 `src/integrations/saber_loader.py` 里新增一个脚本分支，思路与 `render` 类似，但只调用 Saber 的单框接口：

```python
"render_single": textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path
    from PIL import Image
    from src.core.config_models import BubbleState
    from src.core.rendering import render_single_bubble_unified

    payload = json.loads(sys.argv[1])
    image = Image.open(payload["clean_image_path"]).convert("RGB")
    bubble_states = [BubbleState.from_dict(item) for item in payload.get("bubble_states", [])]
    rendered = render_single_bubble_unified(image, bubble_states, payload["bubble_index"])
    output_path = Path(payload["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(output_path)
    print(json.dumps({
        "translatedImagePath": str(output_path),
        "bubbleStates": [state.to_dict() for state in bubble_states],
    }, ensure_ascii=False))
    """
)
```

- [x] **Step 4: 实现编辑服务**

`src/core/editing/service.py`

```python
from copy import deepcopy

from src.integrations.saber_loader import run_saber_task


def update_bubble_state(result_payload, bubble_index, patch):
    updated = deepcopy(result_payload)
    bubble_states = updated.get("bubbleStates") or updated.get("bubbles") or []
    bubble_states[bubble_index] = {**bubble_states[bubble_index], **patch}
    updated["bubbleStates"] = bubble_states
    updated["manualEdited"] = True
    return updated


def rerender_single_bubble(clean_image_path, translated_image_path, bubble_states, bubble_index):
    return run_saber_task(
        "render_single",
        {
            "clean_image_path": clean_image_path,
            "output_path": translated_image_path,
            "bubble_states": bubble_states,
            "bubble_index": bubble_index,
        },
    )
```

- [x] **Step 5: 暴露后端接口**

在 `src/app/routes/pipeline.py` 增加：

```python
@pipeline_bp.post("/api/pipeline/update-bubble")
def update_bubble():
    data = request.get_json() or {}
    page_id = data["pageId"]
    bubble_index = data["bubbleIndex"]
    patch = data.get("patch", {})
    result = CacheStore(current_app).load_result(page_id)
    updated = update_bubble_state(result, bubble_index, patch)
    CacheStore(current_app).save_result(page_id, updated)
    return jsonify(updated)


@pipeline_bp.post("/api/pipeline/rerender-bubble")
def rerender_bubble():
    data = request.get_json() or {}
    page_id = data["pageId"]
    bubble_index = data["bubbleIndex"]
    result = CacheStore(current_app).load_result(page_id)
    rendered = rerender_single_bubble(
        result["cleanImagePath"],
        result["translatedImagePath"],
        result["bubbleStates"],
        bubble_index,
    )
    result["translatedImagePath"] = rendered["translatedImagePath"]
    result["bubbleStates"] = rendered["bubbleStates"]
    result["bubbles"] = rendered["bubbleStates"]
    result["manualEdited"] = True
    CacheStore(current_app).save_result(page_id, result)
    return jsonify(result)
```

- [x] **Step 6: 运行新增后端测试**

Run: `pytest "tests/test_editing_service.py" "tests/test_saber_loader.py" -q`

Expected: PASS

---

## Task 4: A2 前端单框编辑、拖拽缩放与保存

**Files:**
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/app.js`
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/app.css`
- Test: `D:/github/translate-reader/translate-reader/tests/test_reader_shell.py`

- [x] **Step 1: 写前端失败测试，要求存在单框编辑调用**

```python
def test_reader_bundle_wires_bubble_edit_actions():
    source = (Path(__file__).resolve().parents[1] / "src" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/pipeline/update-bubble" in source
    assert "/api/pipeline/rerender-bubble" in source
    assert "selectedBubbleIndex" in source
```

- [x] **Step 2: 运行测试，确认当前前端没有单框编辑调用**

Run: `pytest "tests/test_reader_shell.py::test_reader_bundle_wires_bubble_edit_actions" -q`

Expected: FAIL

- [x] **Step 3: 为右侧面板补齐编辑表单**

在 `renderBubbleEditorPanel()` 中输出字段：

```javascript
<textarea id="bubbleTranslatedTextInput">${escapeHtml(bubble.translatedText || "")}</textarea>
<input id="bubbleFontSizeInput" type="number" value="${bubble.fontSize || ""}" />
<select id="bubbleTextDirectionInput">...</select>
<input id="bubbleLineSpacingInput" type="number" step="0.05" value="${bubble.lineSpacing || 1.0}" />
<select id="bubbleTextAlignInput">...</select>
<button id="saveBubbleBtn">保存当前框</button>
<button id="rerenderBubbleBtn">重排当前框</button>
```

- [x] **Step 4: 保存当前框调用后端**

```javascript
async function saveSelectedBubble() {
  const patch = collectBubblePatchFromForm();
  const result = await requestJson("/api/pipeline/update-bubble", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pageId: state.currentPageId,
      bubbleIndex: state.selectedBubbleIndex,
      patch,
    }),
  });
  applyCurrentResult(result);
  renderBubbleEditorPanel();
}
```

- [x] **Step 5: 支持最小拖拽 / 缩放**

先不做复杂控制点，第一版只支持矩形框拖动和右下角缩放：

```javascript
state.dragMode = null;
state.dragBubbleIndex = null;

elements.overlay?.addEventListener("pointerdown", handleOverlayPointerDown);
window.addEventListener("pointermove", handleOverlayPointerMove);
window.addEventListener("pointerup", handleOverlayPointerUp);
```

要求：

- 只修改当前 `bubbleStates[index].coords`
- 拖动完成后必须调用 `update-bubble`

- [x] **Step 6: 单框重排版并刷新译图**

```javascript
async function rerenderSelectedBubble() {
  const result = await requestJson("/api/pipeline/rerender-bubble", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pageId: state.currentPageId,
      bubbleIndex: state.selectedBubbleIndex,
    }),
  });
  applyCurrentResult(result);
  await loadPage(state.currentPageId);
  state.view = "translated";
  renderCurrentPage();
}
```

- [x] **Step 7: 回跑前端壳测试**

Run: `pytest "tests/test_reader_shell.py" -q`

Expected: PASS

---

## Task 5: B1 章节上下文一致性

**Files:**
- Create: `D:/github/translate-reader/translate-reader/src/core/context/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/core/translate/openai_compatible.py`
- Modify: `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/storage/library_store.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_context_service.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_translate_adapter.py`

- [x] **Step 1: 写失败测试，要求手动修正能进入章节上下文**

```python
def test_build_context_snapshot_prefers_manual_confirmed_translations():
    pages = [
        {"id": "page-0001", "fileName": "001.jpg"},
        {"id": "page-0002", "fileName": "002.jpg"},
    ]
    results = {
        "page-0001": {
            "manualEdited": True,
            "bubbleStates": [{"originalText": "先輩", "translatedText": "学姐"}],
        }
    }

    snapshot = build_context_snapshot(pages, results, current_page_id="page-0002")

    assert "学姐" in snapshot["confirmedTranslations"]
```

- [x] **Step 2: 运行测试，确认当前没有章节上下文服务**

Run: `pytest "tests/test_context_service.py::test_build_context_snapshot_prefers_manual_confirmed_translations" -q`

Expected: FAIL

- [x] **Step 3: 实现上下文服务**

`src/core/context/service.py`

```python
def build_context_snapshot(pages, results_by_page, current_page_id, window=3):
    page_ids = [page["id"] for page in pages]
    current_index = page_ids.index(current_page_id)
    history_ids = page_ids[max(0, current_index - window):current_index]
    confirmed = []
    glossary = {}

    for page_id in history_ids:
        result = results_by_page.get(page_id) or {}
        for bubble in result.get("bubbleStates", []):
            original = (bubble.get("originalText") or "").strip()
            translated = (bubble.get("translatedText") or "").strip()
            if not translated:
                continue
            confirmed.append(translated)
            if result.get("manualEdited") and original:
                glossary[original] = translated

    return {
        "historyPageIds": history_ids,
        "confirmedTranslations": confirmed,
        "glossary": glossary,
    }
```

- [x] **Step 4: 翻译 adapter 支持上下文输入**

在 `src/core/translate/openai_compatible.py` 中把消息构建扩展为：

```python
def translate_texts(self, texts, model, base_url, api_key="dummy", context_snapshot=None):
    ...
```

系统提示中追加：

```python
if context_snapshot:
    glossary_lines = [f"{k} -> {v}" for k, v in context_snapshot.get("glossary", {}).items()]
```

要求：

- 只追加“邻近页确认译文”和“术语映射”
- 不把全章原文直接拼进去

- [x] **Step 5: 在整页流水线中注入上下文**

在 `src/core/pipeline/service.py` 中：

```python
pages = LibraryStore(app).list_pages()
results_by_page = {
    page["id"]: CacheStore(app).load_result(page["id"])
    for page in pages
    if page["id"] != page_id
}
context_snapshot = build_context_snapshot(pages, results_by_page, page_id)
translated_texts = translate_texts(
    ocr["originalTexts"],
    model=model,
    base_url=base_url,
    context_snapshot=context_snapshot,
)
payload["contextInputs"] = context_snapshot
```

- [x] **Step 6: 运行上下文相关测试**

Run: `pytest "tests/test_context_service.py" "tests/test_translate_adapter.py" -q`

Expected: PASS

---

## Task 6: C1 基于真实阅读器流程的性能优化

**Files:**
- Modify: `D:/github/translate-reader/translate-reader/src/core/pipeline/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/core/editing/service.py`
- Modify: `D:/github/translate-reader/translate-reader/src/app/static/app.js`
- Test: `D:/github/translate-reader/translate-reader/tests/test_editing_service.py`
- Test: `D:/github/translate-reader/translate-reader/tests/test_pipeline_service.py`

- [x] **Step 1: 写失败测试，要求单框重排版不重跑整页检测 / OCR / 翻译**

```python
def test_rerender_single_bubble_does_not_call_detect_or_translate(monkeypatch):
    called = {"detect": 0, "translate": 0}

    monkeypatch.setattr("src.core.editing.service.detect_page", lambda *args, **kwargs: called.__setitem__("detect", called["detect"] + 1))
    monkeypatch.setattr("src.core.editing.service.translate_texts", lambda *args, **kwargs: called.__setitem__("translate", called["translate"] + 1))

    # 执行单框重渲染
    ...

    assert called["detect"] == 0
    assert called["translate"] == 0
```

- [x] **Step 2: 运行测试，确认当前没有显式防回归保护**

Run: `pytest "tests/test_editing_service.py::test_rerender_single_bubble_does_not_call_detect_or_translate" -q`

Expected: FAIL

- [x] **Step 3: 明确区分“整页流程”和“编辑流程”**

要求：

- `run_page_pipeline()` 仅用于首轮自动生成
- 单框编辑只允许依赖：
  - `cleanImagePath`
  - `translatedImagePath`
  - `bubbleStates`

不允许：

- 重跑 `detect_page`
- 重跑 `ocr_page`
- 重跑 `translate_texts`

- [x] **Step 4: 在 UI 上直出当前页耗时**

在 `renderTimingPanel()` 中增加：

```javascript
const totalSeconds = timings.total || 0;
elements.statusText.textContent = `当前页总耗时 ${totalSeconds.toFixed(2)}s`;
```

同时为手动微调链路记录：

- `saveBubble`
- `rerenderBubble`
- `redoInpaint`
- `redoRender`

- [x] **Step 5: 用真实章节目录做 smoke**

Run:

```powershell
@'
from pathlib import Path
from time import perf_counter
from src.app import create_app

folder = Path(r"D:/github/translate-reader/翻译测试日漫/单话测试")
...
'@ | python -
```

记录：

- 前 3 页 `run-page` 耗时
- 单框保存耗时
- 单框重排版耗时

Smoke 结果（`D:/github/translate-reader/翻译测试日漫/单话测试`）：

- `009.jpg`：整页 `29.20s`
- `010.jpg`：整页 `26.36s`
- `011.jpg`：整页 `35.88s`
- `page-0001` 单框保存：`0.001s`
- `page-0001` 单框重排：`0.37s`

验收目标：

- 单框重排版明显快于整页完整重跑
- 所有耗时都能在 UI 中读取

---

## 自检

### Spec coverage

- A1 阅读器工作区：Task 1、Task 2
- A2 单框人工微调：Task 3、Task 4
- B1 章节上下文一致性：Task 5
- C1 单页性能优化：Task 1、Task 6

### Placeholder scan

- 未使用 `TBD` / `TODO`
- 每个任务都给了具体文件和测试入口
- 所有新增接口都已命名并落在现有路由结构内

### Type consistency

- 页面主键统一为 `pageId`
- 气泡主状态统一为 `bubbleStates`
- 单页缓存主文件仍为 `result.json`
- 单框编辑接口统一使用 `bubbleIndex + patch`
