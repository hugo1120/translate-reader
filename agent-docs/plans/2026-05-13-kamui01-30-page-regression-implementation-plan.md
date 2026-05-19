# 卡姆依传 01 三十页抽样自治回归实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `卡姆依传/01` 建立 30 页固定抽样回归集，反复重跑和修复，直到样本页在翻译质量、气泡分组和嵌字观感上达到停机标准。

**Architecture:** 先固化样本清单和判定标准，再对样本做基线重跑与问题归类；随后只针对高频问题做小范围修改，并以同一批 30 页反复验证，直到 `Fail = 0` 且 `Borderline <= 4`。整个闭环依赖现有 `--page-name` 指定页重做能力、`_debug/pages/*.json` 调试信息和人工视觉复核。

**Tech Stack:** Python 3.10, pytest, PIL, `translate_manga_v2` CLI/pipeline/debug artifacts, PowerShell.

---

### Task 1: 固化回归样本与验收标准

**Files:**
- Modify: `agent-docs/specs/2026-05-13-kamui01-30-page-regression-design.md`
- Modify: `agent-docs/plans/2026-05-13-kamui01-30-page-regression-implementation-plan.md`
- Modify: `agent-docs/index.md`

- [x] **Step 1: 确认 30 页固定样本清单**

样本必须固定为以下 30 页，后续所有回归都使用同一清单：

```text
Kamui#01_014.jpg
Kamui#01_031.jpg
Kamui#01_032.jpg
Kamui#01_033.jpg
Kamui#01_052.jpg
Kamui#01_054.jpg
Kamui#01_075.jpg
Kamui#01_093.jpg
Kamui#01_100.jpg
Kamui#01_131.jpg
Kamui#01_164.jpg
Kamui#01_198.jpg
Kamui#01_295.jpg
Kamui#01_329.jpg
Kamui#01_012.jpg
Kamui#01_027.jpg
Kamui#01_041.jpg
Kamui#01_083.jpg
Kamui#01_091.jpg
Kamui#01_106.jpg
Kamui#01_126.jpg
Kamui#01_128.jpg
Kamui#01_154.jpg
Kamui#01_174.jpg
Kamui#01_205.jpg
Kamui#01_234.jpg
Kamui#01_252.jpg
Kamui#01_279.jpg
Kamui#01_323.jpg
Kamui#01_352.jpg
```

- [x] **Step 2: 锁定停机标准**

本轮只有同时满足以下条件才允许宣布“样本过关”：

```text
1. 30 页样本 Fail = 0
2. 30 页样本 Borderline <= 4
3. 锚点页 014/031/032/033/052/054/075/093/100/131/164/198/295/329 不允许 Fail
4. 不再出现用户主诉级的“多个无关气泡被合并成一个翻译单元”
```

- [x] **Step 3: 在索引登记新设计与计划文档**

向 `agent-docs/index.md` 的“活跃文档”增加：

```markdown
- [2026-05-13 卡姆依传 01 三十页抽样自治回归设计](./specs/2026-05-13-kamui01-30-page-regression-design.md)
  - 适用场景：为 `卡姆依传/01` 建立固定 30 页样本、停机标准和问题分型。
- [2026-05-13 卡姆依传 01 三十页抽样自治回归实施计划](./plans/2026-05-13-kamui01-30-page-regression-implementation-plan.md)
  - 适用场景：执行 30 页抽样重跑、问题归类、定向修复和循环回归。
```

### Task 2: 跑出样本基线并记录问题簇

