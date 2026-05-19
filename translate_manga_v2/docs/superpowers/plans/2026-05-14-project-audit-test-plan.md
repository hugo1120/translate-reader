# Project Audit Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 `translate_manga_v2` 进行项目级审计，验证入口、配置、纠错、质检、流水线、渲染和文档说明是否一致，并给出可复现的测试结果。

**Architecture:** 本计划以只读审计和自动化测试为主，不覆盖真实漫画输出，不删除或移动文件。若发现确定缺陷，先补最小回归测试，再用 `apply_patch` 做小范围修复，并重新执行受影响测试与全量测试。

**Tech Stack:** Python 3.10、本地 `.venv310`、pytest、compileall、PowerShell、批处理入口 `start_cli.bat`。

---

### Task 1: 项目结构与工作树审计

**Files:**
- Read: `AGENTS.md`
- Read: `agent-docs/index.md`
- Read: `translate_manga_v2/AGENTS.md`
- Read: `translate_manga_v2/README.md`
- Read: `translate_manga_v2/start.md`
- Read: `translate_manga_v2/config/defaults.json`
- Read: `translate_manga_v2/config/local.example.json`

- [ ] **Step 1: 列出当前工作树状态**

Run:

```powershell
git status --short
```

Expected: 输出当前已修改和未跟踪文件；不执行 reset、checkout、clean。

- [ ] **Step 2: 列出 V2 文件清单**

Run:

```powershell
rg --files "translate_manga_v2"
```

Expected: 输出 V2 源码、测试、配置和文档文件，确认审计范围。

- [ ] **Step 3: 读取项目约束与记忆入口**

Run:

```powershell
Get-Content -Raw "agent-docs/index.md"
Get-Content -Raw "translate_manga_v2/AGENTS.md"
```

Expected: 确认当前活跃项目、入口、样式约定、纠错缓存约束和常用验证命令。

### Task 2: 分模块测试矩阵

**Files:**
- Test: `translate_manga_v2/tests/test_cli_menu.py`
- Test: `translate_manga_v2/tests/test_batch_translate_entry.py`
- Test: `translate_manga_v2/tests/test_run_batch_background.py`
- Test: `translate_manga_v2/tests/test_quality_review.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`
- Test: `translate_manga_v2/tests/test_cli_service_styles.py`
- Test: `translate_manga_v2/tests/test_settings.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_inpaint_render_services.py`
- Test: `translate_manga_v2/tests/test_saber_loader.py`

- [ ] **Step 1: 运行 CLI 与菜单相关测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest tests/test_cli_menu.py tests/test_batch_translate_entry.py tests/test_run_batch_background.py tests/test_cli_batch.py tests/test_cli_service_styles.py -q
```

Expected: exit code 0，CLI 参数、菜单纠错、后台入口、样式映射相关测试通过。

- [ ] **Step 2: 运行配置、上下文、书系 Profile 测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest tests/test_settings.py tests/test_context_service.py tests/test_manga_context.py tests/test_manga_context_service.py tests/test_book_profile.py -q
```

Expected: exit code 0，配置优先级、漫画背景、书系 profile 相关测试通过。

- [ ] **Step 3: 运行流水线、OCR、Saber、渲染与编辑测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest tests/test_pipeline_service.py tests/test_pipeline_runtime.py tests/test_pipeline_filtering.py tests/test_page_classifier.py tests/test_ocr_service.py tests/test_saber_loader.py tests/test_saber_detection_reading_order.py tests/test_inpaint_render_services.py tests/test_editing_service.py tests/test_style_profiles.py -q
```

Expected: exit code 0，核心流水线、OCR、Saber 集成、擦字、写字、样式配置相关测试通过。

- [ ] **Step 4: 运行质检与翻译适配层测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest tests/test_quality_review.py tests/test_translate_adapter.py tests/test_paddle_ocr_onnx_interface.py tests/test_package_imports.py tests/test_project_paths.py tests/test_constants.py tests/test_start_cli_bat.py -q
```

Expected: exit code 0，质量扫描、翻译 API 适配、Paddle 接口、包导入、路径和启动脚本测试通过。

