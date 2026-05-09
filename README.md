# translate-reader 工作区

当前活跃项目是 `D:/github/translate-reader/translate_manga_v2`。后续开发和 GitHub 同步只以 V2 为准；旧 `translate_manga_cli` 已删除，`translate_manga_v1` 仅作本机备用，不参与同步。

## 目录定位

- `translate_manga_v2/`：当前重构版漫画批量翻译器。
- `translate_manga_v1/`：旧 CLI 的本机备用副本，已被 `.gitignore` 整目录忽略。
- `Saber-Translator/`：旧同级 Saber 基线；V2 默认使用自己的 `translate_manga_v2/vendor/Saber-Translator`。
- `agent-docs/`：长期设计、计划和项目记忆索引。
- `翻译测试日漫/`：本地真实样本与用户测试数据。

## 当前主流程

`translate_manga_v2` 是纯命令行本地漫画整章/整卷翻译器，主链路为：

```text
OCR -> 三轮翻译(draft/contextual/final) -> 擦字 -> 写字 -> 输出译图
```

当前不包含 Web API、浏览器界面或本地阅读器壳。

## 快速启动

```powershell
cd "D:/github/translate-reader/translate_manga_v2"
./start_cli.bat
```

无参数时进入交互菜单：

- `继续上次任务`：复用上次保存的一个或多个输入目录，继续跑未完成内容。
- `新建任务`：重新输入一个或多个漫画目录，输出固定到每个输入目录下的 `out`。
- `扫描并纠正错误`：扫描已有 `_debug` 记录，只覆盖重跑失败/需复查页面。
- `退出`

有参数时，`start_cli.bat` 会直接透传给 `batch_translate.py`：

```powershell
./start_cli.bat --input "D:/path/to/input" --output "D:/path/to/input/out" --layout-mode vertical
```

更完整说明见 `translate_manga_v2/start.md`。

## 配置

V2 配置优先级：

```text
config/defaults.json < config/local.json < TRANSLATE_MANGA_CLI_* 环境变量 < 命令行参数
```

私有接口、模型和本机路径放在：

```text
translate_manga_v2/config/local.json
```

该文件被 `.gitignore` 忽略，不应写入公开文档或提交记录。

## 输出和纠错

默认输出：

```text
<输入目录>/out/*.translated.png
```

调试与复查产物：

- `_debug/pages/*.json`：每页 OCR、译文、页型、耗时和状态。
- `_debug/review-pages.txt`：需要复查/重跑的页。
- `_debug/failed-translations.tsv`：失败或疑似失败页清单。
- `_debug/final-review-report.txt`：最终复查报告和残留问题。
- `_debug/summary.json`：本次跑批汇总与运行选项。

完整翻译结束后会自动扫描失败页并最多重试 5 轮；菜单里的 `扫描并纠正错误` 可对已有输出反复补救。

## 书系 Profile

当输入目录最后一段是卷号时，程序会把上一级识别为书系根目录：

```text
D:/漫画/德川家康/01 -> 书系: 德川家康, 卷: 01
D:/漫画/德川家康/02 -> 书系: 德川家康, 卷: 02
```

书系提示词和术语文件保存在：

```text
<书系目录>/_translation_profile/
  series_profile.md
  glossary.tsv
  characters.tsv
  translation_memory.json
```

翻译时优先使用当前卷 `manga_context.md`；如果不存在，就复用书系 `series_profile.md`。

## V2 开发基线

常用验证命令：

```powershell
cd "D:/github/translate-reader/translate_manga_v2"
./.venv310/Scripts/python.exe -m pytest --ignore=tests/test_cli_batch.py -q
./.venv310/Scripts/python.exe -m pytest tests/test_book_profile.py tests/test_manga_context_service.py tests/test_cli_menu.py -q
./.venv310/Scripts/python.exe -m compileall -q src/translate_manga/core/context src/translate_manga/cli/menu.py
```

`2026-05-08` 验证基线：

- `pytest --ignore=tests/test_cli_batch.py -q`：`110 passed`
- `pytest tests/test_book_profile.py tests/test_manga_context_service.py tests/test_cli_menu.py -q`：`14 passed`
- `compileall`：通过
