# 卡姆依传 01 质量重做实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `翻译测试日漫/白土三平/卡姆依传/01` 建立“指定页重做 -> 历史坏页修复 -> 类型化嵌字优化 -> 真实页回归验证”的闭环。

**Architecture:** 先在 CLI 批处理层补“指定页名单重做”能力，解决历史坏页无法高效重跑的问题；再在翻译/嵌字流水线中加入 bubble 类型分流，先处理页眉噪声、标题框、横泡和长旁白这几类高价值问题；最后用真实坏页重跑结果和自动化测试共同验证。

**Tech Stack:** Python, pytest, PIL, 现有 `translate_manga_v2` CLI/pipeline/debug artifacts 体系。

---

### Task 1: 指定页重做入口

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/cli/service.py`
- Modify: `translate_manga_v2/batch_translate.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`

- [x] 增加 `run_batch_translation(..., target_page_names=None)`，支持只处理显式页名单。
- [x] 新增命令行参数，至少支持重复传入的 `--page-name`。
- [x] 页名单过滤后仍沿用现有 `retry_review_pages`、`overwrite_existing`、debug/cache 逻辑。
- [x] 先写失败测试，覆盖“仅重做指定页且不误处理其他页”。
- [x] 跑目标测试，确认先失败、后通过。

### Task 2: 历史坏页重做闭环

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/cli/service.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`

- [x] 让指定页重做路径可直接覆盖已有输出并重写 `_debug/pages/*.json`。
- [x] 保持相邻页上下文注入能力，避免单页重做后译文质量明显掉档。
- [x] 先对 `01_014 / 01_031 / 01_032 / 01_033` 做真实页重跑。
- [x] 记录重跑后的问题收敛情况，作为后续版式优化基线。

### Task 3: bubble 类型分流

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/quality_review.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_quality_review.py`

- [x] 新增 bubble 级启发式分类，至少区分页眉噪声、标题框/说明框、普通对白、长旁白。
- [x] 页眉噪声优先跳过或弱化，不再直接作为正文翻译并渲染。
- [x] 标题框/横泡使用更保守的横排参数，降低字号/收紧 padding。
- [x] 为长旁白预留单独样式或单独自动字号策略。
- [x] 先写失败测试，覆盖代表性分类和质量扫描命中。
- [x] 用真实页 `01_052 / 01_054 / 01_075 / 01_100 / 01_131` 回归验证。

### Task 4: 长旁白与真实页回归

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/quality_review.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_quality_review.py`

- [x] 对长旁白加入更小字号、更保守留白和更稳定的文本方向策略。
- [x] 扩展 quality review，使其更容易抓到页眉噪声、横框风险和长文本风险。
- [x] 用真实页 `01_164 / 01_198 / 01_329` 重跑验证观感。
- [x] 跑本次改动相关 pytest 与 `python -m compileall -q src`。
- [x] 当前任务不做提交，只输出修改结果、测试结果和仍存风险。
