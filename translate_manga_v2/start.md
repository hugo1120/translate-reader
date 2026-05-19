# 启动说明

## 交互菜单

直接运行：

```powershell
./start_cli.bat
```

无参数时会进入交互式控制台菜单，支持：

- `继续上次任务`：复用上一次保存的一个或多个输入目录，继续跑未完成内容
- `新建任务`：重新输入一个或多个漫画目录，并覆盖上次任务记忆
- `扫描并纠正错误`：扫描已有 `_debug` 记录和缺失输出图；可选择只修复硬错误，或追加通篇译文质检后只重跑被标记的问题页
- `退出`：退出菜单

菜单每次翻译完成后都会返回主菜单，不会直接退出。

### 任务输入

新建任务和扫描纠错都支持同一种输入方式：

- 一行一个输入目录
- 直接回车结束输入
- 可直接粘贴多行；如果出现 `...\10D:\...\01` 这种路径连在一起的情况，会按 Windows 盘符自动拆开
- 然后统一选择一次样式

每本漫画的输出目录固定为：

```text
<输入目录>/out
```

例如：

```text
D:/book-a/item/image -> D:/book-a/item/image/out
D:/book-b/item/image -> D:/book-b/item/image/out
```

### 图片扫描和排序

- 只扫描输入目录下的直接图片文件，不递归子目录
- 支持 `.jpg`、`.jpeg`、`.png`、`.webp`，扩展名大小写不敏感
- 其它文件会被忽略
- 处理顺序使用自然排序：`1.jpg, 2.jpg, 10.jpg, 100.jpg`
- 同一个页号不同补零时短文件名优先：`1.jpg, 01.jpg, 001.jpg`
- `cover.jpg` 这类非数字文件会稳定排在纯数字页前

完整翻译默认跳过已有输出，适合中断后继续。完整翻译结束后会自动扫描 `_debug` 和缺失输出图，最多重试 5 轮需要复查/失败/未生成的页；纠错重跑会覆盖这些失败页和缺输出页。

纠错重跑会读取旧 `_debug/pages/*.json` 里前后页的正常译文作为翻译上下文；新生成的 debug 记录还会保存可复用预处理摘要，后续纠错会优先复用它，减少重复 OCR/PREP。

选择 `扫描并纠正错误` 后会再选择扫描模式：

- `只修复硬错误`：不额外调用模型，只处理失败、复查标记和缺失输出图
- `硬错误+通篇译文质检`：先修复硬错误；即使仍有少量硬错误未清完，也会继续让模型审核该书已有译文，生成 `_debug/quality-review.tsv`，再覆盖重跑这些软质量问题页。硬错误页仍会保留在 `failed-translations.tsv` / `review-pages.txt`

跨程序重启会记住上一次配置，保存在：

```text
config/session.json
```

`config/local.json` 用于本机路径和 API key，已被 `.gitignore` 忽略；公开同步只保留无密钥模板 `config/local.example.json`。

菜单 `3. 扫描并纠正错误` 支持单独 API 配置：

```json
{
  "scan_fix_translation": {
    "model": "your-scan-fix-model",
    "base_url": "https://your-scan-fix-base-url/v1",
    "api_key": "your-scan-fix-api-key"
  }
}
```

它只影响扫描纠错、通篇译文质检和质检后覆盖重跑；正常新建/继续翻译仍使用 `translation`。留空字段会自动继承 `translation`。

`多模态AI辅助` 样式使用独立 API 配置：

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

`Auto` 不调用多模态 AI；只有选择 `M` / `m` / `multimodal` / `style_mm` 时才会启用多模态版面辅助。若 `model`、`base_url` 或 `api_key` 配置不完整，或接口失败，该页会降级为普通 Auto 版式，并在 `_debug/pages/*.json` 的 `multimodalLayout` 中记录原因。`cache_enabled=false` 可在重跑时强制刷新多模态版面分析。

## 纯命令行

有参数时，`start_cli.bat` 会直接透传给 `batch_translate.py`：

```powershell
./start_cli.bat --input "D:/path/to/input" --output "D:/path/to/output" --style-id 2
```

也可以直接运行 Python 入口：

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py --input "D:/path/to/input" --output "D:/path/to/output"
```

支持位置参数：

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py "D:/path/to/input" "D:/path/to/output"
```

后台跑批并写实时日志：

```powershell
./.venv310/Scripts/python.exe ./run_batch_background.py "D:/path/to/input" "D:/path/to/input/out" --log-path "./logs/batch-live.log" --style-id 3
./.venv310/Scripts/python.exe ./run_batch_background.py "D:/path/to/input" "D:/path/to/input/out" --style-id auto --retry-quality-review-pages
```

后台入口支持 `--layout-mode`、`--style-id`、`--overwrite-existing`、`--retry-review-pages`、`--retry-quality-review-pages`，参数含义和 `batch_translate.py` 保持一致。

