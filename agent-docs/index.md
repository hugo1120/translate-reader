# agent-docs 索引

## 全局关键记忆

- 工作区根目录仍是 `D:/github/translate-reader`，但自 `2026-04-29` 起唯一活跃项目是 `D:/github/translate-reader/translate_manga_cli`。
- 子目录 `D:/github/translate-reader/translate-reader` 已于 `2026-04-29` 物理删除；新代码、启动脚本、说明文档都不应再把它当成运行前提。
- `translate_manga_cli` 的主定位是本地漫画整章批处理翻译器，核心流程为 `OCR -> 三轮翻译(draft/contextual/final) -> 擦字 -> 写字 -> 输出译图`。
- `translate_manga_cli` 的默认配置统一收敛到：
  - `translate_manga_cli/config/defaults.json`
  - `translate_manga_cli/config/local.json`
- 配置优先级固定为：`defaults.json < local.json < TRANSLATE_MANGA_CLI_* 环境变量 < Python 调用参数`。
- 当前推荐用户只改 `config/local.json` 中这些组：
  - `paths`
  - `ocr`
  - `translation`
  - `prompts`
  - `pipeline`
  - `inpaint`
  - `render`
  - `runtime`
- `translate_manga_cli` 自 `2026-04-30` 起默认 OCR 策略改为 `48px_ocr + manga_ocr hybrid`：
  - 主 OCR：`ocr.engine`
  - 低置信/空结果回退：`ocr.secondary_engine`
  - 当前默认：`48px_ocr -> manga_ocr`
  - 若 48px 模型缺失，会自动回退到纯 `manga_ocr`
- `translate_manga_cli` 自 `2026-04-30` 起默认嵌字可读性策略改为 V3 自适应：
  - 深色底：`白字 + 黑描边 1px`
  - 浅色底：`黑字 + 白描边 1px`
  - 极小框：关闭描边，避免糊成块
- `translate_manga_cli` 自 `2026-04-30` 起支持每本漫画目录根的 `manga_context.md` / `manga_context.txt`：
  - 有就直接读入三轮翻译
  - 没有时默认尝试自动生成 `manga_context.md`
  - 失败时降级为空上下文，不阻塞整本翻译
  - `_debug/pages/*.json` 会记录本页实际使用的漫画背景内容、文件路径和是否自动生成
- `translate_manga_cli` 的 `排版2` 当前是独立竖排布局分支：
  - 只在 `render.layout_mode=vertical` 时启用
  - 目标是“整块居中 + 列均衡 + 竖排去空格/断句”
  - 不影响 `排版1` 横排逻辑
- Saber 48px OCR 模型当前已手动补齐到：
  - `D:/github/translate-reader/Saber-Translator/models/ocr_48px/ocr_ar_48px.ckpt`
  - `D:/github/translate-reader/Saber-Translator/models/ocr_48px/alphabet-all-v7.txt`
- `translate_manga_cli` 自 `2026-04-30` 起支持按 Saber 操作单独放宽超时：
  - 配置键：`runtime.saber_operation_timeout_seconds`
  - 当前默认仅放宽：`preprocess: 90.0`
  - 目的：避免 `48px OCR + 颜色提取` 在长文页上被通用 `45s` 超时提前打断
- `translate_manga_cli` 自 `2026-04-30` 起的 Saber 单次 subprocess fallback 不再把完整 payload 挂在命令行参数上：
  - 现改为 `stdin` 传 JSON payload
  - 目的：避免 Windows 在长 `rawMask` / 大 payload 时触发 `WinError 206`
- 批处理翻译失败恢复顺序已扩展为：
  - 正常多轮批量翻译
  - 单页 `retry-single`
  - 轻量单轮直译（无上下文）
  - 仍失败才回退原图拷贝
