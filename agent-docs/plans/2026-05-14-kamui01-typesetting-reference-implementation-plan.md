# 卡姆依传 01 嵌字参考汉化对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `卡姆依传/01/out` 的嵌字重点从“翻译可用”推进到“长说明块接近参考汉化的横排正文观感”。

**Architecture:** 普通对白继续遵循 `auto` 规则：原横排走样式1，原竖排走样式2。大面积、长文本、说明性质的叙述块单独识别为 editorial prose block，即使原日文为竖排，也改用横排正文块、小字号、左对齐和更舒展的行距，参考 `村人C汉化 Vol.01` 的处理。

**Tech Stack:** Python 3.10, pytest, PIL, `translate_manga_v2` pipeline/CLI, Saber debug artifacts.

---

### Task 1: 锁定参考差距

**Files:**
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-ref-vs-ours-keypages.jpg`
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/pages/Kamui#01_198.json`
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/pages/Kamui#01_295.json`
- Read: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/pages/Kamui#01_329.json`

- [x] **Step 1: 记录主要差距**

参考汉化对 `031/033/198/295/329` 这类长说明块的处理是横排正文块，不沿用日文原竖排列宽。当前输出仍把中文压进竖排样式2，导致密度过高、版面机械。

- [x] **Step 2: 确定本轮推荐方案**

方案 A：只对 editorial long narration 强制横排正文。优点是风险小，普通对白和窄竖排框不被误伤；缺点是仍依赖启发式判断。

方案 B：所有长说明块全部横排。优点是结果接近参考；缺点是可能破坏窄竖排旁白和局部说明框。

方案 C：做图像级空白区搜索再重排。优点上限最高；缺点改动大，需要更多视觉检测和真实页验证。

本轮先执行方案 A；如果真实页仍密，再局部加入方案 C 的空白扩区。

### Task 2: TDD 固化排版策略

**Files:**
- Modify: `translate_manga_v2/tests/test_pipeline_service.py`
- Modify: `translate_manga_v2/tests/test_cli_batch.py`

- [x] **Step 1: 写失败测试**

新增测试覆盖 `198/295/329` 形态：宽大、长文本、原 OCR 竖排占多数时，profile 应输出 `directionOverride = horizontal`、`textAlignOverride = start`、横排正文字号参数。

- [x] **Step 2: 验证测试先失败**

运行：

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_batch.py" -q
```

### Task 3: 修改长说明块嵌字策略

**Files:**
- Modify: `translate_manga_v2/src/translate_manga/core/pipeline/service.py`
- Modify: `translate_manga_v2/src/translate_manga/cli/service.py`

- [x] **Step 1: 增加 editorial prose 判定**

判定依据：长文本、面积大或宽度大、行数多、非窄竖排框。命中后使用横排正文配置。

- [x] **Step 2: 调整横排正文参数**

长说明块使用更小 `max_size`、较高有效内边距和左对齐，使渲染结果接近参考汉化的“正文段落”。

- [x] **Step 3: 保留窄竖排例外**

高瘦、窄列、说明框空间不足的长文本仍允许样式2，避免把用户认可的原竖排对白改坏。

### Task 4: 真实页验证

**Files:**
- Output: `翻译测试日漫/白土三平/卡姆依传/01/out/*.translated.png`
- Output: `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/*.jpg`

- [x] **Step 1: 重跑重点页**

重点页：

```text
Kamui#01_031.jpg
Kamui#01_033.jpg
Kamui#01_093.jpg
Kamui#01_164.jpg
Kamui#01_198.jpg
Kamui#01_295.jpg
Kamui#01_329.jpg
Kamui#01_352.jpg
```

- [x] **Step 2: 生成原图/参考/新输出对照图**

对照图必须能看出长说明块是否从竖排密集块变为横排正文块，且不明显压图、不遮挡关键漫画内容。

### Task 5: 回归与 Review

**Files:**
- Run: pytest
- Run: compileall
- Review: changed diff

- [x] **Step 1: 跑相关测试**

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m pytest "D:/github/translate-reader/translate_manga_v2/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_batch.py" "D:/github/translate-reader/translate_manga_v2/tests/test_cli_service_styles.py" -q
```

- [x] **Step 2: 跑编译检查**

```powershell
& "D:/github/translate-reader/translate_manga_v2/.venv310/Scripts/python.exe" -m compileall -q "D:/github/translate-reader/translate_manga_v2/src"
```

- [x] **Step 3: 代码 Review**

检查是否误伤普通对白、窄竖排说明、L 型说明块裁剪，以及是否新增不可控大范围改动。

---

### 执行记录

- `2026-05-14`：新增 editorial prose 判定。`031/033/198/295/329` 这类宽说明块转为横排正文；`093/164` 仍保留竖排，避免压图和误伤参考汉化也保留竖排的页面。
- `2026-05-14`：修复缓存译文重渲染路径。已有 `stage=translated` 的缓存文本在重新渲染前会按当前 profile 重新断行，避免单行长文本把自动字号压小。
- `2026-05-14`：重点页重跑成功：`031/033/093/164/198/295/329/352` 共 8 页，`ok=8 fail=0`。
- `2026-05-14`：全书 37 个长说明页已重跑刷新，`ok=37 fail=0`。额外修正 `356` 图表/清单页，避免被普通正文块字号挤爆。
- 新对照图：
  - `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-typesetting-block-crops-round2.jpg`
  - `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-typesetting-long-block-crops-round4.jpg`
  - `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-typesetting-ref-vs-ours-round5-final.jpg`
  - `翻译测试日漫/白土三平/卡姆依传/01/out/_debug/kamui01-long-narration-37-ours-contact-sheet-final.jpg`
- 已验证：
  - `pytest translate_manga_v2/tests/test_pipeline_service.py translate_manga_v2/tests/test_cli_batch.py -q`：`94 passed`
  - `pytest translate_manga_v2/tests/test_cli_service_styles.py translate_manga_v2/tests/test_quality_review.py -q`：`22 passed`
  - `pytest translate_manga_v2/tests -q`：`242 passed`
  - `compileall -q translate_manga_v2/src`：通过
