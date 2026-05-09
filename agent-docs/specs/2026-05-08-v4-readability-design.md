# V4 readability 设计

> 历史背景：本文最初面向旧 `translate_manga_cli` 编写；当前实现和后续维护以 `translate_manga_v2` 为准。

## 目标

将 `translate_manga_cli` 当前的 V3 自适应嵌字配色策略收敛为新的全局默认 `V4 readability`，目标是：

- 保持漫画对白框的清爽感，不让描边干扰正常阅读
- 在灰底、脏底、网点、线稿穿插背景上维持足够可读性
- 消除当前 `白字 + 黑描边`、`黑字 + 白描边`、`黑字 + 无描边`、fallback 默认样式混用导致的风格不统一问题

## 用户确认边界

- 新策略作为新的全局默认，直接替换当前 V3 逻辑
- 全局文字颜色固定为黑色
- 只允许两种最终视觉样式：
  - `black + white stroke`
  - `black + no stroke`
- 白描边应尽量轻，只作为复杂背景上的隔离层，不应抢字形本身的视觉权重

## 非目标

- 本次不引入新的 UI 选项或样式切换菜单
- 本次不保留 V3 和 V4 并存的运行时开关
- 本次不扩展新的渲染协议字段，例如 `strokeAlpha`
- 本次不改动排版模式、自动字号、翻译流程或 OCR 流程

## 现状问题

当前逻辑位于 `src/core/pipeline/service.py::_resolve_bubble_readability_style()`，主要问题：

- 深底会切到 `白字 + 黑描边`
- 浅底会切到 `黑字 + 白描边/无描边`
- `fg/bg` 同暗色时会触发特殊回退，导致和其他气泡风格不一致
- 颜色提取失败时会落入默认 render 样式，容易形成“同页两套甚至三套观感”
- 小框虽然已有关闭描边逻辑，但阈值偏粗，部分竖排短句仍显得脏

## 设计决策

### 1. 全局输出风格

新的 V4 只输出两种样式：

- `black + white stroke`
- `black + no stroke`

其中：

- `textColor` 固定为 `#111111`
- `strokeColor` 固定为 `#FFFFFF`
- `strokeWidth` 仅允许 `0` 或 `1`

不再输出白字，不再输出黑描边。

### 2. 判断链路

单个气泡的样式决策顺序固定为：

1. 先判小框
2. 再判背景亮度
3. 再判背景复杂度
4. 颜色提取不可信时走复杂度兜底

判断必须在 `_build_bubbles()` 阶段完成，Saber render 只消费最终样式，不再二次决定配色。

### 3. 小框优先

小框应优先避免描边，因为 1px 白描边对窄竖排和短文本的侵入感最强。

建议规则：

- `min(width, height) <= 32` 时判定为小框
- 或 `width * height <= 1100` 时判定为小框

小框直接使用：

- `black + no stroke`

这样可以减少语气词、短促对白、小注释框的糊团感。

### 4. 背景亮度分层

颜色可信时，先根据背景亮度决定基础倾向：

- `bg_luminance >= 225`
  - 倾向 `black + no stroke`
- `165 <= bg_luminance < 225`
  - 进入复杂度判定
- `bg_luminance < 165`
  - 倾向 `black + white stroke`

这里的亮度只负责提供基线，不单独完成最终决策。浅色但复杂的背景仍允许进入描边分支。

### 5. 背景复杂度

为了提高漫画观感，V4 不只看亮度，还要识别“亮但花”的背景。

复杂度建议由以下信号组成：

- `grayStdDev`
  - 灰度标准差，越高表示底子越不干净
- `edgeDensity`
  - 边缘/线稿密度，越高表示线稿更容易穿字
- `darkPixelRatio`
  - 暗像素比例，越高表示局部压字风险更高

实现上应以轻量级局部图像统计为主，不引入额外模型。

决策规则：

- 高亮且复杂度低：`black + no stroke`
- 高亮但复杂度高：`black + white stroke`
- 中亮度且复杂度中高：`black + white stroke`
- 偏暗背景：`black + white stroke`

### 6. 颜色提取不可信兜底

以下情况视为颜色提取不可信：

