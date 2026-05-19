# Multimodal Layout Assist Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立的“多模态AI辅助”样式，并保持现有 Auto 样式不接入多模态、不改变默认速度和行为。

**Architecture:** 新样式通过 style profile 标记 `layout_assist=multimodal`，流水线在 Saber 预处理后按需调用 OpenAI-compatible 多模态接口，得到页面角色、横竖排和粗框提示。提示只合并为 `bubbleLayoutHints`，用于影响现有 profile/嵌字策略；OCR、翻译、擦字和最终渲染仍走现有链路。多模态失败或未配置时只让新样式降级，不影响 Auto。

**Tech Stack:** Python 3.10, pytest, Pillow, OpenAI-compatible chat completions vision payload, translate_manga_v2 CLI/pipeline.

---

### Task 1: 样式入口和配置

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/styles.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/menu.py`
- Modify: `translate_manga_v2/batch_translate.py`
- Modify: `translate_manga_v2/run_batch_background.py`
- Modify: `translate_manga_v2/config/defaults.json`
- Modify: `translate_manga_v2/config/local.example.json`
- Modify: `translate_manga_v2/src/translate_manga/config/settings.py`
- Test: `translate_manga_v2/tests/test_style_profiles.py`
- Test: `translate_manga_v2/tests/test_batch_translate_entry.py`
- Test: `translate_manga_v2/tests/test_run_batch_background.py`
- Test: `translate_manga_v2/tests/test_cli_menu.py`
- Test: `translate_manga_v2/tests/test_settings.py`

- [x] **Step 1: 写失败测试**

新增测试证明 `m/mm/multimodal/style_mm/多模态` 能解析为 `style_mm`，`style_mm` 是 auto layout JP 且带 `layout_assist.type == "multimodal"`；同时断言 `auto` 没有 layout assist。CLI 和菜单测试断言新参数可传入并保存 session。

- [x] **Step 2: 运行失败测试**

Run:

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_style_profiles.py" "D:/github/translate-reader/translate_manga_v2/tests/test_batch_translate_entry.py" "D:/github/translate-reader/translate_manga_v2/tests/test_run_batch_background.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_menu.py" "D:/github/translate-reader/translate_manga_v2/tests/test_settings.py" -q
```

Expected: FAIL，原因是新样式、新配置解析函数或 CLI choices 尚不存在。

- [x] **Step 3: 实现样式和配置**

新增 style profile、菜单选项和 argparse choices。新增 `multimodal_layout` 配置解析，公开模板不写密钥；配置默认不全局启用，只有新样式会请求启用。

- [x] **Step 4: 运行测试变绿**

Run 同 Step 2，Expected: PASS。

### Task 2: 多模态布局服务

**Files:**
- Create: `translate_manga_v2/src/translate_manga/core/multimodal_layout.py`
- Test: `translate_manga_v2/tests/test_multimodal_layout.py`

- [x] **Step 1: 写失败测试**

测试 JSON 解析、bbox 归一化、角色/方向标准化、IoU/中心匹配、以及 page number/header suppress 和 narration/dialogue direction hint。

- [x] **Step 2: 运行失败测试**

Run:

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_multimodal_layout.py" -q
```

Expected: FAIL，原因是模块不存在。

- [x] **Step 3: 实现服务**

实现 `request_multimodal_layout()`、`normalize_multimodal_layout_response()`、`build_bubble_layout_hints()` 和 `apply_multimodal_layout_assist()`。网络调用只在配置完整且新样式启用时发生；失败写入 `status=failed` 和错误摘要，不抛出阻断整页。

- [x] **Step 4: 运行测试变绿**

Run 同 Step 2，Expected: PASS。

### Task 3: 流水线合并提示

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/debug_artifacts.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_cli_service_styles.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`

- [x] **Step 1: 写失败测试**

测试 `bubbleLayoutHints` 会让页码/页眉 suppress、让 narration 按提示切横/竖排、让 run options 和 cache signature 记录多模态辅助；同时验证 `auto` 不触发多模态配置。

- [x] **Step 2: 运行失败测试**

Run:

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_service_styles.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_batch.py" -q
```

Expected: FAIL，原因是提示尚未合并。

- [x] **Step 3: 实现提示合并**

在 `_prepare_batch` 的预处理产物生成后调用多模态 assist。`build_bubble_text_profiles()` 读取 `bubbleLayoutHints`，只覆盖角色、方向、suppress、对齐和长说明块参数，不替换 OCR 文本。

- [x] **Step 4: 运行测试变绿**

Run 同 Step 2，Expected: PASS。

### Task 4: 文档和全量验证

**Files:**
- Modify: `translate_manga_v2/README.md`
- Modify: `translate_manga_v2/start.md`

- [x] **Step 1: 更新说明**

说明 Auto 与多模态辅助的区别、配置位置、失败降级和能力边界。

- [x] **Step 2: 运行目标测试和编译**

Run:

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_style_profiles.py" "D:/github/translate-reader/translate_manga_v2/tests/test_multimodal_layout.py" "D:/github/translate-reader/translate_manga_v2/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_service_styles.py" "D:/github/translate-reader/translate_manga_v2/tests/test_batch_translate_entry.py" "D:/github/translate-reader/translate_manga_v2/tests/test_run_batch_background.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_menu.py" "D:/github/translate-reader/translate_manga_v2/tests/test_settings.py" -q
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m compileall -q "D:/github/translate-reader/translate_manga_v2/src"
```

Expected: PASS。

### Self-Review

- Spec coverage: Auto 不接多模态、新样式独立、配置独立、失败降级、提示合并、文档说明均有任务覆盖。
- Placeholder scan: 无 TBD/TODO 占位。
- Type consistency: 统一使用 `style_mm`、`layout_assist`、`multimodal_layout`、`bubbleLayoutHints`、`multimodalLayout`。
