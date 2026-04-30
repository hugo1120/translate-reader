# 交互式 CLI 菜单设计

## 目标

为 `translate_manga_cli` 增加一个交互式控制台菜单入口，满足以下需求：

- 用户双击或直接运行 `start_cli.bat` 时，无需手写参数
- 可在菜单里设置输入目录、输出目录、样式和是否覆盖已有输出
- 支持 `reuse / reset`
- 上一次输入目录、输出目录、样式、覆盖开关可跨程序重启记忆
- 翻译完成后返回主菜单，而不是直接退出
- 运行中继续显示现有批处理进度日志
- 纯命令行参数模式继续保留，供自动化和脚本调用

本次不处理标题页自适应。

## 已确认约束

- `start_cli.bat` 有参数时：直接透传给 `batch_translate.py`
- `start_cli.bat` 无参数时：进入交互式菜单
- 样式映射固定：
  - `Style 1 = horizontal`：横排黑体，左到右
  - `Style 2 = vertical`：竖排圆体，右到左
- 菜单支持覆盖开关
- 用户当前验证目录：
  - 输入：`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译前`
  - 输出：`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译后`

## 方案对比

### 方案 A：只用 bat 写完整菜单

优点：

- 表面改动最少

缺点：

- Windows bat 很难稳定处理菜单循环、路径输入、状态持久化和异常处理
- 几乎不可测试
- 后续维护成本高

### 方案 B：新增 Python 菜单入口，bat 只负责分流

优点：

- 菜单逻辑、状态持久化和输入校验都能写成可测试 Python 代码
- 保留现有参数模式，不影响自动化
- 后续扩展标题页选项、运行模式选项更容易

缺点：

- 会新增一个入口模块

### 推荐：方案 B

原因：

- 这是最干净且风险最低的实现
- 和当前“CLI-only + 参数模式保留”的架构不冲突

## 设计

### 入口分工

- `start_cli.bat`
  - 有参数：继续执行 `batch_translate.py %*`
  - 无参数：执行新的菜单入口模块
- `batch_translate.py`
  - 保持纯参数模式
  - 不重新塞回交互逻辑
- 新增 `src/cli/menu.py`
  - 承担菜单循环、状态读写、输入校验、菜单内发起翻译

### 状态持久化

新增或恢复 `config/session.json`，记录：

- `last_input_dir`
- `last_output_dir`
- `last_layout_mode`
- `last_overwrite_existing`

状态只存本地运行偏好，不存 API key。

### 菜单结构

主菜单：

1. `Reuse 上次配置并开始`
2. `Reset 重新设置输入/输出/样式/覆盖策略`
3. `退出`

说明：

- 首次运行无 session 时，默认引导用户走设置流程
- 每次返回主菜单时都展示当前配置快照
- 翻译完成后显示 summary，再直接返回主菜单

### 输入校验

- 输入目录必须存在且是目录
- 输出目录允许不存在，运行时自动创建
- 样式只允许 `1/2`
- 覆盖策略只允许 `1/2`
  - `1 = 跳过已有输出`
  - `2 = 覆盖已有输出`

### 运行行为

菜单最终仍调用现有 `run_batch_translation()`，只把下面这些值传进去：

- `input_dir`
- `output_dir`
- `layout_mode`
- `overwrite_existing`

这样可以继续复用当前进度日志和 `_debug` 写出逻辑，避免重复实现。

### `_debug` 增补

当前 `_debug` 里没有明确记录本次启动选择的样式和覆盖策略。

本次需要在 `_debug/summary.json` 的 `runSummary` 或新增 `runOptions` 中补充：

- `inputDir`
- `outputDir`
- `layoutMode`
- `styleName`
- `overwriteExisting`
- `launchMode`：`menu` 或 `args`
- `translationModel`
- `ocrEngine`
- `secondaryOcrEngine`

不记录敏感字段，例如 `api_key`。

### 文档

新增 `start.md`，内容包括：

- 交互菜单用法
- 纯命令行参数用法
- 样式1/样式2说明
- `reuse / reset` 说明
- 覆盖开关说明
- `_debug` 会记录哪些运行策略

`README.md` 同步补一段简版入口说明，避免和 `start.md` 脱节。

## 影响文件

预计修改：

- `start_cli.bat`
- `batch_translate.py`（最多只改少量公共辅助函数导出或复用，不塞菜单）
- `src/config/settings.py`
- `src/config/__init__.py`
- `src/cli/debug_artifacts.py`
- `README.md`

预计新增：

- `src/cli/menu.py`
- `start.md`
- 菜单相关测试文件

## 测试策略

### 自动化测试

- 菜单首次启动无 session
- 菜单 reuse 已保存配置
- 菜单 reset 后保存新配置
- 菜单修改样式
- 菜单修改覆盖策略
- 菜单翻译完成后返回主菜单
- `start_cli.bat` 无参数进菜单
- `start_cli.bat` 有参数直接透传
- `_debug/summary.json` 正确记录 `runOptions`

### 人工验证

使用用户指定目录：

- 输入：`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译前`
- 输出：`D:/github/translate-reader/翻译测试日漫/笑面推销员/翻译后`

验证两种模式：

1. `start_cli.bat` 无参数进入菜单，选择目录与样式后翻译
2. 纯命令行参数模式直接翻译

## 风险与控制

- 风险：菜单逻辑和参数逻辑重新耦合
  - 控制：菜单只负责收集参数，实际翻译仍统一调用 `run_batch_translation()`
- 风险：session 状态损坏导致菜单异常
  - 控制：读取失败时回退为空配置
- 风险：`_debug` 增补字段影响旧脚本解析
  - 控制：新增字段，不改旧字段含义