- [ ] **Step 5: 运行全量测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest -q
```

Expected: exit code 0，全部 pytest 用例通过。

### Task 3: 编译与入口可用性验证

**Files:**
- Compile: `translate_manga_v2/src`
- Compile: `translate_manga_v2/batch_translate.py`
- Compile: `translate_manga_v2/run_batch_background.py`
- Execute: `translate_manga_v2/start_cli.bat`

- [ ] **Step 1: 编译源码和入口脚本**

Run:

```powershell
./.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py
```

Expected: exit code 0，没有语法错误或导入期编译错误。

- [ ] **Step 2: 验证核心模块可导入**

Run:

```powershell
./.venv310/Scripts/python.exe -c "import translate_manga; import translate_manga.cli.menu; import translate_manga.cli.quality_review; import translate_manga.core.pipeline.service; print('imports ok')"
```

Expected: 输出 `imports ok`，exit code 0。

- [ ] **Step 3: 验证批处理帮助入口**

Run:

```powershell
./.venv310/Scripts/python.exe batch_translate.py --help
./.venv310/Scripts/python.exe run_batch_background.py --help
```

Expected: 两个命令都能输出帮助文本，包含 `--style-id`、`--retry-review-pages`、`--retry-quality-review-pages`。

- [ ] **Step 4: 验证 bat 透传帮助入口**

Run:

```powershell
cmd /c start_cli.bat --help
```

Expected: 能透传到 `batch_translate.py --help` 并输出帮助文本。

### Task 4: 菜单、配置、文档一致性检查

**Files:**
- Inspect: `translate_manga_v2/src/translate_manga/cli/menu.py`
- Inspect: `translate_manga_v2/batch_translate.py`
- Inspect: `translate_manga_v2/run_batch_background.py`
- Inspect: `translate_manga_v2/start_cli.bat`
- Inspect: `README.md`
- Inspect: `translate_manga_v2/README.md`
- Inspect: `translate_manga_v2/start.md`

- [ ] **Step 1: 搜索样式和 Auto 说明**

Run:

```powershell
rg -n "style-id|style_id|style auto|style_auto|Auto|样式|排版|layout" README.md translate_manga_v2/README.md translate_manga_v2/start.md translate_manga_v2/batch_translate.py translate_manga_v2/run_batch_background.py translate_manga_v2/src/translate_manga/cli/menu.py translate_manga_v2/start_cli.bat
```

Expected: 文档和入口都说明 `1/2/3/Auto` 或等价支持，不出现互相矛盾的样式映射。

- [ ] **Step 2: 搜索纠错与质检说明**

Run:

```powershell
rg -n "扫描并纠正错误|retry-review-pages|retry-quality-review-pages|quality-review|failed-translations|review-pages|translation_failed|质检|纠错" README.md translate_manga_v2/README.md translate_manga_v2/start.md translate_manga_v2/batch_translate.py translate_manga_v2/run_batch_background.py translate_manga_v2/src/translate_manga/cli/menu.py translate_manga_v2/src/translate_manga/cli/quality_review.py
```

Expected: 文档明确区分硬错误扫描和通篇译文质检，参数入口与菜单实现一致。

- [ ] **Step 3: 检查配置模板是否包含当前功能键**

Run:

```powershell
rg -n "scan_fix_translation|quality_review|retry_quality|style|layout_mode|prompt_profile|source_language|reading_order" translate_manga_v2/config/defaults.json translate_manga_v2/config/local.example.json translate_manga_v2/src/translate_manga/config translate_manga_v2/src/translate_manga/core/styles.py
```

Expected: defaults、example、settings 和 styles 对当前功能键的命名一致。

### Task 5: 真实 Debug 数据只读抽查

**Files:**
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug`
- Read: `翻译测试日漫/白土三平/卡姆依传/02/out/_debug`
- Execute: `translate_manga_v2/src/translate_manga/cli/menu.py`
- Execute: `translate_manga_v2/src/translate_manga/cli/quality_review.py`

- [ ] **Step 1: 统计 01、02 的 debug 产物**

Run:

```powershell
@'
from pathlib import Path
roots = [
    Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01/out"),
    Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/02/out"),
]
for root in roots:
    debug = root / "_debug"
    pages = list((debug / "pages").glob("*.json")) if (debug / "pages").exists() else []
    outputs = list(root.glob("*.translated.png"))
    failed = debug / "failed-translations.tsv"
    review = debug / "review-pages.txt"
    quality = debug / "quality-review.tsv"
    print(root)
    print("outputs", len(outputs), "pages_json", len(pages))
    for path in [failed, review, quality]:
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            print(path.name, len(lines), "lines")
        else:
            print(path.name, "missing")
'@ | & ./.venv310/Scripts/python.exe -
```

Expected: 只读取统计，不改写真实输出目录。

- [ ] **Step 2: 用代码路径只读收集 retry 候选**

Run:

```powershell
@'
from pathlib import Path
from translate_manga.cli.menu import _collect_review_entries
roots = [
    (
        Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01"),
        Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01/out"),
    ),
    (
        Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/02"),
        Path(r"D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/02/out"),
    ),
]
for input_dir, root in roots:
    hard = _collect_review_entries(input_dir, root, include_quality_review=False)
    quality = _collect_review_entries(input_dir, root, include_quality_review=True)
    print(root)
    print("hard", len(hard), "hard+quality", len(quality))
'@ | & ./.venv310/Scripts/python.exe -
```

Expected: 菜单 3 的重跑候选收集逻辑能读取失败、复查、缺失输出和 quality review 文件。

### Task 6: 补救与复验

**Files:**
- Modify only if needed: `translate_manga_v2/src/**`
- Modify only if needed: `translate_manga_v2/tests/**`
- Modify only if needed: `README.md`
- Modify only if needed: `translate_manga_v2/README.md`
- Modify only if needed: `translate_manga_v2/start.md`

- [ ] **Step 1: 若发现确定 bug，先写针对性失败测试**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest path/to/relevant_test.py::test_specific_case -q
```

Expected: 新测试在修复前失败，失败原因对应已发现问题。

- [ ] **Step 2: 使用 apply_patch 做最小修复**

Action: 只修改相关源码、测试或文档，不重排无关代码，不改真实 `config/local.json`，不覆盖漫画输出。

Expected: diff 只包含与发现问题直接相关的改动。

- [ ] **Step 3: 运行针对性复验和全量复验**

Run:

```powershell
./.venv310/Scripts/python.exe -m pytest path/to/relevant_test.py -q
./.venv310/Scripts/python.exe -m pytest -q
./.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py
git diff --check
```

Expected: 相关测试、全量测试、编译和 diff 空白检查通过。

### Task 7: 结论报告

**Files:**
- Read: `translate_manga_v2/docs/superpowers/plans/2026-05-14-project-audit-test-plan.md`

- [ ] **Step 1: 汇总测试证据**

Action: 记录每个命令的 exit code、通过数量、失败数量和发现问题。

Expected: 结论只基于本轮实际执行结果，不使用旧结果替代。

- [ ] **Step 2: 明确剩余风险**

Action: 区分“自动化已覆盖的问题”和“真实翻译语义/嵌字审美仍需人工或样本回归覆盖的问题”。

Expected: 不承诺菜单 3 能识别所有翻译错误；说明硬错误扫描、质检启发式和模型质检的边界。
