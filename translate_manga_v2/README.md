# translate_manga_v2

纯命令行漫画批量翻译器。

当前定位只有一条主链路:

`OCR -> 翻译(draft/contextual/final, 可配置质量档) -> 擦字 -> 写字 -> 输出译图`

不再包含 Web API、浏览器界面或本地阅读器壳。

## 运行方式

交互式菜单入口：

```powershell
./start_cli.bat
```

无参数时进入交互菜单；有参数时直接透传给 `batch_translate.py`。

交互菜单现在只有一个主入口，内部提供四个选项：

- `继续上次任务`：复用上次保存的一个或多个输入目录，继续跑未完成内容
- `新建任务`：重新输入一个或多个漫画目录，覆盖上次任务记忆
- `扫描并纠正错误`：扫描已有 `_debug` 记录和缺失输出图；可选择只修复硬错误，或追加一次通篇译文质检并只覆盖重跑被标记的页
- `退出`

新建任务和扫描任务都支持批量输入：

- 一行一个输入目录
- 直接回车结束输入
- 整批共用一次样式
- 每本输出目录自动写到对应输入目录下的 `out`
- 只扫描输入目录下的直接图片文件，不递归子目录
- 支持 `.jpg`、`.jpeg`、`.png`、`.webp`，扩展名大小写不敏感
- 图片按自然顺序处理，例如 `1, 2, 3, 10, 11, 100`；同页号不同补零时按短文件名优先，`cover.jpg` 稳定排在纯数字页前
- 默认跳过已有输出，用于中断后继续；纠错时会自动覆盖失败页和未生成输出图的页
- 完整翻译后会自动扫描并最多重试 5 轮失败页/缺输出页
- 纠错重跑会读取旧 `_debug` 中前后页的正常译文作为上下文，提升称呼和语气一致性
- `扫描并纠正错误` 的通篇质检模式会生成 `_debug/quality-review.tsv`，只把明显误译、残留原文、称呼不一致、中文不通顺等问题页加入覆盖重跑
- 新生成的 debug 记录会保存可复用预处理摘要，后续纠错可优先跳过重复 OCR/PREP
- 批量粘贴路径时会自动去重，并尝试拆开 `...\10D:\...\01` 这种连在一起的 Windows 路径

优先使用本地虚拟环境:

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py --input "D:/path/to/input" --output "D:/path/to/output"
```

也支持位置参数:

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py "D:/path/to/input" "D:/path/to/output"
```