- `autoBgColor` 和 `autoFgColor` 均缺失
- `colorConfidence` 低于可信阈值
- `fg/bg` 距离极小且整体非常暗，接近当前“同暗色误判”场景

颜色不可信时，不再依赖颜色直接决定样式，而是走复杂度兜底：

- 复杂度低：`black + no stroke`
- 复杂度高：`black + white stroke`

这能消除当前 fallback 默认样式与正常样式混排导致的突兀感。

### 7. 白描边应尽量轻

当前 `BubbleRecord` 和 Saber render 协议只有：

- `strokeEnabled`
- `strokeColor`
- `strokeWidth`

没有 `strokeAlpha` 或更细粒度描边控制。

因此本次“描边尽量轻”的实现方式是：

- 仅在必要时启用描边
- 一旦启用，固定 `strokeWidth = 1`
- 不提高描边宽度
- 不引入额外描边颜色变化

这保证描边存在感最小，只在复杂背景里帮助黑字从底图里分离出来。

## 代码结构调整

主要修改点：

- `src/core/pipeline/service.py`

建议拆分出以下辅助逻辑：

- `_is_tiny_bubble(coords)`
- `_resolve_background_luminance(color)`
- `_is_color_unreliable(color)`
- `_resolve_background_complexity(...)`
- `_resolve_bubble_readability_style(...)`

其中：

- 复杂度特征应在预处理阶段或 bubble 构建前准备好
- `_resolve_bubble_readability_style()` 只消费结构化输入做决策
- `_build_bubbles()` 保持为“逐气泡组装最终 render payload”

## 配置策略

本次不增加新的 `render.readability_mode` 开关。

原因：

- 用户已确认作为新的全局默认
- 保留双模式会增加维护成本和回归矩阵
- 当前项目定位是本地批处理 CLI，更适合收敛默认而不是长期维持多分支样式逻辑

## 测试策略

需要更新或新增以下测试：

- 暗底大框 -> `black + white stroke`
- 亮底干净框 -> `black + no stroke`
- 亮底复杂框 -> `black + white stroke`
- 极小框 -> `black + no stroke`
- `fg/bg` 同暗色且颜色不可信 -> 复杂度兜底
- 颜色缺失 -> 不再落到突兀默认样式

同时需要修改现有依赖白字/黑描边预期的测试用例。

## 样本回归页

建议使用以下本地样本做回归验证：

- `D:/github/translate-reader/翻译测试日漫/德川家康/05/tokugawa#05_005.jpg`
- `D:/github/translate-reader/翻译测试日漫/德川家康/05/tokugawa#05_023.jpg`
- `D:/github/translate-reader/翻译测试日漫/卡姆依传/01/Kamui#01_034.jpg`
- `D:/github/translate-reader/翻译测试日漫/卡姆依传/01/Kamui#01_050.jpg`

覆盖场景：

- 干净对白框
- 复杂灰底/网点背景
- 小框
- 颜色提取 fallback
- 同页多气泡混排

## 验收标准

- 新输出中不再出现 `白字 + 黑描边`
- 正常对白框多数呈现为 `black + no stroke`
- 复杂背景上的黑字可读性不下降
- 同页混排时，样式差异应表现为“合理补偿”，而不是明显风格跳变
- 相关单测通过，样本页人工观感检查通过

## 落地状态

- `2026-05-08` 起，V4 readability 已在代码层替换 V3，成为新的全局默认嵌字可读性策略。
- 输出样式固定收敛为 `black + white stroke` 与 `black + no stroke`。
- 样本页人工观感检查仍需在确认可调用本地批处理和翻译接口后执行。

## 风险与控制

风险：

- 复杂度阈值过敏，导致描边重新变多，画面变脏
- 复杂度阈值过松，导致复杂背景上黑字陷入底图
- 小框阈值过宽，部分应描边的中小框被误杀

控制方式：

- 先用保守阈值实现
- 以回归样本页做人工目检
- 让复杂度只在亮底和中亮度区间提升描边，不覆盖小框优先规则

## 实施顺序

1. 重写可读性决策函数，收敛为黑字双样式
2. 引入复杂度特征并接入决策
3. 更新单元测试
4. 用指定样本页做人工回归
5. 将 V4 作为全局默认发布
