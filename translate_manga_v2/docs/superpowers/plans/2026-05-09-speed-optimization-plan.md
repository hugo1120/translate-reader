# Speed Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升批量漫画翻译的可观测性和低风险吞吐速度，先优化日志写盘、耗时定位、取色开销和翻译轮数选择。

**Architecture:** 本阶段不引入 Saber 多 worker，也不并发打多个翻译 API，避免稳定性和限流风险。先在 debug 层聚合耗时并减少重复写盘，在 pipeline 层加入可配置 color fast mode，在翻译层加入 `fast/balanced/high` 质量档位。

**Tech Stack:** Python 3.10+、pytest、现有 `translate_manga` CLI pipeline、Saber-Translator vendor。

---

## File Map

- Modify: `src/translate_manga/cli/debug_artifacts.py`
  - 负责 `_debug` 产物写入、summary、final review report。
  - 新增耗时聚合 `timingSummary`。
  - 新增延迟 flush，避免每页重写整本索引和 book 文本。
- Modify: `src/translate_manga/core/pipeline/service.py`
  - 负责 preprocess/render 前后的色彩指标和气泡可读性样式。
  - 新增 color fast mode，在背景明显简单时跳过或简化昂贵背景指标计算。
- Modify: `src/translate_manga/config/settings.py`
  - 解析新增 pipeline 配置：`debug_flush_interval`、`color_fast_mode`、`translation_quality`。
- Modify: `config/defaults.json`
  - 增加默认低风险配置。
- Modify: `src/translate_manga/cli/service.py`
  - 把 translation quality 传入翻译上下文和 runOptions。
  - 在翻译缓存签名中纳入 translation quality，避免不同质量档复用旧译文。
- Modify: `src/translate_manga/core/translate/openai_compatible.py`
  - 根据 `context_snapshot["translationQuality"]` 决定 1/2/3 轮翻译。
- Modify: `README.md`, `start.md`, `docs/translation_prompt_scheme.md`
  - 记录性能相关配置和质量档位。
- Test: `tests/test_cli_batch.py`
- Test: `tests/test_pipeline_service.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_translate_adapter.py`
- Test: `tests/test_cli_service_styles.py`

---

### Task 1: Debug 耗时聚合

**Files:**
- Modify: `src/translate_manga/cli/debug_artifacts.py`
- Test: `tests/test_cli_batch.py`

- [x] **Step 1: 写失败测试**

在 `tests/test_cli_batch.py` 增加测试，直接使用 `BatchDebugArtifactWriter` 写两页记录：

```python
def test_debug_writer_summarizes_timing_breakdown(tmp_path):
    output_dir = tmp_path / "out"
    writer = BatchDebugArtifactWriter(output_dir)

    for index, timings in enumerate(
        [
            {"detect": 1.0, "ocr": 2.0, "color": 3.0, "translate": 4.0, "render": 5.0, "total": 15.0},
            {"detect": 2.0, "ocr": 4.0, "color": 6.0, "translate": 8.0, "render": 10.0, "total": 30.0},
        ],
        start=1,
    ):
        writer.record_page(
            page={"id": f"page-{index}", "fileName": f"{index:03d}.jpg"},
            page_index=index,
            total_pages=2,
            source_path=tmp_path / f"{index:03d}.jpg",
            target_path=output_dir / f"{index:03d}.translated.png",
            status="translated",
            preprocessed_payload={"bubbleCoords": [], "originalTexts": [], "timings": timings},
            translated_texts=[],
            translation_payload=None,
            classification={"should_translate": False, "page_type": "blank", "skip_reason": "blank"},
        )

    writer.finish({"total": 2, "succeeded": 2, "skipped": 0, "failed": 0})
    summary = json.loads((output_dir / "_debug" / "summary.json").read_text(encoding="utf-8"))
    report = (output_dir / "_debug" / "final-review-report.txt").read_text(encoding="utf-8")

    assert summary["timingSummary"]["pageCount"] == 2
    assert summary["timingSummary"]["totals"]["ocr"] == 6.0
    assert summary["timingSummary"]["averages"]["total"] == 22.5
    assert summary["timingSummary"]["slowestPages"][0]["sourceName"] == "002.jpg"
    assert "## 阶段耗时汇总" in report
    assert "ocr: total=6.00s avg=3.00s" in report
```

