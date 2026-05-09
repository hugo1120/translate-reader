# translate_manga_v2 Agent Notes

## 项目边界

- 本项目是独立命令行漫画翻译器，目录固定为 `D:/github/translate-reader/translate_manga_v2`。
- 不修改同级旧项目 `translate_manga_cli`、旧 `Saber-Translator` 或其他测试漫画目录，除非用户明确要求。
- `config/local.json`、`config/session.json`、`logs/`、`smoke/`、`.cache/`、`vendor/Saber-Translator/data/` 是本地运行产物或私密配置，不打印、不提交。
- GitHub 同步只提交 V2 代码、文档、测试和无密钥模板；`config/local.example.json` 可提交，真实 `config/local*.json` 不提交。
- `vendor/Saber-Translator` 体积较大，受根 `.gitignore` 的 `Saber-Translator/` 规则保护，默认不提交。

## 当前入口

- 交互菜单：`start_cli.bat`
- 参数模式：`.venv310/Scripts/python.exe batch_translate.py --input "<input>" --output "<output>"`
- 后台日志模式：`.venv310/Scripts/python.exe run_batch_background.py "<input>" "<output>" --log-path "logs/batch-live.log"`
- 无参数 `start_cli.bat` 进入菜单；有参数时透传给 `batch_translate.py`。

## 样式约定

- `--style-id 1`：横排日漫，黑体，左到右，日语 OCR/提示词。
- `--style-id 2`：竖排日漫，圆体，右到左，日语 OCR/提示词。
- `--style-id 3`：横排英漫，圆体，左到右，PaddleOCR English ONNX + 英语提示词。
- 旧参数 `--layout-mode horizontal|vertical|auto` 仍兼容；英文漫画直接用 `--style-id 3`。
- 样式上下文必须传到翻译层，尤其轻量兜底翻译不能丢 `promptPreset/sourceLanguage/readingOrder`。

## 纠错与缓存

- 完整翻译默认跳过已有输出，适合中断后继续。
- 菜单“扫描并纠正错误”和命令行 `--retry-review-pages` 只覆盖 `_debug` 标记的问题页，以及源图存在但输出缺失的页。
- `_debug/failed-translations.tsv`、`_debug/review-pages.txt`、`_debug/pages/*.json` 都是返工来源。
- 翻译缓存签名包含提示词 profile、实际提示词配置和 `manga_context` 内容；提示词或书系背景变化后，应重新翻译而不是复用旧译文缓存。
- 预处理缓存签名包含 OCR 配置、语言和阅读方向；OCR/样式变动后应重新 PREP/OCR。

## 常用验证

```powershell
.venv310/Scripts/python.exe -m pytest -q
.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py
cmd /c start_cli.bat --help
```
