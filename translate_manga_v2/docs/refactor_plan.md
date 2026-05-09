# translate_manga_v2 重构计划

## 当前基线

- 新目录：`D:/github/translate-reader/translate_manga_v2`
- CLI 已复制到新目录，旧 `translate_manga_cli` 不受影响。
- Saber 已复制到 `vendor/Saber-Translator`，默认 `paths.saber_root` 已改为 `vendor/Saber-Translator`。
- `config/local.json` 已按要求复制；该文件包含本地私密配置，已在新项目 `.gitignore` 中忽略。
- 应用包已迁移到标准 src-layout：`src/translate_manga/**`。
- 交互菜单已收敛为 `继续上次任务 / 新建任务 / 扫描并纠正错误 / 退出` 四项。
- 输出目录固定为每个输入目录下的 `out`；完整翻译默认跳过已有输出，纠错重跑只覆盖 `_debug` 标记的问题页。
- `_debug` 已支持 `failed-translations.tsv`、`review-pages.txt`、`final-review-report.txt` 和 `preprocessedPayload`。
- 批量输入支持拆分连在一起的 Windows 盘符路径，并自动识别书系/卷号，生成或复用 `<书系目录>/_translation_profile/series_profile.md`。
- 已支持三个明确样式：Style 1 日漫横排、Style 2 日漫竖排、Style 3 英文欧美漫画横排。Style 3 使用 PaddleOCR English ONNX、英文提示词和 LTR 阅读顺序。
- 后台入口 `run_batch_background.py` 已支持 `--style-id` 与 `--retry-review-pages`，和主 CLI 参数保持一致。
- 翻译缓存签名已包含提示词 profile、实际提示词配置和 `manga_context` 内容；提示词或书系背景变化会触发重新翻译。
- 冒烟验证：
  - `Kamui#01_034.jpg` 单页真实翻译成功，输出 `smoke/kamui_034_output/Kamui#01_034.translated.png`
  - 英文漫画 Style 3 两页真实冒烟成功，输出 `smoke/style3-english-20260509-111412`
  - 三样式样张冒烟成功，输出 `smoke/three-styles-20260509-111852`
  - `tests/test_pipeline_service.py` + `tests/test_inpaint_render_services.py`：`31 passed`

## 重构目标

- 新项目独立运行，不依赖旧 `translate_manga_cli` 或旧同级 `Saber-Translator`。
- 保留现有全部功能：
  - 交互菜单与参数模式
  - 批量目录模式
  - `48px_ocr + manga_ocr hybrid`
  - 三轮翻译与上下文注入
  - 前置页/目录页/空页跳过
  - 擦字、写字、水印、V4 readability
  - 隐藏 stage cache 与 `_debug` 调试产物
  - 失败重试与轻量降级
- 把当前跨目录、跨职责、入口分散的问题整理成清晰边界。

## 目标结构

```text
translate_manga_v2/
  src/
    translate_manga/
      app/                 # 应用编排
      cli/                 # 菜单、批处理入口、进度输出
      config/              # 配置加载、路径解析、session
      pipeline/            # 页面流水线、缓存、页分类
      translation/         # OpenAI-compatible 翻译与 prompt
      rendering/           # 写字样式决策、V4 readability
      saber/               # Saber 适配层，只暴露稳定接口
  vendor/
    Saber-Translator/      # 暂时保留原后端，后续再瘦身
  config/
    defaults.json
    local.example.json
  scripts/
    setup_venv.ps1
    smoke_test.ps1
  tests/
  start_cli.bat
  batch_translate.py
```

## 分阶段计划

### Phase 1：安全基线固定

- 保留当前功能路径，只做命名和边界整理。
- 增加 `config/local.example.json`，从文档中移除真实 API 示例。
- 明确运行产物目录：`workspace/`、`.cache/`、`logs/`、`smoke/` 全部不进版本。
- 补一组稳定冒烟命令：
  - `python -m pytest tests/test_pipeline_service.py tests/test_inpaint_render_services.py -q`
  - 单页真实翻译 smoke，输入固定为 `smoke/kamui_034_input`

### Phase 2：包结构重命名

- 将 `src/core/**`、`src/cli/**`、`src/config/**` 迁移到 `src/translate_manga/**`。
- 保留薄兼容入口：
  - `batch_translate.py`
  - `run_batch_background.py`
  - `start_cli.bat`
- 测试同步改 import，不再直接依赖裸 `src.*` 命名。

### Phase 3：Saber 适配层收口

状态：未实施。当前 Saber 仍通过 `translate_manga.integrations.saber_loader` 适配，vendor 内部 `src.core.*` 导入保留。

- 将 `src/integrations/saber_loader.py` 拆成：
  - `saber/paths.py`
  - `saber/session.py`
  - `saber/scripts.py`
  - `saber/client.py`
- Pipeline 只调用稳定接口：
  - `detect_page`
  - `ocr_page`
  - `extract_bubble_colors`
  - `inpaint_page`
  - `render_page`
- Saber 内部实现仍放在 `vendor/Saber-Translator`，暂不改它的核心算法。

### Phase 4：配置与运行时清理

状态：部分实施。配置仍使用 `config/defaults.json` / `config/local.json`，session 仍在 `config/session.json`；已新增 `translate_manga.config.paths.find_project_root()` 降低路径推断风险。

- `defaults.json` 只保留项目默认，不放私密值。
- `local.json` 仅作为本机覆盖文件。
- `session.json` 从配置目录中逻辑隔离，后续可移到 `runtime/session.json`。
- 所有路径配置都通过 `PathResolver` 统一解析，避免散落的 `parents[2]` 和相对路径推断。

### Phase 5：测试加速与回归矩阵

状态：部分实施。当前常用回归命令是排除慢文件 `tests/test_cli_batch.py` 后跑全量，再定向运行关键 `test_cli_batch.py` 用例。

- 把慢的 `test_cli_batch.py` 拆成小组，避免整文件超时。
- 为真实样本页建立明确 smoke：
  - `卡姆依传/01/Kamui#01_034.jpg`
  - `德川家康/05/tokugawa#05_005.jpg`
- 输出只校验存在、debug summary、气泡样式字段，不把大图纳入仓库。

### Phase 6：Saber 瘦身

状态：未实施。

- 在新项目稳定后再处理。
- 从 `vendor/Saber-Translator` 中识别真实使用文件：
  - `src/core/detection.py`
  - `src/core/ocr.py`
  - `src/core/ocr_types.py`
  - `src/core/color_extractor.py`
  - `src/core/inpainting.py`
  - `src/core/rendering.py`
  - `src/core/config_models.py`
  - `src/interfaces/ocr_48px/**`
  - `src/interfaces/manga_ocr_interface.py`
  - `models/ocr_48px/**`
  - `src/app/static/fonts/**`
- 逐步删除未使用 Web、frontend、manga_insight、gallery import 相关代码。

## 验收标准

- `start_cli.bat` 可在新目录直接启动。
- `batch_translate.py --help` 正常。
- 单页真实翻译成功，输出译图和 `_debug/summary.json`。
- 相关单测通过。
- 旧 `translate_manga_cli` 和旧 `Saber-Translator` 不被修改，不影响继续运行。

## 2026-05-09 当前验证命令

- `.venv310/Scripts/python.exe -m pytest -q`：`169 passed`
- `.venv310/Scripts/python.exe -m compileall -q src batch_translate.py run_batch_background.py`
- `cmd /c start_cli.bat --help`
- `"4" | cmd /c start_cli.bat`：菜单可正常退出