- [x] **Step 2: 确认 RED**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_summarizes_timing_breakdown -q
```

Expected: FAIL，提示缺少 `timingSummary` 或报告章节。

- [x] **Step 3: 实现耗时聚合**

在 `BatchDebugArtifactWriter` 中新增：

```python
def _read_timing_value(record, name):
    timings = record.get("timings") if isinstance(record.get("timings"), dict) else {}
    try:
        return max(0.0, float(timings.get(name, 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _build_timing_summary(self, ordered_records):
    fields = ["detect", "ocr", "color", "translate", "render", "total"]
    totals = {field: 0.0 for field in fields}
    for record in ordered_records:
        for field in fields:
            totals[field] += _read_timing_value(record, field)
    page_count = len(ordered_records)
    averages = {
        field: (totals[field] / page_count if page_count else 0.0)
        for field in fields
    }
    slowest = sorted(
        ordered_records,
        key=lambda record: _read_timing_value(record, "total"),
        reverse=True,
    )[:10]
    return {
        "pageCount": page_count,
        "totals": {field: round(totals[field], 3) for field in fields},
        "averages": {field: round(averages[field], 3) for field in fields},
        "slowestPages": [
            {
                "sourceName": record.get("sourceName"),
                "total": round(_read_timing_value(record, "total"), 3),
                "detect": round(_read_timing_value(record, "detect"), 3),
                "ocr": round(_read_timing_value(record, "ocr"), 3),
                "color": round(_read_timing_value(record, "color"), 3),
                "translate": round(_read_timing_value(record, "translate"), 3),
                "render": round(_read_timing_value(record, "render"), 3),
            }
            for record in slowest
        ],
    }
```

把 `timingSummary` 加入 `_build_summary()`；在 `_build_final_review_report()` 增加“阶段耗时汇总”章节。

- [x] **Step 4: 验证 GREEN**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_summarizes_timing_breakdown -q
```

Expected: PASS。

---

### Task 2: Debug 写盘降频

**Files:**
- Modify: `src/translate_manga/cli/debug_artifacts.py`
- Test: `tests/test_cli_batch.py`

- [x] **Step 1: 写失败测试**

新增测试验证每页 JSON 仍立即落盘，但 summary/book/index 按 flush interval 延迟到 finish：

```python
def test_debug_writer_flushes_indexes_by_interval(tmp_path):
    output_dir = tmp_path / "out"
    writer = BatchDebugArtifactWriter(output_dir, flush_interval=3)

    for index in range(1, 3):
        writer.record_page(
            page={"id": f"page-{index}", "fileName": f"{index:03d}.jpg"},
            page_index=index,
            total_pages=2,
            source_path=tmp_path / f"{index:03d}.jpg",
            target_path=output_dir / f"{index:03d}.translated.png",
            status="translated",
            preprocessed_payload={"bubbleCoords": [], "originalTexts": [f"ocr-{index}"], "timings": {}},
            translated_texts=[f"zh-{index}"],
            translation_payload=None,
            classification={"should_translate": True, "page_type": "content", "skip_reason": None},
        )
        assert (output_dir / "_debug" / "pages" / f"{index:03d}.json").exists()

    assert not (output_dir / "_debug" / "summary.json").exists()
    writer.finish({"total": 2, "succeeded": 2, "skipped": 0, "failed": 0})

    assert (output_dir / "_debug" / "summary.json").exists()
    assert "ocr-1" in (output_dir / "_debug" / "book.ocr.txt").read_text(encoding="utf-8")
```

- [x] **Step 2: 确认 RED**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_flushes_indexes_by_interval -q
```

Expected: FAIL，因为构造函数没有 `flush_interval`，且当前每页都会写 `summary.json`。

- [x] **Step 3: 实现 flush interval**

修改构造函数：

```python
def __init__(self, output_dir, run_options=None, flush_interval=1):
    self.output_dir = Path(output_dir)
    self.debug_root = self.output_dir / "_debug"
    self.pages_root = self.debug_root / "pages"
    self.texts_root = self.debug_root / "texts"
    self.manifest_path = self.debug_root / "pages.jsonl"
    self.summary_path = self.debug_root / "summary.json"
    self.book_ocr_path = self.debug_root / "book.ocr.txt"
    self.book_translation_path = self.debug_root / "book.translation.txt"
    self.review_pages_path = self.debug_root / "review-pages.txt"
    self.failed_translations_path = self.debug_root / "failed-translations.tsv"
    self.final_review_report_path = self.debug_root / "final-review-report.txt"
    self.pages_root.mkdir(parents=True, exist_ok=True)
    self.texts_root.mkdir(parents=True, exist_ok=True)
    self.records = {}
    self.finished_summary = None
    self.run_options = dict(run_options or {})
    self.flush_interval = max(1, int(flush_interval or 1))
    self._dirty_records = 0
```

修改 `record_page()` 末尾：

```python
self.records[int(page_index)] = record
self._write_page_files(record)
self._dirty_records += 1
if self._dirty_records >= self.flush_interval:
    self._flush_index()
    self._dirty_records = 0
return record
```

修改 `finish()` 末尾确保总是 flush：

```python
self._flush_index()
self._dirty_records = 0
```

- [x] **Step 4: 从配置传入 flush interval**

在 `settings.resolve_pipeline_config()` 返回：

```python
"debug_flush_interval": max(1, int(pipeline.get("debug_flush_interval", 25) or 25)),
```

在 `config/defaults.json` 的 `pipeline` 加：

```json
"debug_flush_interval": 25
```

在 `run_batch_translation()` 创建 writer 时：

```python
BatchDebugArtifactWriter(
    output_dir,
    run_options=run_options,
    flush_interval=pipeline_config.get("debug_flush_interval", 25),
)
```

- [x] **Step 5: 验证 GREEN**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_flushes_indexes_by_interval tests/test_settings.py::test_resolve_pipeline_config_supports_context_options -q
```

Expected: PASS，必要时更新 settings 测试里的期望字段。

---

### Task 3: Color Fast Mode

**Files:**
- Modify: `src/translate_manga/core/pipeline/service.py`
- Modify: `src/translate_manga/config/settings.py`
- Modify: `config/defaults.json`
- Test: `tests/test_pipeline_service.py`
- Test: `tests/test_settings.py`

- [x] **Step 1: 写失败测试**

在 `tests/test_pipeline_service.py` 增加测试，验证 fast mode 下简单白底颜色不调用昂贵背景指标：

```python
def test_enrich_bubble_color_metrics_fast_mode_skips_simple_white_bubbles(monkeypatch, tmp_path):
    source_path = tmp_path / "001.jpg"
    Image.new("RGB", (120, 120), "white").save(source_path)
    called = {"count": 0}

    def fake_enrich(payload, source_path, bubble_coords, textlines_per_bubble):
        called["count"] += 1
        return payload

    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.enrich_bubble_colors_with_background_metrics",
        fake_enrich,
    )
    monkeypatch.setattr(
        "translate_manga.core.pipeline.service.load_settings",
        lambda: {"pipeline": {"color_fast_mode": True}},
    )

    payload = {
        "bubbleColors": [
            {
                "bgColor": "#FFFFFF",
                "textColor": "#111111",
                "autoBgColor": [255, 255, 255],
                "autoFgColor": [17, 17, 17],
                "colorConfidence": 0.95,
            }
        ],
        "bubbleCoords": [[10, 10, 80, 80]],
        "textlinesPerBubble": [[]],
    }

    result = pipeline_service._enrich_bubble_color_metrics(payload, source_path)

    assert called["count"] == 0
    assert result["bubbleColors"][0]["grayStdDev"] == 0.0
    assert result["bubbleColors"][0]["edgeDensity"] == 0.0
    assert result["bubbleColors"][0]["darkPixelRatio"] == 0.0
```

- [x] **Step 2: 确认 RED**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_pipeline_service.py::test_enrich_bubble_color_metrics_fast_mode_skips_simple_white_bubbles -q
```

Expected: FAIL，因为当前总是调用 `enrich_bubble_colors_with_background_metrics()`。

- [x] **Step 3: 实现 fast 判断**

在 `pipeline/service.py` 新增：

```python
def _resolve_color_fast_mode():
    settings = load_settings()
    pipeline = settings.get("pipeline") or {}
    return bool(pipeline.get("color_fast_mode", True))


def _is_simple_light_bubble_color(color):
    if not isinstance(color, dict):
        return False
    bg_luminance = _resolve_background_luminance(color)
    confidence = float(color.get("colorConfidence", 0.0) or 0.0)
    if bg_luminance is None:
        return False
    return bg_luminance >= 235 and confidence >= 0.8


def _with_fast_background_metrics(color):
    updated = dict(color)
    updated.setdefault("grayStdDev", 0.0)
    updated.setdefault("edgeDensity", 0.0)
    updated.setdefault("darkPixelRatio", 0.0)
    return updated
```

修改 `_enrich_bubble_color_metrics()`：

```python
if _resolve_color_fast_mode() and all(_is_simple_light_bubble_color(color) for color in payload.get("bubbleColors", []) or []):
    enriched = dict(payload)
    enriched["bubbleColors"] = [_with_fast_background_metrics(color) for color in payload["bubbleColors"]]
    return enriched
```

- [x] **Step 4: 配置解析**

在 `settings.resolve_pipeline_config()` 返回：

```python
"color_fast_mode": bool(pipeline.get("color_fast_mode", True)),
```

在 `config/defaults.json` 的 `pipeline` 加：

```json
"color_fast_mode": true
```

- [x] **Step 5: 验证 GREEN**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_pipeline_service.py::test_enrich_bubble_color_metrics_fast_mode_skips_simple_white_bubbles tests/test_pipeline_service.py::test_build_bubbles_uses_dark_background_adaptive_style tests/test_settings.py::test_resolve_pipeline_config_supports_context_options -q
```

Expected: PASS。

---

### Task 4: 翻译质量档位

**Files:**
- Modify: `src/translate_manga/config/settings.py`
- Modify: `config/defaults.json`
- Modify: `src/translate_manga/cli/service.py`
- Modify: `src/translate_manga/core/translate/openai_compatible.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_cli_service_styles.py`
- Test: `tests/test_translate_adapter.py`

- [x] **Step 1: 写 settings 失败测试**

在 `tests/test_settings.py` 增加或扩展 pipeline config 测试：

```python
def test_resolve_pipeline_config_supports_speed_options(tmp_path):
    project_root = tmp_path
    config_root = project_root / "config"
    config_root.mkdir()
    (config_root / "defaults.json").write_text(
        json.dumps(
            {
                "pipeline": {
                    "translation_quality": "balanced",
                    "debug_flush_interval": 11,
                    "color_fast_mode": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = settings_module.resolve_pipeline_config(project_root=project_root)

    assert config["translation_quality"] == "balanced"
    assert config["debug_flush_interval"] == 11
    assert config["color_fast_mode"] is True
```

- [x] **Step 2: 确认 RED**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_settings.py::test_resolve_pipeline_config_supports_speed_options -q
```

Expected: FAIL，缺少新字段。

- [x] **Step 3: 实现配置解析**

在 `resolve_pipeline_config()` 里规范化：

```python
translation_quality = str(pipeline.get("translation_quality") or "high").strip().lower()
if translation_quality not in {"fast", "balanced", "high"}:
    translation_quality = "high"
```

返回：

```python
"translation_quality": translation_quality,
```

在 `config/defaults.json` 的 `pipeline` 加：

```json
"translation_quality": "high"
```

- [x] **Step 4: 写 CLI 上下文失败测试**

在 `tests/test_cli_service_styles.py` 增加：

```python
def test_build_translation_signature_tracks_quality():
    settings = {"pipeline": {"translation_quality": "high"}}
    high_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
        translation_quality="high",
    )
    fast_signature = cli_service._build_translation_signature(
        settings=settings,
        style_profile=resolve_style_profile("style2"),
        manga_context_payload=None,
        translation_quality="fast",
    )

    assert high_signature != fast_signature
```

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_service_styles.py::test_build_translation_signature_tracks_quality -q
```

Expected: FAIL，因为 `_build_translation_signature()` 不接受 quality。

- [x] **Step 5: 实现 CLI 传递**

修改 `_build_translation_signature(settings, style_profile=None, manga_context_payload=None, translation_quality=None)`，payload 增加：

```python
"translationQuality": str(translation_quality or "high").strip().lower() or "high",
```

修改 `_build_run_options()` 增加参数并写入：

```python
"translationQuality": translation_quality,
```

在 `run_batch_translation()`：

```python
translation_quality = pipeline_config.get("translation_quality", "high")
```

传给 runOptions、translation signature，并注入 `batch_context_snapshot`：

```python
"translationQuality": translation_quality,
```

- [x] **Step 6: 写翻译轮数失败测试**

在 `tests/test_translate_adapter.py` 增加 fast 和 balanced 测试：

```python
def test_translate_texts_with_metadata_fast_quality_runs_one_round(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            calls.append(messages)
            message = type("Message", (), {"content": "<|1|>快译"})()
            choice = type("Choice", (), {"message": message})()
            usage = type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["HELLO"],
        model="model",
        base_url="https://example.invalid/v1",
        context_snapshot={"translationQuality": "fast"},
    )

    assert len(calls) == 1
    assert [round_payload["name"] for round_payload in result["rounds"]] == ["final"]
    assert result["translatedTexts"] == ["快译"]
```

再加 balanced：

```python
def test_translate_texts_with_metadata_balanced_quality_runs_two_rounds(monkeypatch):
    responses = ["<|1|>初译", "<|1|>润色"]
    calls = []

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            calls.append(messages)
            message = type("Message", (), {"content": responses.pop(0)})()
            choice = type("Choice", (), {"message": message})()
            usage = type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["HELLO"],
        model="model",
        base_url="https://example.invalid/v1",
        context_snapshot={"translationQuality": "balanced"},
    )

    assert len(calls) == 2
    assert [round_payload["name"] for round_payload in result["rounds"]] == ["draft", "final"]
    assert result["translatedTexts"] == ["润色"]
```

- [x] **Step 7: 实现翻译质量档位**

在 `openai_compatible.py` 新增：

```python
def _resolve_translation_quality(context_snapshot):
    if not isinstance(context_snapshot, dict):
        return "high"
    value = str(context_snapshot.get("translationQuality") or "high").strip().lower()
    if value in {"fast", "balanced", "high"}:
        return value
    return "high"
```

在 `translate_texts_with_metadata()` 中读取 quality：

- `fast`：直接走现有单轮 final 逻辑。
- `balanced`：跑 draft，然后用 `_build_final_messages(texts, draft_texts, context_snapshot=context_snapshot, prompt_config=prompt_config)` 跑 final，rounds 为 `draft/final`。
- `high`：保持当前 dense 三轮逻辑不变。

实现时保留空文本 slot、usage 汇总和 `_analyze_ocr_retry()`。

- [x] **Step 8: 验证 GREEN**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_settings.py::test_resolve_pipeline_config_supports_speed_options tests/test_cli_service_styles.py::test_build_translation_signature_tracks_quality tests/test_translate_adapter.py::test_translate_texts_with_metadata_fast_quality_runs_one_round tests/test_translate_adapter.py::test_translate_texts_with_metadata_balanced_quality_runs_two_rounds -q
```

Expected: PASS。

---

### Task 5: 文档与回归

**Files:**
- Modify: `README.md`
- Modify: `start.md`
- Modify: `docs/translation_prompt_scheme.md`
- Test: full regression

- [x] **Step 1: 文档更新**

在 README/start 增加性能配置：

```md
性能相关配置在 `config/defaults.json` / `config/local.json` 的 `pipeline` 下：

- `translation_quality`: `high` / `balanced` / `fast`
- `debug_flush_interval`: 默认 `25`
- `color_fast_mode`: 默认 `true`

建议：
- 正式精翻：`high`
- 大批量预览：`balanced`
- 快速扫图或英文短页：`fast`
```

在 `docs/translation_prompt_scheme.md` 补充：`translation_quality` 会进入翻译缓存签名。

- [x] **Step 2: 定向回归**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py tests/test_pipeline_service.py tests/test_settings.py tests/test_translate_adapter.py tests/test_cli_service_styles.py -q
```

Expected: PASS。

- [x] **Step 3: 全量回归**

Run:

```powershell
.venv310/Scripts/python.exe -m pytest -q
.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py
cmd /c start_cli.bat --help
```

Expected:
- `pytest` 全量通过。
- `compileall` exit code 0。
- `start_cli.bat --help` 输出包含 `--style-id` 和 `--retry-review-pages`。

## Notes

- 本计划不执行 git commit，因为项目约束要求除非用户明确要求，否则不做提交/分支操作。
- 本计划不引入 Saber 多 worker；后续若需要，再单独做 Phase 5，并对内存占用、模型加载和 worker 崩溃恢复做专项设计。
- `translation_quality=high` 是默认值，保证现有质量和行为优先不回退。
