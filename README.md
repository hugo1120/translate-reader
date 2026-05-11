# Translate Manga V2

本仓库当前活跃项目是 `translate_manga_v2`：一个本地命令行漫画汉化工具，用于把日漫、英漫图片目录批量翻译成中文译图。

后续开发和 GitHub 同步只以 `translate_manga_v2/` 为准。旧 `translate_manga_cli/` 已删除；`translate_manga_v1/` 仅作本机备用旧版，已被 `.gitignore` 整目录忽略。

## 核心能力

- 批量翻译单本或多本漫画目录，输出到每本目录下的 `out`。
- 支持中断后继续，默认跳过已生成的译图。
- 支持批后自动复查，最多重试失败页、疑似坏页和缺失输出页。
- 支持菜单入口和命令行入口。
- 支持日漫横排、日漫竖排、英漫横排三种样式。
- 支持书系 Profile：同一作品后续卷可复用背景、人名、术语和称呼。
- 输出 `_debug` 调试记录，方便定位 OCR、翻译、渲染和失败页。
- 本地私有 API 配置不进 Git，不进 Release 包。

主链路：

```text
图片目录 -> OCR/检测 -> 翻译 -> 擦字 -> 写字 -> 输出译图 -> 复查/纠错
```

## 技术栈

- Python 3.10+
- Windows batch 入口：`start_cli.bat`、`setup_windows.bat`
- CLI 应用包：`translate_manga_v2/src/translate_manga`
- 图像处理：Pillow
- 翻译接口：OpenAI-compatible API
- OCR / 检测 / 擦字 / 渲染底座：`vendor/Saber-Translator`
- 日漫 OCR：48px OCR + manga_ocr fallback
- 英漫 OCR：PaddleOCR English ONNX
- 测试：pytest

## 目录说明

```text
translate-reader/
  translate_manga_v2/       # 当前主项目，开发和同步目标
  Release/                  # 本地打包产物，不进 Git
  agent-docs/               # 设计、计划和长期记忆
  translate_manga_v1/       # 本机备用旧版，不进 Git
```

`translate_manga_v2/` 主要文件：

```text
start_cli.bat               # 推荐入口
setup_windows.bat           # 首次安装依赖
batch_translate.py          # 命令行批量翻译入口
run_batch_background.py     # 后台跑批日志入口
config/defaults.json        # 默认配置
config/local.example.json   # 本机配置模板，不含密钥
src/translate_manga/        # 应用源码
vendor/Saber-Translator/    # OCR、检测、擦字、渲染依赖
```

## Release 包使用

普通使用者推荐使用 Release 包，不需要理解源码结构。

拿到压缩包后，先解压到任意目录，例如：

```text
<解压目录>/translate_manga_v2_windows
```

进入解压后的目录，按顺序执行：

```bat
setup_windows.bat
```

它会创建 `.venv310` 并安装依赖。完成后复制配置模板：

```text
config/local.example.json -> config/local.json
```

编辑 `config/local.json`，填写翻译 API：

```json
{
  "translation": {
    "model": "mimo-v2.5-pro",
    "base_url": "https://your-openai-compatible-base-url/v1",
    "api_key": "your-api-key"
  }
}
```

然后运行：

```bat
start_cli.bat
```

注意：

- `base_url` 通常需要以 `/v1` 结尾。
- `model` 必须是你的接口支持的模型名。
- `config/local.json` 包含 API key，不要发给别人。
- Release 包不包含 `config/local.json`、缓存、日志、虚拟环境和本地 session。

## 交互菜单

在 Release 解压目录中运行：

```powershell
./start_cli.bat
```

菜单选项：

- `继续上次任务`：复用上次保存的一个或多个输入目录。
- `新建任务`：重新输入单本或多本漫画目录。
- `扫描并纠正错误`：读取 `_debug`，只重跑失败、需复查或缺失输出的页面。
- `退出`

新建任务输入规则：

- 一行一个漫画目录。
- 直接回车结束输入。
- 可粘贴多行路径。
- 输出固定为每个输入目录下的 `out`。
- 只扫描输入目录下的直接图片文件，不递归子目录。
- 支持 `.jpg`、`.jpeg`、`.png`、`.webp`，扩展名大小写不敏感。
- 图片按自然顺序处理，例如 `1, 2, 3, 10, 11, 100`；`cover.jpg` 会稳定排在纯数字页前。

例如：

```text
C:/Manga/徳川家康/01 -> C:/Manga/徳川家康/01/out
C:/Manga/徳川家康/02 -> C:/Manga/徳川家康/02/out
```

## 样式

