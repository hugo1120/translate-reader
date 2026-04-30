# translate_manga_cli 实施计划

## Task 1：复制独立项目骨架

- [x] 从 `translate-reader` 复制 `src/`、`tests/`、`requirements.txt`、`pytest.ini` 到 `translate_manga_cli`
- [x] 不复制 `.venv`、`data*`、`.pytest_cache`
- [x] 为独立项目补一个 README 或启动脚本说明

## Task 2：增加 CLI 运行入口

- [x] 新增交互式批处理入口文件
- [x] 控制台读取 `input/output` 目录
- [x] 统一输出命名为 `stem.translated.png`
- [x] 若目标文件已存在则跳过

## Task 3：批处理编排与临时工作区

- [x] 基于临时 `DATA_ROOT` 构建页面 manifest
- [x] 复用 `run_page_pipeline()` 执行整页流程
- [x] 每页只复制最终译图到输出目录
- [x] 运行结束后清理临时目录

## Task 4：日志与进度

- [x] 常驻显示总进度、当前页、成功/跳过/失败、总耗时
- [x] 输出单页 `OK/SKIP/FAIL` 日志
- [x] 最终输出整章汇总

## Task 5：测试与烟测

- [x] 补 CLI 相关测试
- [x] 回跑核心回归测试
- [x] 用真实目录做一次批处理 smoke

## Task 6：可读性增强

- [x] 为 CLI 默认写字样式增加更强的可读性配置（思源黑体粗体、白色描边、较紧凑行距）
- [x] 为 Saber 自动字号桥接暴露 CLI 侧可控参数（最小字号、最大字号、padding ratio）
- [x] 调整翻译提示词与后处理，减少中文全角标点和冗余标点

## Task 7：P0-P4 性能优化

- [x] P0：将 Saber 调用改为长驻 worker 会话，避免每步重复起进程
- [x] P1：新增单次 `preprocess`，合并 `detect + ocr + color`
- [x] P2：批处理主循环改为“当前批次翻译时，预处理下一批次”
- [x] P3：多页文本扁平化后合并成单次 API 翻译请求，再按页拆回
- [x] P4：新增隐藏 stage cache，支持跨运行续跑且不污染输出目录

## Task 8：重跑与调试一致性补强

- [x] 为 `run_batch_translation()` 增加 `overwrite_existing=True`，支持不删输出目录的整本覆盖重跑
- [x] 为 `_debug/pages/*.json`、`pages.jsonl`、`summary.json` 增加最终回写，避免覆盖重跑后残留旧的 `skipped-existing`
- [x] 补一份 `translate_manga_cli/README.md`，给非当前会话的接手者说明启动方式、输出结构、覆盖重跑方式和已知限制

## Task 9：独立化与配置收敛

- [x] 把默认配置统一收敛到 `translate_manga_cli/config/defaults.json`
- [x] 新增 `translate_manga_cli/config/local.json`，供本地输入/输出目录和 API 覆盖使用
- [x] 让 CLI、调试路由、翻译适配器、Saber 桥接共享同一套默认配置
- [x] 启动脚本改为优先使用本项目 `.venv310`
- [x] 清理代码与文档中的 `translate-reader` 运行依赖表述
- [x] 物理删除退役的 `translate-reader/` 目录
- [x] 用 `translate_manga_cli/.venv310` 重新安装 `requirements.txt` 并验证 `pytest -q` 为 `91 passed`

## Smoke 结果

- 首轮真实 CLI smoke：
  - `009.jpg -> 009.translated.png`，`33.51s`
  - `010.jpg -> 010.translated.png`，`43.06s`
  - `011.jpg -> 011.translated.png`，`32.53s`
  - 汇总：`ok=3 skip=0 fail=0 elapsed=01:49`
- 二次重复运行：
  - `009/010/011` 全部命中 `SKIP`
  - 汇总：`ok=0 skip=3 fail=0 elapsed=0.02s`
- P0-P4 后真实 smoke（新输出目录，仍为 `009/010/011`）：
  - `009.jpg -> 009.translated.png`，整批首轮总耗时 `31.50s`
  - 首轮汇总：`ok=3 skip=0 fail=0 elapsed=31.50s`
  - 同输入换新输出目录复跑（命中隐藏 stage cache）：`ok=3 skip=0 fail=0 elapsed=6.69s`
  - 同输出目录再次复跑：`ok=0 skip=3 fail=0 elapsed=0.01s`
- 真实整本覆盖重跑（`[古泉智浩] 死んだ目をした少年`）：
  - 输入页数：`188`
  - 汇总：`ok=188 skip=0 fail=0 elapsed=897.25s`
  - 平均耗时：约 `4.77s/页`
  - `_debug/summary.json` 修正后：`translated=183`、`copied=5`、`needsReviewPages=[]`