**Files:**
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/*.translated.png`
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/pages/*.json`
- Modify: `agent-docs/plans/2026-05-13-kamui01-30-page-regression-implementation-plan.md`

- [x] **Step 1: 用指定页名单重跑 30 页样本**

运行命令时逐个传 `--page-name`，并固定写回 `01/out`：

```powershell
& ".venv310/Scripts/python.exe" "translate_manga_v2/batch_translate.py" `
  --input "D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01" `
  --output "D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01/out" `
  --style-id "auto" `
  --page-name "Kamui#01_014.jpg" `
  --page-name "Kamui#01_031.jpg" `
  --page-name "Kamui#01_032.jpg" `
  --page-name "Kamui#01_033.jpg" `
  --page-name "Kamui#01_052.jpg" `
  --page-name "Kamui#01_054.jpg" `
  --page-name "Kamui#01_075.jpg" `
  --page-name "Kamui#01_093.jpg" `
  --page-name "Kamui#01_100.jpg" `
  --page-name "Kamui#01_131.jpg" `
  --page-name "Kamui#01_164.jpg" `
  --page-name "Kamui#01_198.jpg" `
  --page-name "Kamui#01_295.jpg" `
  --page-name "Kamui#01_329.jpg" `
  --page-name "Kamui#01_012.jpg" `
  --page-name "Kamui#01_027.jpg" `
  --page-name "Kamui#01_041.jpg" `
  --page-name "Kamui#01_083.jpg" `
  --page-name "Kamui#01_091.jpg" `
  --page-name "Kamui#01_106.jpg" `
  --page-name "Kamui#01_126.jpg" `
  --page-name "Kamui#01_128.jpg" `
  --page-name "Kamui#01_154.jpg" `
  --page-name "Kamui#01_174.jpg" `
  --page-name "Kamui#01_205.jpg" `
  --page-name "Kamui#01_234.jpg" `
  --page-name "Kamui#01_252.jpg" `
  --page-name "Kamui#01_279.jpg" `
  --page-name "Kamui#01_323.jpg" `
  --page-name "Kamui#01_352.jpg"
```

- [x] **Step 2: 对 30 页做视觉分级**

逐页检查输出 PNG，并按以下格式记录到计划文档的执行记录区：

```markdown
- Kamui#01_031: Fail | 气泡误合并 + 译文挤爆
- Kamui#01_052: Borderline | 标题框观感一般，但可读
- Kamui#01_198: Borderline | 长说明块已有分段，但正文感不足
```

- [x] **Step 3: 从 debug JSON 提取原因线索**

重点记录以下字段，帮助决定下一轮修复点：

```text
bubbles[].role
bubbles[].direction
bubbles[].source
bubbles[].text
bubbles[].coords
review.needsReview
review.reasons
```

- [x] **Step 4: 汇总高频问题簇并排序**

按频次输出一个问题榜单，格式必须类似：

```markdown
1. 长说明块段落感不足：7 页
2. 气泡误合并：5 页
3. 页眉/边注噪声正文化：3 页
4. OCR 脏串导致译文别扭：3 页
```

### Task 3: 针对最高频问题做最小代码修复

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/quality_review.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`
- Test: `translate_manga_v2/tests/test_quality_review.py`

- [x] **Step 1: 为问题簇先写或补测试**

测试必须直接对应样本里出现的高频坏型，优先覆盖：

```python
def test_build_bubbles_marks_dense_long_narration_as_horizontal_block():
    ...

def test_expand_translation_payload_reflows_long_narration_with_visible_breaks():
    ...

def test_quality_review_flags_header_noise_or_untranslated_source():
    ...
```

- [x] **Step 2: 只实现 1-2 类最高频修复**

本轮允许的优先改动方向：

```text
- bubble 角色判断和噪声抑制
- 长说明块的分段、对齐、行宽和留白
- 横泡/竖泡的样式路由
- OCR 脏串的译后过滤或 review 提示
```

- [x] **Step 3: 运行局部 pytest 验证**

```powershell
& ".venv310/Scripts/python.exe" -m pytest `
  "translate_manga_v2/tests/test_cli_batch.py" `
  "translate_manga_v2/tests/test_pipeline_service.py" `
  "translate_manga_v2/tests/test_quality_review.py" -q
```

### Task 4: 用同一批 30 页重复回归直到停机

**Files:**
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/*.translated.png`
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/pages/*.json`
- Modify: `agent-docs/plans/2026-05-13-kamui01-30-page-regression-implementation-plan.md`

- [x] **Step 1: 用同一命令重跑 30 页**

复用 Task 2 的 `batch_translate.py` 命令，不允许变更样本清单。

- [x] **Step 2: 重新统计 Fail / Borderline / Pass**

每一轮都要在计划文档里追加一段结果摘要：

```markdown
## Round N
- Fail: X
- Borderline: Y
- Pass: Z
- 新解决问题：
- 新暴露问题：
```

- [x] **Step 3: 判断是否继续**

继续迭代的条件：

```text
- 仍有 Fail
- 或 Borderline > 4
- 或锚点页存在主诉级问题
```

停止迭代的条件：

```text
- Fail = 0
- Borderline <= 4
- 锚点页全部过关
```

### Task 5: 独立 Review 与最终验证

**Files:**
- Read: `translate_manga_v2/src/translate_manga/cli/service.py`
- Read: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Read: `translate_manga_v2/src/translate_manga/cli/quality_review.py`
- Test: `translate_manga_v2/tests/test_batch_translate_entry.py`
- Test: `translate_manga_v2/tests/test_cli_batch.py`
- Test: `translate_manga_v2/tests/test_pipeline_service.py`
- Test: `translate_manga_v2/tests/test_quality_review.py`

- [x] **Step 1: 做独立代码 Review**

Review 重点必须覆盖：

```text
- 是否引入新的误分类
- 是否把非长旁白页误伤成说明块
- 是否让原本正常的横泡/竖泡观感回退
- 是否存在 debug 信息和最终渲染不一致
```

- [x] **Step 2: 跑相关回归测试**

```powershell
& ".venv310/Scripts/python.exe" -m pytest `
  "translate_manga_v2/tests/test_batch_translate_entry.py" `
  "translate_manga_v2/tests/test_cli_batch.py" `
  "translate_manga_v2/tests/test_pipeline_service.py" `
  "translate_manga_v2/tests/test_quality_review.py" -q
```

- [x] **Step 3: 跑编译检查**

```powershell
& ".venv310/Scripts/python.exe" -m compileall -q "translate_manga_v2/src"
```

- [x] **Step 4: 输出最终结果**

最终汇报必须包含：

```text
- 30 页样本最终分级结果
- 解决了哪些高频问题
- 仍然剩下哪些边界风险
- 是否建议放大到整本 01
```

## 执行记录

### Round 0 Baseline

- Fail: 多个锚点页存在主诉级问题，重点包括 `014/031/032/033/093/154/352`。
- Borderline: 长说明块页集中在 `164/198/295/329`，可读但正文感不足。
- Pass: 未稳定统计。
- 最高频问题簇：
  1. 竖排/横排样式路由不稳：横排气泡走竖排样式，竖排对白又被硬压成横排。
  2. 长说明块渲染区域过大：`093` 曾覆盖城堡图，`198/295/329` 密度高。
  3. 翻译残留与术语错误：`352` 的 `マスどり` 曾输出 `Masudori`。
  4. 低置信短假名噪声：`154` 曾因 `ッ` 触发失败占位。
  5. 通篇质检漏报：译文假名残留没有被启发式 quality review 抓出。

### Round 6 Final

- 实际命令：固定 30 页样本，`--style-id auto`，写回 `D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01/out`。
- 样式规则：原版竖排文字走样式2方向，原版横排文字走样式1方向。
- 批处理结果：`DONE total=30 ok=30 skip=0 fail=0 elapsed=03:32`。
- 最终硬扫描：30 页 debug JSON 中无 `needsReview`、无失败占位、无日文假名残留、无 `Masudori/Kamui` 这类罗马字残留、无已知坏译 `阿音/拉斯尔/拉斯鲁`。
- Fail: 0
- Borderline: 4，主要是 `164/198/295/329` 长说明块仍偏密，但没有覆盖画面、挤爆或不可读。
- Pass: 26
- 锚点页：`014/031/032/033/052/054/075/093/100/131/164/198/295/329` 无 Fail。
- 新解决问题：
  - `01/manga_context.md` 为 UTF-16LE BOM 时可正常读取，不再静默丢上下文。
  - `093` L 型长旁白渲染区域收窄，不再压到城堡图。
  - `154` 低置信短假名噪声被过滤，页面不再进入失败占位。
  - `352` 的 `マスどり` 固定为“量斗”，`アアッミ` 固定为“啊啊”，不再出现 `Masudori/阿音`。
  - `054/131` 的常见拟声词残留已规范化为“嗖 / 汪 / 嗷”。
  - 通篇质检启发式会标记译文中的日文假名残留为 `quality_untranslated_source`。
- 新暴露问题：
  - `054` 仍有 `GL` 这类疑似画面字母噪声，当前不作为硬失败。
  - 长说明块的审美上限仍受原图大段竖排说明和 OCR 质量限制，后续若扩到整本 `01`，应继续抽查长旁白页。
- 代码 Review：当前环境无 reviewer subagent，已按 diff 人工复核拟声词兜底、假名残留质检、缓存重跑和样式路由路径，未发现高优先级问题。
- 验证：
  - `python -m pytest translate_manga_v2/tests/test_batch_translate_entry.py translate_manga_v2/tests/test_cli_menu.py translate_manga_v2/tests/test_cli_service_styles.py translate_manga_v2/tests/test_cli_batch.py translate_manga_v2/tests/test_pipeline_service.py translate_manga_v2/tests/test_quality_review.py translate_manga_v2/tests/test_manga_context.py -q`：`146 passed`
  - `python -m compileall -q translate_manga_v2/src`：通过
  - 最新 contact sheet：`D:/github/translate-reader/翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-auto-30-contact-sheet-round6-final.jpg`