| 样式 | 用途 | 排版 | OCR / Prompt |
| --- | --- | --- | --- |
| Style 1 | 日漫横排 | 横排，左到右，黑体 | 日语 |
| Style 2 | 日漫竖排 | 竖排，右到左，圆体 | 日语 |
| Style 3 | 英漫横排 | 横排，左到右，圆体 | 英语 |

命令行推荐使用 `--style-id 1|2|3`。旧参数 `--layout-mode horizontal|vertical|auto` 仍兼容。

## 命令行用法

在 Release 解压目录中：

```powershell
./start_cli.bat --input "C:/Manga/Book/01" --output "C:/Manga/Book/01/out" --style-id 2
```

只重跑复查页：

```powershell
./start_cli.bat --input "C:/Manga/Book/01" --output "C:/Manga/Book/01/out" --style-id 2 --retry-review-pages
```

后台跑批并写日志：

```powershell
./.venv310/Scripts/python.exe ./run_batch_background.py "C:/Manga/Book/01" "C:/Manga/Book/01/out" --log-path "./logs/batch-live.log" --style-id 2
```

## 输出结构

```text
out/
  *.translated.png
  _debug/
    pages/*.json
    texts/*.ocr.txt
    texts/*.translation.txt
    review-pages.txt
    failed-translations.tsv
    final-review-report.txt
    summary.json
```

常用排查文件：

- `_debug/review-pages.txt`：需要复查的页面。
- `_debug/failed-translations.tsv`：失败或疑似失败清单。
- `_debug/final-review-report.txt`：最终复查报告、耗时汇总和残留问题。
- `_debug/pages/*.json`：单页 OCR、译文、状态、耗时和上下文。

## 书系 Profile

程序会按输入路径自动识别书系和卷号：

```text
C:/Manga/徳川家康/01 -> 书系: 徳川家康, 卷: 01
C:/Manga/徳川家康/02 -> 书系: 徳川家康, 卷: 02
C:/Manga/卡姆依传    -> 书系: 卡姆依传
```

书系文件位置：

```text
<书系目录>/_translation_profile/
  series_profile.md
  glossary.tsv
  characters.tsv
  translation_memory.json
```

翻译时优先使用当前卷的 `manga_context.md`；没有时复用书系 `series_profile.md`。你可以手工维护 `glossary.tsv` 和 `characters.tsv`，后续卷会自动继承。

## 配置

配置优先级：

```text
config/defaults.json < config/local.json < TRANSLATE_MANGA_CLI_* 环境变量 < 命令行参数
```

本机私有配置写在：

```text
config/local.json
```

常用性能配置：

```json
{
  "pipeline": {
    "translation_quality": "high",
    "debug_flush_interval": 25,
    "color_fast_mode": true
  }
}
```

`translation_quality` 可选：

- `high`：默认，质量优先。
- `balanced`：速度和质量折中。
- `fast`：快速扫图或预览。

## 源码开发

首次开发环境：

```powershell
cd translate_manga_v2
./setup_windows.bat
```

常用验证：

```powershell
./.venv310/Scripts/python.exe -m pytest -q
./.venv310/Scripts/python.exe -m compileall -q src/translate_manga
```

## GitHub 同步边界

应该同步：

- `translate_manga_v2/src/**`
- `translate_manga_v2/tests/**`
- `translate_manga_v2/config/defaults.json`
- `translate_manga_v2/config/local.example.json`
- `translate_manga_v2/*.bat`
- `translate_manga_v2/*.py`
- `README.md`
- `agent-docs/**`

不应同步：

- `config/local.json`
- `config/session.json`
- `.venv310/`
- `.cache/`
- `logs/`
- `Release/`
- 测试漫画素材目录
- API key 或任何私有接口配置

## 常见问题

`start_cli.bat` 提示依赖未安装：

```text
Translate Manga V2 dependencies are not installed.
Please run setup_windows.bat first.
```

先运行 `setup_windows.bat`，完成后再运行 `start_cli.bat`。

API 报错：

- 检查 `config/local.json` 是否存在。
- 检查 `translation.base_url` 是否以 `/v1` 结尾。
- 检查 `translation.api_key` 是否正确。
- 检查 `translation.model` 是否是接口支持的模型名。

英文漫画识别差：

- 使用 `Style 3`。
- Style 1/2 是日漫配置，不适合英文漫画。

有页面没翻译或翻译错：

- 菜单选择 `扫描并纠正错误`。
- 或命令行添加 `--retry-review-pages`。
- 如果同一页多轮后仍显示 `translation_failed` / `translation_failure_placeholder`，通常是翻译 API 拒翻或超时。人工修补时必须同时更新输出图、`_debug/pages/*.json`、`_debug/texts/*.translation.txt`、`review-pages.txt`、`failed-translations.tsv`、`summary.json` 和 stage cache，否则下次扫描会继续把它当失败页重跑。
