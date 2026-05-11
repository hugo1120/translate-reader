# Review Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 批量翻译完成后自动识别翻译失败/可疑页，并支持 `--retry-review-pages` 只重跑这些页覆盖输出。

**Architecture:** 在 debug artifact 层统一判断 `needsReview`，输出 `review-pages.txt` 与 `failed-translations.tsv`；在 CLI batch 层读取返工清单并过滤输入页。返工页复用 OCR/preprocess cache，但强制跳过坏的 translated cache，重新翻译并覆盖输出。

**Tech Stack:** Python 3.10+、pytest、Windows batch、现有 CLI pipeline。

---

### Task 1: Debug 识别翻译失败页

**Files:**
- Modify: `src/translate_manga/cli/debug_artifacts.py`
- Test: `tests/test_cli_batch.py`

- [x] **Step 1: 写失败测试**

新增测试：构造一个 `BatchDebugArtifactWriter`，写入 `translatedTexts=["【翻译失败】请检查终端中的错误日志"]` 且 `ocrRetry.reasons=["translation_failed"]` 的页面，断言：
- `record["needsReview"] is True`
- `record["reviewReasons"]` 包含 `translation_failed`
- `_debug/review-pages.txt` 包含源图名
- `_debug/failed-translations.tsv` 包含表头和源图名
- `_debug/summary.json` 包含 `reviewReasonCounts.translation_failed == 1`

- [x] **Step 2: 确认 RED**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_flags_translation_failure_placeholders -q`

Expected: FAIL，当前不生成 `failed-translations.tsv`，且 `needsReview` 为 False。

- [x] **Step 3: 实现 review 规则和 TSV 输出**

在 `debug_artifacts.py`：
- 引入 `TRANSLATION_FAILURE_TEXT`
- `_build_review_flags()` 接收 `translation_payload`
- 若 `ocrRetry.reasons` 含 `translation_failed`，加入 `translation_failed`
- 若任意译文等于 `TRANSLATION_FAILURE_TEXT`，加入 `translation_failure_placeholder`
- `_flush_index()` 写 `failed-translations.tsv`
- `_build_summary()` 增加 `reviewReasonCounts`

### Task 2: 返工清单读取

**Files:**
- Modify: `src/translate_manga/cli/service.py`
- Modify: `batch_translate.py`
- Test: `tests/test_cli_batch.py`
- Test: `tests/test_batch_translate_entry.py`

- [x] **Step 1: 写失败测试**

新增测试：输出目录存在旧版 `_debug/pages/page-2.json`，其中包含 `translation_failed` / 翻译失败占位符；调用 `run_batch_translation(..., retry_review_pages=True)`，断言只扫描/处理 `page-2.jpg`，并覆盖输出。

- [x] **Step 2: 确认 RED**

Run: `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_run_batch_translation_retry_review_pages_only_processes_failed_translation_list -q`

Expected: FAIL，当前 `run_batch_translation` 不支持 `retry_review_pages` 参数。

- [x] **Step 3: 实现过滤逻辑**

在 `service.py`：
- 新增 `_load_retry_review_page_names(output_dir)`，优先读 `_debug/failed-translations.tsv`，回退读 `_debug/review-pages.txt`
- `run_batch_translation()` 增加 `retry_review_pages=False`
- 若启用且清单为空，抛出清晰错误
- 若启用，过滤 `image_paths` 到清单内源图名
- 若启用，强制 `overwrite_existing=True`
- 若启用，translated cache 视为 preprocessed cache，重新翻译

### Task 3: CLI 参数

**Files:**
- Modify: `batch_translate.py`
- Modify: `src/translate_manga/cli/menu.py` 不改交互菜单，本阶段只加参数模式
- Test: `tests/test_batch_translate_entry.py`

- [x] **Step 1: 写失败测试**

新增测试：`batch_translate.py --retry-review-pages` 会把 `retry_review_pages=True` 传给 `run_batch_translation`。

- [x] **Step 2: 实现参数**

在 `_build_parser()` 增加：

```python
parser.add_argument("--retry-review-pages", action="store_true", help="只重跑 _debug 标记需要复查/失败的页，并覆盖输出")
```

调用 `run_batch_translation()` 时传入 `retry_review_pages=args.retry_review_pages`。

### Task 4: 验证

**Files:**
- No production file changes.

- [x] **Step 1: 定向单测**

Run:
- `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_flags_translation_failure_placeholders -q`
- `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_run_batch_translation_retry_review_pages_only_processes_failed_translation_list -q`
- `.venv310/Scripts/python.exe -m pytest tests/test_batch_translate_entry.py -q`

- [x] **Step 2: 回归**

Run:
- `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py -q`
- `.venv310/Scripts/python.exe -m pytest --ignore=tests/test_cli_batch.py -q`

- [x] **Step 3: 只读扫描旧 debug**

用新逻辑或临时只读命令扫描：
`D:/github/translate-reader/翻译测试日漫/德川家康/01/out/_debug/pages`

Expected: 能列出含 `tokugawa#01_010.jpg` 的返工清单。

