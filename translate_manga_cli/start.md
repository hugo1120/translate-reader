# 启动说明

## 交互菜单

直接运行：

```powershell
./start_cli.bat
```

无参数时会进入交互式控制台菜单，支持：

- `Reuse`：复用上一次保存的输入目录、输出目录、风格和覆盖策略后直接开始
- `Reset`：重新输入输入目录、输出目录、风格和覆盖策略后直接开始
- `Batch mode`：批量输入多个图片目录，整批共用样式和覆盖策略，每本自动输出到各自目录下的 `out`
- `Exit`：退出菜单

菜单每次翻译完成后都会返回主菜单，不会直接退出。

### 批量模式

批量模式的输入方式：

- 一行一个输入目录
- 直接回车结束输入
- 然后统一选择一次样式
- 再统一选择一次覆盖策略

每本漫画的输出目录固定为：

```text
<输入目录>/out
```

例如：

```text
D:/book-a/item/image -> D:/book-a/item/image/out
D:/book-b/item/image -> D:/book-b/item/image/out
```

跨程序重启会记住上一次配置，保存在：

```text
config/session.json
```

## 纯命令行

有参数时，`start_cli.bat` 会直接透传给 `batch_translate.py`：

```powershell
./start_cli.bat --input "D:/path/to/input" --output "D:/path/to/output" --layout-mode vertical
```

也可以直接运行 Python 入口：

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py --input "D:/path/to/input" --output "D:/path/to/output"
```

支持位置参数：

```powershell
./.venv310/Scripts/python.exe ./batch_translate.py "D:/path/to/input" "D:/path/to/output"
```

## 风格说明

- `Style 1 = horizontal`：横排黑体，左到右
- `Style 2 = vertical`：竖排圆体，右到左

## 覆盖策略

- `1 = 跳过已有输出`
- `2 = 覆盖已有输出`

## 调试记录

开启 `_debug` 时，`_debug/summary.json` 会额外记录本次运行策略：

- `inputDir`
- `outputDir`
- `layoutMode`
- `styleName`
- `overwriteExisting`
- `launchMode`
- `translationModel`
- `ocrEngine`
- `secondaryOcrEngine`
