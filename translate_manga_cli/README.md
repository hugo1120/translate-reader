# translate_manga_cli

纯命令行漫画批量翻译器。

当前定位只有一条主链路:

`OCR -> 三轮翻译(draft/contextual/final) -> 擦字 -> 写字 -> 输出译图`

不再包含 Web API、浏览器界面或本地阅读器壳。

## 运行方式

交互式菜单入口：

```powershell
./start_cli.bat
```

无参数时进入交互菜单；有参数时直接透传给 `batch_translate.py`。

交互菜单支持两种运行方式：

- 单目录：`Reuse` / `Reset`
- 批量目录：`Batch mode`

批量目录模式下：

- 一行一个输入目录
- 整批共用一次样式和覆盖策略
- 每本输出目录自动写到对应输入目录下的 `out`

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

- `--layout-mode horizontal|vertical|auto`
- `--overwrite-existing`
- `--workspace-root`
- `--cache-root`
- `--model`
- `--base-url`
- `--api-key`

风格映射：

- `Style 1 = horizontal`
- `Style 2 = vertical`

更完整的启动说明见 [start.md](./start.md)。

后台跑批并写实时日志:

```powershell
./.venv310/Scripts/python.exe ./run_batch_background.py --log-path "./logs/batch-live.log"
```

## 配置优先级

`config/defaults.json < config/local.json < TRANSLATE_MANGA_CLI_* 环境变量 < 命令行参数`

## 输出结构

- `*.translated.png`: 最终译图
- `_debug/pages/*.json`: 每页调试记录
- `_debug/texts/*.ocr.txt`: OCR 文本
- `_debug/texts/*.translation.txt`: 最终译文
- `_debug/summary.json`: 本次跑批汇总

## 依赖

- `Saber-Translator`
- `Pillow`
- `OpenAI-compatible` 翻译接口