如果 `config/local.json` 已配置 `paths.input_dir` 和 `paths.output_dir`，可以直接运行:

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py
```

常用参数:

- `--style-id 1|2|auto|3|m`
- `--layout-mode horizontal|vertical|auto`
- `--overwrite-existing`
- `--retry-review-pages`
- `--retry-quality-review-pages`
- `--workspace-root`
- `--cache-root`
- `--model`
- `--base-url`
- `--api-key`

风格映射：

- `Style 1 = horizontal JP`：横排黑体，左到右，日语 OCR/提示词
- `Style 2 = vertical JP`：竖排圆体，右到左，日语 OCR/提示词
- `Auto = auto JP`：原文横排气泡按 Style 1 渲染，原文竖排气泡按 Style 2 渲染，日语 OCR/提示词
- `Style 3 = horizontal EN`：横排圆体，左到右，PaddleOCR English ONNX + 英语提示词
- `多模态AI辅助 = auto JP + vision layout assist`：保留现有 OCR/翻译/擦字链路，只额外用多模态 AI 判断标题、页码、说明块、横竖排和可用版面提示

命令行推荐用 `--style-id 1|2|auto|3|m`。旧参数 `--layout-mode` 仍兼容：`horizontal -> Style 1`，`vertical -> Style 2`，`auto -> Auto`。英文漫画建议直接选 `--style-id 3`。

`Auto` 是稳定基线，不调用多模态 AI。需要多模态版面理解时，显式选择 `M` / `m` / `multimodal` / `style_mm`。

更完整的启动说明见 [start.md](./start.md)。

提示词与书系 profile 说明见：

- [docs/translation_prompt_scheme.md](./docs/translation_prompt_scheme.md)
- [docs/manga_context_prompt_template.md](./docs/manga_context_prompt_template.md)

后台跑批并写实时日志:

```powershell
./.venv310/Scripts/python.exe ./run_batch_background.py --log-path "./logs/batch-live.log"
./.venv310/Scripts/python.exe ./run_batch_background.py "D:/path/to/book" "D:/path/to/book/out" --style-id auto --retry-quality-review-pages
```

## 配置优先级

`config/defaults.json < config/local.json < TRANSLATE_MANGA_CLI_* 环境变量 < 命令行参数`

`config/local.json` 用于本机路径和 API key，已被 `.gitignore` 忽略；公开同步只保留无密钥模板 `config/local.example.json`。

菜单 `3. 扫描并纠正错误` 可以单独使用另一套 OpenAI-compatible API，在 `config/local.json` 写：

```json
{
  "scan_fix_translation": {
    "model": "your-scan-fix-model",
    "base_url": "https://your-scan-fix-base-url/v1",
    "api_key": "your-scan-fix-api-key"
  }
}
```

该配置只影响菜单 3 的硬错误重翻、通篇译文质检和质检后重翻；菜单 1/2 的正常翻译仍使用 `translation`。如果 `scan_fix_translation` 某个字段留空，会自动继承 `translation` 中的对应字段。

多模态AI辅助样式使用独立配置：

```json
{
  "multimodal_layout": {
    "enabled": false,
    "model": "mimo-v2.5",
    "base_url": "https://your-vision-openai-compatible-base-url/v1",
    "api_key": "your-vision-api-key",
    "request_timeout_seconds": 90.0,
    "max_edge": 1280,
    "cache_enabled": true
  }
}
```

选择 `M/多模态AI辅助` 时会强制启用这组配置；如果 `model`、`base_url` 或 `api_key` 未配置，页面会降级为普通 Auto 版式并在 debug 里记录 `multimodalLayout.status=skipped`。`cache_enabled=true` 时会复用预处理缓存里的多模态提示，设为 `false` 可在重跑时重新请求版面分析。接口错误同样只影响该页的多模态提示，不影响 OCR、翻译和输出。

## 性能配置

性能相关配置在 `config/defaults.json` / `config/local.json` 的 `pipeline` 下：

- `translation_quality`: `high` / `balanced` / `fast`，默认 `high`
- `debug_flush_interval`: debug 汇总文件每多少页刷新一次，默认 `25`
- `color_fast_mode`: 高置信浅色气泡跳过昂贵背景复杂度采样，默认 `true`

建议：

- 正式精翻：`high`
- 大批量预览：`balanced`
- 快速扫图或英文短页：`fast`

## 输出结构

- `*.translated.png`: 最终译图
- `_debug/pages/*.json`: 每页调试记录
- `_debug/texts/*.ocr.txt`: OCR 文本
- `_debug/texts/*.translation.txt`: 最终译文
- `_debug/summary.json`: 本次跑批汇总
- `_debug/review-pages.txt`: 需要复查的页
- `_debug/failed-translations.tsv`: 失败/疑似失败页清单，可用于纠错重跑
- `_debug/quality-review.tsv`: 通篇译文质检发现的软质量问题页清单，菜单 3 的质检模式会用它只重跑这些页
- `_debug/final-review-report.txt`: 本轮最终复查报告，列出阶段耗时汇总、残留问题页和耗时排行

## 纠错与人工修补

菜单 `扫描并纠正错误` 有两个模式：

- `只修复硬错误`：只处理失败占位符、需要复查记录和缺失输出图，不额外调用翻译模型做整本质检
- `硬错误+通篇译文质检`：先最多 5 轮修复硬错误；即使仍有少量硬错误未清完，也会继续让模型通读该书 `_debug/pages/*.json` 中的原文/译文，写入 `_debug/quality-review.tsv`，然后覆盖重跑这些软质量问题页。硬错误页仍会保留在 `failed-translations.tsv` / `review-pages.txt`

硬错误扫描和命令行 `--retry-review-pages` 会读取：

- `_debug/failed-translations.tsv`
- `_debug/review-pages.txt`
- `_debug/pages/*.json`
- 源图存在但 `*.translated.png` 缺失的页面

通篇质检重跑额外读取 `_debug/quality-review.tsv`。命令行可用 `--retry-quality-review-pages` 直接消费已有质检 TSV；该参数会自动启用 `--retry-review-pages`。质检 TSV 在对应问题页成功进入重跑后会被清理；如果重跑仍失败，新的硬错误会继续留在 `failed-translations.tsv` / `review-pages.txt` 里。

能力边界：

- `--retry-review-pages` 和硬错误扫描不做语义判断，不能发现普通误译。
- 如果 `_debug/pages/*.json` 或 `_debug/texts/*.translation.txt` 里的译文包含失败占位，会按硬错误加入重跑；识别范围包含“翻译失败 / 无法翻译 / 翻译出错 / 译文生成失败 / translation_failed / translation error / failed to translate”等短错误提示和常见接口错误提示。但不会对最终 PNG 重新 OCR 来判断图上是否写着这些字。
- 通篇质检会用模型和启发式检查明显误译、残留原文、称呼不一致、中文不通顺、OCR 噪声残留、横竖排不匹配等，但不能保证发现所有翻译错误。
- 通篇质检依据 `_debug/pages/*.json` 的 OCR 原文和译文，不直接看最终 PNG；嵌字审美和遮挡问题仍需要抽样看图。

同一页多轮后仍保留 `translation_failed` / `translation_failure_placeholder` 时，通常是翻译 API 对内容拒翻、超时或返回失败占位符。人工修补不能只覆盖最终 PNG；必须同步修正 `_debug/pages/*.json`、`_debug/texts/*.translation.txt`、`review-pages.txt`、`failed-translations.tsv`、`summary.json` 和隐藏 stage cache。否则后续扫描会继续把旧失败记录当成待重跑页面。

## 书系 Profile

当输入目录最后一段是 `01` / `02` / `10` 这类卷号时，程序会把上一级目录识别为书系名：

```text
D:/漫画/德川家康/01 -> 书系: 德川家康, 卷: 01
D:/漫画/德川家康/02 -> 书系: 德川家康, 卷: 02
```

当最后一段不是卷号时，最后一段就是书系名：

```text
D:/漫画/卡姆依传 -> 书系: 卡姆依传
```

自动生成或复用的书系提示词放在书系根目录：

```text
德川家康/
  _translation_profile/
    series_profile.md
    glossary.tsv
    characters.tsv
    translation_memory.json
```

翻译时优先使用当前卷目录下的 `manga_context.md`；如果没有，就复用书系 `_translation_profile/series_profile.md`。你可以手工修改 `series_profile.md`、`glossary.tsv`、`characters.tsv`，后续卷会自动继承。

## 依赖

- `Saber-Translator`: 本地放在 `vendor/Saber-Translator`，或在 `config/local.json` 的 `paths.saber_root` 指向已有目录；该 vendor 目录体积较大，默认不随 GitHub 同步
- `Pillow`
- `OpenAI-compatible` 翻译接口
