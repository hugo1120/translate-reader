# translate_manga_cli 设计

## 目标

在仓库根目录新增独立项目 `translate_manga_cli`，复制现有 `translate-reader` 的核心算法与流水线逻辑，改造成不依赖前台 Web UI 的本地控制台批处理工具。

运行目标：

- 启动后在控制台输入图片输入目录和输出目录
- 按文件名顺序整章翻译
- 只输出最终译图
- 已存在的目标译图自动跳过
- 在控制台常驻显示进度与翻译日志

## 用户确认边界

- 项目形态：独立目录 `translate_manga_cli`
- 输入方式：控制台交互输入路径
- 输出方式：写入用户指定输出目录
- 输出文件名：`<原文件名 stem>.translated.png`
- 覆盖策略：默认跳过已存在目标文件；程序化调用可显式覆盖
- 中间产物：不导出 clean 图、不导出 result.json 到输出目录
- 日志粒度：简洁，只显示总进度、当前页、成功/跳过/失败、单页耗时

## 设计决策

### 1. 工程结构

`translate_manga_cli` 复制以下内容作为独立项目基础：

- `src/`
- `tests/`
- `requirements.txt`
- `pytest.ini`
- 必要启动脚本

不复制运行期数据目录、虚拟环境和已有 smoke 产物。

### 2. 运行模式

CLI 不启动 Flask server，但保留现有 `src.app.create_app()` 作为配置容器，以最小改动复用：

- `run_page_pipeline()`
- Saber 子进程桥接
- 章节上下文一致性
- 现有缓存与清洗逻辑

### 3. 输入输出与临时工作区

CLI 运行时：

- 直接读取用户输入目录中的原图，不复制源图片
- 在临时 `DATA_ROOT` 下生成 manifest、cache 和上下文所需数据
- 每页完成后只把最终译图复制到用户输出目录
- 运行结束后删除临时工作区

这样既保留章节上下文，又满足“输出目录只保留最终译图”。

### 4. 章节上下文

整章翻译时，仍沿用当前 `LibraryStore + CacheStore + context snapshot` 机制：

- 当前页会读取前面已完成页面的缓存结果
- 若前页有人工修正译文，也会进入术语上下文

CLI 首版不提供人工修正入口，但保留该兼容能力。

### 5. 日志与进度

控制台输出分两层：

- 常驻进度状态：`[12/59] current=011.jpg ok=10 skip=1 fail=0 elapsed=04:31`
- 页级结果日志：
  - `OK   011.jpg -> 011.translated.png (35.88s)`
  - `SKIP 012.jpg -> 012.translated.png (already exists)`
  - `FAIL 013.jpg (translate error: ...)`

失败页不中断整章，最终输出总汇总。

### 6. 错误处理

- 输入目录不存在：提示并重新输入
- 输出目录不存在：自动创建
- 输入目录无有效图片：直接退出并提示
- 输出命名冲突：
  - 默认情况下，若 `stem.translated.png` 已存在，视为已翻译并直接跳过
  - 若调用方显式启用覆盖模式，则允许重写旧译图
- 单页失败：记失败并继续

### 7. 启动方式

提供独立启动脚本，默认优先使用本地 `.venv310` 或 `.venv`，不再依赖 `translate-reader/.venv*`。

## 非目标

- 不保留浏览器阅读器交互
- 不做单框编辑 UI
- 不做数据库或任务队列
- 不做并行批量翻译优化，先保证稳定复用现有整页流水线

## 2026-04-29 独立化修订

- `translate_manga_cli` 已从“复制出来的旁路工具”升级为唯一活跃项目，不再把 `translate-reader/` 当作运行依赖。
- 默认配置已统一收敛到 `config/defaults.json`，用户覆盖放在 `config/local.json`。
- 启动行为改为：
  - 先读 `config/local.json` 的 `paths.input_dir / output_dir`
  - 若为空，再回退到交互输入
- 翻译 API、Saber 路径、批处理策略、擦字参数、写字样式现在共用同一套配置源，不再分散硬编码在 CLI、路由和翻译适配器里。
- 保留同级 `Saber-Translator` 作为算法依赖；`translate-reader/` 目录本身已在 `2026-04-29` 完成物理删除。