- `batch_translate.py` 现在会优先读取 `config/local.json` 里的 `paths.input_dir` 和 `paths.output_dir`；若为空才回退到命令行输入。
- CLI、调试路由、后台批处理脚本现在共用同一套翻译默认值；根目录 `翻译api.txt` 只保留脱敏示例，实际私有接口配置只放 `config/local.json` 或 `TRANSLATE_MANGA_CLI_*` 环境变量。
- 四段翻译提示词已正式进入配置：
  - `prompts.translation.system`
  - `prompts.translation.rounds.draft`
  - `prompts.translation.rounds.contextual`
  - `prompts.translation.rounds.final`
  - `local.json` 留空时回退到 `defaults.json`
- Saber 仍作为同级外部依赖存在：`D:/github/translate-reader/Saber-Translator`。
- `translate_manga_cli` 自身的运行时解释器优先找本地 `.venv310`，不应再回退到 `translate-reader/.venv*`。
- `translate_manga_cli/.venv310` 已在 `2026-04-29` 按 `requirements.txt` 重建并验证通过：`python -m pytest -q` 为 `91 passed`。
- 为兼容过渡，代码层仍接受少量旧前缀 `TRANSLATE_READER_*`，但文档只推荐 `TRANSLATE_MANGA_CLI_*`。
- 批处理能力当前已覆盖：
  - 自然排序扫描输入图片
  - `*.translated.png` 输出
  - `overwrite_existing`
  - 隐藏 stage cache
  - `_debug/` 调试产物
  - 前置页 / 目录页轻量跳过
  - OpenAI-compatible 超时与逐页降级重试
- 最近稳定基线：
  - `pytest -q`：`99 passed`
  - 真实整本 `[古泉智浩] 死んだ目をした少年`：`188` 页，`897.25s`，约 `4.77s/页`
  - 真实整卷 `[藤子不二雄A] 帰ッテキタせぇるすまん 第01巻`：
    - V2 最终补齐：`170/170`
    - 最后一轮全缓存重渲染耗时：`467.85s`

## 文档列表

### 活跃文档

- [2026-04-28 translate_manga_cli 设计](./specs/2026-04-28-translate-manga-cli-design.md)
  - 适用场景：理解 CLI 的目标边界、运行方式，以及 `2026-04-29` 之后的独立化方向。
- [2026-04-28 translate_manga_cli 实施计划](./plans/2026-04-28-translate-manga-cli-implementation-plan.md)
  - 适用场景：追踪 CLI 已落地的流水线、性能优化、调试输出和独立化收尾任务。
- [translate_manga_cli 使用说明](../translate_manga_cli/README.md)
  - 适用场景：人类接手者直接查启动方式、配置方法、输出结构和覆盖重跑。
- [translate_manga_cli 翻译提示词方案](../translate_manga_cli/docs/translation_prompt_scheme.md)
  - 适用场景：调整翻译 prompt、理解 `manga_context.md` 应该写什么。
- [translate_manga_cli manga_context 生成模板](../translate_manga_cli/docs/manga_context_prompt_template.md)
  - 适用场景：用 AI 生成每本漫画的 `manga_context.md` 首版。

### 历史文档

- [2026-04-28 translate-reader 本地 Web 机翻阅读器首版设计](./specs/2026-04-28-translate-reader-local-web-reader-design.md)
  - 适用场景：仅供回溯早期 Web 阅读器方案；当前不是活跃实现目标。
- [2026-04-28 translate-reader 阅读器增强与人工微调设计](./specs/2026-04-28-translate-reader-reader-enhancement-design.md)
  - 适用场景：仅供回溯早期阅读器增强设想；当前不继续推进。
- [2026-04-28 translate-reader V1 实施计划](./plans/2026-04-28-translate-reader-v1-implementation-plan.md)
  - 适用场景：历史记录，保留以便理解 CLI 的来源。
- [2026-04-28 translate-reader 阅读器增强实施计划](./plans/2026-04-28-translate-reader-reader-enhancement-implementation-plan.md)
  - 适用场景：历史记录，当前不再执行。
