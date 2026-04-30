# translate_manga_cli

本地漫画整章批处理翻译器。主流程是 `OCR -> 翻译 -> 擦字 -> 写字`，输出最终译图，适合直接跑一整话或一整卷日漫生肉。

## 当前形态

- 主入口：`batch_translate.py`
- 双击启动：根目录 `start_translate_manga_cli.bat` 或项目内 `start_cli.bat`
- 默认只保留最终译图，文件名为 `*.translated.png`
- 默认跳过已有译图；可用 `overwrite_existing=True` 覆盖重跑
- 默认 OCR 策略：`48px_ocr + manga_ocr hybrid`
- 前置页 / 目录 / 无字页会自动复制原图，避免空跑和卡顿
- 输出目录默认附带 `_debug/`，用于复查 OCR、译文、页型和耗时
- 支持每本漫画目录放 `manga_context.md` 作为整本翻译背景
- 如果目录里没有背景文件，默认会尝试自动生成；失败时会自动降级为空上下文，不阻塞主流程

## 依赖关系

`translate_manga_cli` 现在独立运行，不再依赖 `translate-reader/` 目录。

仍保留的外部依赖只有：

- 同级 `../Saber-Translator`
- 本项目自己的 Python 环境，推荐 `translate_manga_cli/.venv310`

首次在新机器或新目录准备环境时，可直接执行：

```powershell
C:/Python310/python.exe -m venv "D:/github/translate-reader/translate_manga_cli/.venv310"
D:/github/translate-reader/translate_manga_cli/.venv310/Scripts/python.exe -m pip install -r "D:/github/translate-reader/translate_manga_cli/requirements.txt"
```

`start_cli.bat` 会按这个顺序找解释器：

1. `translate_manga_cli/.venv310/Scripts/python.exe`
2. `translate_manga_cli/.venv/Scripts/python.exe`
3. 系统 `python`

## 配置文件

默认配置：

- `config/defaults.json`

用户本地覆盖：

- `config/local.json`

配置优先级：

- `defaults.json`
- `local.json`
- `TRANSLATE_MANGA_CLI_*` 环境变量
- Python 调用参数

最常改的字段在 `config/local.json`：

```json
{
  "paths": {
    "input_dir": "D:/manga/input",
    "output_dir": "D:/manga/output",
    "workspace_root": "",
    "cache_root": ""
  },
  "translation": {
    "model": "mimo-v2.5-pro",
    "base_url": "https://your-openai-compatible-base-url/v1",
    "api_key": ""
  },
  "ocr": {
    "engine": "",
    "enable_hybrid": true,
    "secondary_engine": "",
    "hybrid_threshold": 0.2,
    "fallback_to_manga_ocr_when_48px_unavailable": true
  },
  "pipeline": {
    "manga_context_file_names": ["manga_context.md", "manga_context.txt"],
    "auto_generate_manga_context": true
  },
  "prompts": {
    "translation": {
      "system": "",
      "rounds": {
        "draft": "",
        "contextual": "",
        "final": ""
      }
    }
  }
}
```

还支持这些配置组：

- `ocr`
  - `engine`
  - `enable_hybrid`
  - `secondary_engine`
  - `hybrid_threshold`
  - `fallback_to_manga_ocr_when_48px_unavailable`
- `pipeline`
  - `overwrite_existing`
  - `debug_output`
  - `skip_frontmatter`
  - `translate_batch_size`
  - `translate_batch_max_chars`
  - `manga_context_file_names`
  - `auto_generate_manga_context`
- `prompts`
  - `translation.system`
  - `translation.rounds.draft`
  - `translation.rounds.contextual`
  - `translation.rounds.final`
  - 留空时会回退到 `config/defaults.json` 的默认提示词
- `inpaint`
  - `method`
  - `mask_dilate_size`
  - `mask_box_expand_ratio`
- `render`
  - `font_family`
  - `stroke_enabled`
  - `stroke_color`
  - `stroke_width`
  - `line_spacing`
  - `text_align`
  - `auto_font`