## 风格说明

- `Style 1 = horizontal JP`：横排黑体，左到右，日语 OCR/提示词
- `Style 2 = vertical JP`：竖排圆体，右到左，日语 OCR/提示词
- `Auto = auto JP`：原文横排气泡按 Style 1 渲染，原文竖排气泡按 Style 2 渲染，日语 OCR/提示词
- `Style 3 = horizontal EN`：横排圆体，左到右，PaddleOCR English ONNX + 英语提示词
- `多模态AI辅助 = auto JP + vision layout assist`：现有 OCR/翻译/擦字链路不变，只额外用多模态 AI 判断标题、页码、说明块和横竖排提示

命令行推荐用 `--style-id 1|2|auto|3|m`。旧参数 `--layout-mode horizontal|vertical|auto` 仍保留兼容，未显式传 `--style-id` 时会按 `horizontal -> Style 1`、`vertical -> Style 2`、`auto -> Auto` 映射。

## 覆盖策略

- 完整翻译/继续任务：默认跳过已有输出
- 扫描并纠正错误：硬错误模式只覆盖 `_debug` 标记需要复查/失败的页，以及源图存在但输出图缺失的页；通篇质检模式还会覆盖 `_debug/quality-review.tsv` 标记的软质量问题页

## 性能配置

性能相关配置在 `config/defaults.json` / `config/local.json` 的 `pipeline` 下：

- `translation_quality`: `high` / `balanced` / `fast`，默认 `high`
- `debug_flush_interval`: debug 汇总文件每多少页刷新一次，默认 `25`
- `color_fast_mode`: 高置信浅色气泡跳过昂贵背景复杂度采样，默认 `true`

建议：

- 正式精翻：`high`
- 大批量预览：`balanced`
- 快速扫图或英文短页：`fast`

## 调试记录

开启 `_debug` 时，`_debug/summary.json` 会额外记录本次运行策略：

- `inputDir`
- `outputDir`
- `layoutMode`
- `styleName`
- `styleId`
- `sourceLanguage`
- `readingOrder`
- `promptProfile`
- `translationQuality`
- `overwriteExisting`
- `launchMode`
- `translationModel`
- `ocrEngine`
- `secondaryOcrEngine`

错误排查重点看：

- `_debug/review-pages.txt`：需要复查的页名和原因
- `_debug/failed-translations.tsv`：失败页 TSV 清单，菜单纠错和 `--retry-review-pages` 会优先使用它
- `_debug/quality-review.tsv`：通篇译文质检发现的误译、残留原文、称呼不一致、中文不通顺等软质量问题页
- `_debug/final-review-report.txt`：最终复查报告，包含阶段耗时汇总、残留问题页和页面耗时 Top 10

`quality-review.tsv` 由菜单 3 的通篇质检模式生成，也可以用命令行 `--retry-quality-review-pages` 消费；该参数会自动启用 `--retry-review-pages`。对应页成功进入重跑后会自动清理。若重跑仍失败，新的硬错误会继续落到 `failed-translations.tsv` / `review-pages.txt`。

能力边界：

- 硬错误扫描不做语义判断，只能发现失败占位、缺译文、缺输出等确定性问题。
- 通篇质检会尝试发现明显误译、残留原文、称呼不一致、中文不通顺、OCR 噪声残留、横竖排不匹配等，但不保证覆盖所有翻译错误。
- 通篇质检依据 `_debug/pages/*.json` 的 OCR 原文和译文，不直接判断最终 PNG 的嵌字审美。

如果同一页多轮后仍是 `translation_failed` / `translation_failure_placeholder`，通常是翻译 API 对内容拒翻、超时或返回失败占位符。人工修补时不能只覆盖最终 PNG；需要同步更新该页 `_debug/pages/*.json`、`_debug/texts/*.translation.txt`、整本 `review-pages.txt`、`failed-translations.tsv`、`summary.json` 和隐藏 stage cache，否则后续扫描会继续把它当失败页。

## 书系 Profile

程序会按输入目录自动识别书系和卷号：

- `D:/漫画/德川家康/01` -> 书系 `德川家康`，卷 `01`
- `D:/漫画/德川家康/02` -> 继续复用书系 `德川家康`
- `D:/漫画/卡姆依传` -> 书系 `卡姆依传`

书系级提示词和术语文件保存在：

```text
<书系目录>/_translation_profile/
```

常用文件：

- `series_profile.md`：给 AI 看的书系提示词，会自动生成
- `glossary.tsv`：固定术语、人名、地名，可手工维护
- `characters.tsv`：人物称呼和关系，可手工维护
- `translation_memory.json`：后续用于跨卷记忆

翻译时优先使用当前卷目录的 `manga_context.md`；没有时使用书系 profile。后续卷会自动继承同一套书系提示词。