## 自检

- 不修改 `D:/github/translate-reader/translate_manga_v2` 以外代码。
- 对旧输出目录只做读取扫描，除非用户明确要求直接覆盖重跑。
- 不打印 `config/local.json` 内容。

## 完成记录

- 新增 `_debug/failed-translations.tsv`，并在 `summary.json` 增加 `reviewReasonCounts`。
- `review-pages.txt` 现在会包含 `translation_failed` 与 `translation_failure_placeholder`。
- 新增 `--retry-review-pages` 参数；返工时强制覆盖输出，复用 preprocess cache，但不复用坏的 translated cache。
- 返工入口优先读取 `failed-translations.tsv`，其次读取 `review-pages.txt`，最后回退扫描旧版 `_debug/pages/*.json`，可直接识别历史输出。
- 返工后会合并旧 debug 记录，只替换重跑页，不会把整本 debug 索引缩成返工页。
- 只读扫描 `D:/github/translate-reader/翻译测试日漫/德川家康/01/out`，识别出 11 个需要重跑的源图，包含旧 debug 回退扫描发现的 `tokugawa#01_591.jpg`。
- 后续增强已补齐：`_debug/final-review-report.txt`、菜单最多 5 轮自动纠错、纠错时注入邻近页正常译文，以及新 debug 记录中的 `preprocessedPayload` / `PREP-DEBUG` 复用路径。
- 2026-05-09 补齐：返工入口会同时检查缺失输出页；后台入口 `run_batch_background.py` 也支持 `--retry-review-pages` 和 `--style-id`。
- 2026-05-11 补齐：缺失输出页扫描和输入扫描统一使用稳定自然排序，已覆盖 `cover.jpg + 00001.jpg`、`1/2/10/100`、补零数字页和大小写 `.JPG/.PNG/.WebP`。
- 2026-05-11 实跑修补：`东京大麻特区：被称为大麻王的男人/02` 中 `0_00014.jpg` 至 `0_00019.jpg` 因敏感词触发翻译失败占位符，已用人工译文重嵌；修补时同步更新最终 PNG、`_debug/pages/*.json`、`_debug/texts/*.translation.txt`、`review-pages.txt`、`failed-translations.tsv`、`summary.json` 和 stage cache，避免下次扫描继续重跑。
- 验证命令：
  - `.venv310/Scripts/python.exe -m pytest tests/test_cli_batch.py::test_debug_writer_flags_translation_failure_placeholders tests/test_cli_batch.py::test_run_batch_translation_retry_review_pages_only_processes_failed_translation_list tests/test_batch_translate_entry.py -q`，结果 `7 passed`
  - 2026-05-09 全量回归：`.venv310/Scripts/python.exe -m pytest -q`，结果 `169 passed`
  - 2026-05-11 全量回归：`.venv310/Scripts/python.exe -m pytest -q`，结果 `184 passed`
  - `.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py`
  - `start_cli.bat --help`