- `runtime`
  - `saber_session_timeout_seconds`
  - `saber_subprocess_timeout_seconds`
  - `saber_operation_timeout_seconds`
    - 例如可单独给 `preprocess` 放宽超时, 避免 48px OCR + 颜色提取在长文页上被 `45s` 提前打断

批处理翻译失败恢复顺序现在是：

1. 正常多轮批量翻译
2. 单页 `retry-single`
3. 轻量单轮直译，无上下文

这样在线 API 偶发超时时，不会优先直接回退成原图拷贝。

## 使用方式

### 1. 双击直接跑

如果 `config/local.json` 里已经填了 `paths.input_dir` 和 `paths.output_dir`，双击：

- `start_translate_manga_cli.bat`

就会直接开始翻译。

如果这两个路径为空，程序会退回到命令行输入。

### 2. Python 调用

```python
from pathlib import Path
from src.cli.service import run_batch_translation

summary = run_batch_translation(
    input_dir=Path(r"D:/input"),
    output_dir=Path(r"D:/output"),
    overwrite_existing=True,
)
print(summary)
```

## 输出规则

- 默认输出：`<原文件名>.translated.png`
- 纯数字文件名会自动补零，例如 `1.jpg -> 001.translated.png`
- 默认不保留中间 clean 图
- 输出目录会生成 `_debug/`

`_debug/` 里的主要文件：

- `pages/*.json`：每页 OCR、译文、页型、耗时、状态
- `texts/*.ocr.txt`：每页 OCR 文本
- `texts/*.translation.txt`：每页最终译文
- `texts/*.{draft,contextual,final}.translation.txt`：三轮翻译各轮结果
- `pages.jsonl`：整本页级清单
- `book.ocr.txt` / `book.translation.txt`：整本合并文本
- `review-pages.txt`：需要人工复查的页
- `summary.json`：整本汇总
- `pages/*.json` 还会记录本页实际使用的 `mangaContext`、背景文件路径、是否自动生成

## 漫画背景提示词

推荐在每本漫画输入目录根放：

- `manga_context.md`

建议内容：

- 作品名、作者、题材
- 主角/常驻角色标准译名
- 时代感和说话口吻
- 标点习惯
- 避免事项

这个文件会注入三轮翻译，优先解决：

- 称呼前后不一致
- 成年向作品被翻成少年漫口气
- 标点过多、语气过躁

## 环境变量

推荐统一改 `config/local.json`。如果需要临时覆盖，可用：

- `TRANSLATE_MANGA_CLI_INPUT_DIR`
- `TRANSLATE_MANGA_CLI_OUTPUT_DIR`
- `TRANSLATE_MANGA_CLI_OCR_ENGINE`
- `TRANSLATE_MANGA_CLI_OCR_ENABLE_HYBRID`
- `TRANSLATE_MANGA_CLI_OCR_SECONDARY_ENGINE`
- `TRANSLATE_MANGA_CLI_OCR_HYBRID_THRESHOLD`
- `TRANSLATE_MANGA_CLI_MODEL`
- `TRANSLATE_MANGA_CLI_BASE_URL`
- `TRANSLATE_MANGA_CLI_API_KEY`
- `TRANSLATE_MANGA_CLI_INPAINT_METHOD`
- `TRANSLATE_MANGA_CLI_SABER_PYTHON`
- `TRANSLATE_MANGA_CLI_SABER_SESSION_TIMEOUT_SECONDS`
- `TRANSLATE_MANGA_CLI_SABER_SUBPROCESS_TIMEOUT_SECONDS`

兼容过渡期仍接受少量旧前缀 `TRANSLATE_READER_*`，但不建议继续用。

## 已验证基线

- `pytest -q`：`99 passed`
- 真实整本重跑基线：
  - 输入：`[古泉智浩] 死んだ目をした少年`
  - 总页数：`188`
  - 结果：`succeeded=188 skipped=0 failed=0`
  - 总耗时：`897.25s`
  - 平均：约 `4.77s/页`
