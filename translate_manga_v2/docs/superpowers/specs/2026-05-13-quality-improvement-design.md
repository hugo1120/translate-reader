# 质量改进系统设计

## 目标

系统性提升 translate_manga_v2 的翻译质量，解决以下核心问题：

1. **翻译残留未检测**：日文假名、英文字母残留在译文中
2. **气泡过度合并**：多个独立气泡被合并为一个翻译单元
3. **嵌字质量不稳定**：横排/竖排样式混用，渲染效果差

## 背景

### 问题案例

**案例 1：翻译残留**
- 文件：`Kamui#01_046.json`
- 原文：`"かん ねん なされ。"` (日文)
- 译文：`"堪念なされ."` (日文残留)
- OCR 置信度：0.999
- 质检状态：`needsReview: false` ❌

**案例 2：气泡过度合并**
- 现象：3 个独立对话气泡被合并为 1 个翻译单元
- 原因：`edge_ratio_threshold=0.0` 禁用异常边检测
- 影响：翻译质量下降，上下文混乱

**案例 3：嵌字样式混用**
- 现象：同一页内横排和竖排样式混用
- 原因：`layoutMode="auto"` 时每个气泡独立判断
- 影响：视觉不统一，阅读体验差

### 根因分析

| 问题 | 根因 | 影响范围 |
|------|------|---------|
| 翻译残留 | 质检系统完全依赖 LLM，无硬性字符检查 | 所有翻译页面 |
| 气泡过度合并 | Saber 默认 `edge_ratio_threshold=0.0`，未从配置传入 | 所有检测页面 |
| 嵌字样式混用 | `auto` 模式下每个气泡独立判断方向 | 使用 `auto` 模式的页面 |

## 设计原则

1. **向后兼容**：新功能通过配置开关控制，默认保持现有行为
2. **可测试性**：所有核心逻辑可单元测试
3. **可配置性**：关键阈值可通过配置文件调整
4. **性能优先**：避免引入显著性能开销（< 10%）
5. **渐进式改进**：分阶段实施，每个阶段独立可验证

## 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Translation Pipeline                    │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Detection   │    │  Translation  │    │    Render     │
│   (P1 优化)   │    │  (P0 增强)    │    │  (P2 改进)    │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Saber + Edge  │    │ Char Residue  │    │ Uniform Style │
│   Detection   │    │   Detection   │    │  + Optimized  │
│               │    │ + Validation  │    │   Rendering   │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
                     ┌───────────────┐
                     │ Quality Review│
                     │  (P0 增强)    │
                     └───────────────┘
```

### 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `quality_review.py` | 质检系统，增加字符残留检测 | 翻译页面记录 | 质检报告 TSV |
| `openai_compatible.py` | 翻译服务，增加即时验证 | 原文 | 译文（验证后） |
| `detection/service.py` | 检测服务，传递边缘检测参数 | 图片路径 | 气泡坐标 |
| `saber_loader.py` | Saber 集成，传递参数到 Saber | 检测参数 | Saber 结果 |
| `pipeline/service.py` | 渲染服务，强制样式分离 | 检测+翻译结果 | 渲染图片 |

## 详细设计

### P0: 翻译质量检测增强

#### 1. 字符残留检测

**设计目标**：在质检流程中增加硬性字符检查，捕获 LLM 漏检的残留

**检测规则**：

```python
# 1. 日文平假名
hiragana_pattern = r'[\u3040-\u309f]'

# 2. 日文片假名
katakana_pattern = r'[\u30a0-\u30ff]'

# 3. 日文汉字（排除中文常用字）
# 策略：检测日文特有汉字，如「堪」「念」等
# 实现：使用白名单策略，排除 GB2312 常用字

# 4. 英文字母（排除拟声词）
latin_pattern = r'[A-Za-z]{3,}'
# 白名单：OK, NG, SOS 等常见拟声词
```

**阈值设计**：

```python
# 残留判定条件（满足任一即判定为残留）
1. 残留字符比例 ≥ 30%
2. 残留字符绝对数量 ≥ 5 个
3. 包含日文假名（任意数量）
```

**集成点**：

```python
# 在 load_reviewable_page_records() 中调用
for record in records:
    for translated_text in record["translatedTexts"]:
        residue_info = _detect_untranslated_chars(translated_text)
        if residue_info["has_residue"]:
            record.setdefault("reviewReasons", []).append("quality_untranslated_source")
```

#### 2. LLM 提示词增强

**增强内容**：

```
原提示词：
"只标记明确问题：误译、人物/术语前后不一致、译文残留日文或英文..."

增强后：
"只标记明确问题：
- 误译：译文与原文含义不符
- 人物/术语前后不一致：同一角色或术语在不同页面翻译不同
- 译文残留原文：译文中不应出现日文假名（ひらがな、カタカナ）、
  日文汉字或英文单词（拟声词除外）

正例（需要标记）：
- 原文："こんにちは" → 译文："こんにちは" （残留日文）
- 原文："Hello" → 译文："Hello" （残留英文）

反例（不需要标记）：
- 原文："ドキドキ" → 译文："怦怦" （正确翻译拟声词）
- 原文："OK" → 译文："OK" （常见拟声词保留）"
```

#### 3. 翻译后即时验证

**验证时机**：在 `_parse_numbered_translations()` 返回前

**验证逻辑**：

```python
def _validate_translation(translated_text, original_text=""):
    # 1. 字符残留检测
    residue_info = _detect_untranslated_chars(translated_text, original_text)
    if residue_info["has_residue"]:
        return False, f"检测到残留字符: {residue_info['residue_types']}"

    # 2. 长度检查（可选）
    if len(translated_text) > len(original_text) * 3:
        return False, "译文过长"

    # 3. 标点符号检查（可选）
    if translated_text.count("。") > 5:
        return False, "标点过多"

    return True, ""
```

**失败处理**：

```python
if not is_valid:
    translations[i] = TRANSLATION_FAILURE_TEXT
    print(f"[WARNING] 译文验证失败: {reason}")
    # 触发 OCR 重试或人工审核
```

### P1: 气泡分组优化

#### 4. 边缘距离比例检测

**原理**：Saber 的 `textline_merge.py` 已支持 `edge_ratio_threshold` 参数

**工作机制**：

```python
# 对于每个文本行节点
for node in G.nodes():
    neighbors = list(G.neighbors(node))
    if len(neighbors) >= 2:
        # 计算到所有邻居的距离
        neighbor_distances = [(neighbor, distance) for neighbor in neighbors]
        neighbor_distances.sort(key=lambda x: x[1])

        min_dist = neighbor_distances[0][1]

        # 如果距离差异 > edge_ratio_threshold 倍，断开连接
        for neighbor, dist in neighbor_distances[1:]:
            ratio = dist / min_dist
            if ratio > edge_ratio_threshold:
                G.remove_edge(node, neighbor)
```

**参数传递链路**：

```
config/defaults.json
    ↓ (resolve_detection_config)
detection/service.py
    ↓ (run_saber_task)
saber_loader.py
    ↓ (sys.argv[1])
Saber Python 脚本
    ↓ (edge_ratio_threshold=...)
get_bubble_detection_result_with_auto_directions()
```

**推荐值**：

```json
{
  "detection": {
    "edge_ratio_threshold": 2.0  // 距离差异 > 2 倍时断开
  }
}
```

**效果预期**：

- 减少 30-50% 的过度合并
- 平均气泡数量增加 10-30%
- 翻译质量提升（更精确的上下文）

### P2: 嵌字质量改进

#### 5. 强制样式分离

**设计目标**：同一页内统一使用一种样式（横排或竖排）

**判断逻辑**：

```python
# 1. 统计页面主导方向
auto_directions = detection.get("autoDirections", [])
vertical_count = sum(1 for d in auto_directions if d == "vertical")

# 2. 60% 阈值判断
dominant_direction = "vertical" if vertical_count >= len(auto_directions) * 0.6 else "horizontal"

# 3. 强制所有气泡使用主导方向
for bubble in bubbles:
    bubble["direction"] = dominant_direction
    bubble["textDirection"] = dominant_direction
```

**配置开关**：

```json
{
  "render": {
    "force_uniform_layout": false  // 默认关闭，保持现有行为
  }
}
```

**效果预期**：

- 同一页内样式统一
- 视觉一致性提升
- 阅读体验改善

#### 6. 优化渲染参数

**调整内容**：

```json
{
  "render": {
    "stroke_width": 1.2,      // 1.0 → 1.2 (横排描边加粗)
    "line_spacing": 0.88,     // 0.84 → 0.88 (横排行间距增加)
    "vertical_layout": {
      "stroke_width": 1.1,    // 1.0 → 1.1 (竖排描边加粗)
      "line_spacing": 1.06    // 1.04 → 1.06 (竖排行间距增加)
    }
  }
}
```

**调整理由**：

- 描边加粗：提升文字清晰度，特别是在复杂背景上
- 行间距增加：避免文字拥挤，提升可读性

#### 7. 改进背景复杂度判断

**当前阈值**：

```python
gray_stddev / 32.0
edge_density / 0.16
dark_pixel_ratio / 0.18
```

**优化后阈值**：

```python
gray_stddev / 28.0      // 更敏感
edge_density / 0.14     // 更敏感
dark_pixel_ratio / 0.15 // 更敏感
```

**效果预期**：

- 描边启用率提升 10-20%
- 复杂背景页面的文字清晰度提升

## 配置设计

### 新增配置项

```json
{
  "detection": {
    "edge_ratio_threshold": 2.0,
    "reading_order": "rtl"
  },
  "render": {
    "force_uniform_layout": false,
    "stroke_width": 1.2,
    "line_spacing": 0.88,
    "vertical_layout": {
      "stroke_width": 1.1,
      "line_spacing": 1.06
    }
  }
}
```

### 配置优先级

```
local.json > defaults.json > 硬编码默认值
```

### 向后兼容

- 所有新配置项都有默认值
- 默认行为与现有系统一致
- 用户可选择性启用新功能

## 数据流设计

### 检测流程

```
Image
  ↓
detect_page(image_path)
  ↓ (读取 detection config)
run_saber_task("detect", {
  "image_path": ...,
  "edge_ratio_threshold": 2.0,
  "reading_order": "rtl"
})
  ↓ (Saber Python 脚本)
get_bubble_detection_result_with_auto_directions(
  image,
  right_to_left=True,
  edge_ratio_threshold=2.0
)
  ↓
{
  "bubbleCoords": [...],
  "autoDirections": [...],
  "textlinesPerBubble": [...]
}
```

### 翻译流程

```
Original Texts
  ↓
translate_batch(texts)
  ↓
_parse_numbered_translations(response)
  ↓ (即时验证)
_validate_translation(translated_text)
  ↓ (验证失败)
TRANSLATION_FAILURE_TEXT
  ↓ (验证成功)
Translated Texts
```

### 质检流程

```
Output Dir
  ↓
load_reviewable_page_records(output_dir)
  ↓ (字符残留检测)
_detect_untranslated_chars(translated_text)
  ↓ (检测到残留)
record["reviewReasons"].append("quality_untranslated_source")
  ↓
run_quality_review(records)
  ↓ (LLM 质检)
_call_reviewer(messages)
  ↓
write_quality_review_tsv(entries)
```

## 性能设计

### 性能目标

- 单页处理耗时增加 < 10%
- 内存占用增加 < 5%
- 质检吞吐量不下降

### 性能优化策略

1. **字符残留检测**：使用正则表达式，O(n) 复杂度
2. **边缘检测**：在 Saber 内部实现，无额外开销
3. **样式分离**：仅增加一次遍历，O(n) 复杂度
4. **缓存策略**：配置读取结果缓存

### 性能监控

```python
import time

start = time.time()
# 执行操作
elapsed = time.time() - start

if elapsed > threshold:
    print(f"[PERF] 操作耗时: {elapsed:.2f}s")
```

## 测试设计

### 单元测试

```python
# test_quality_review.py
def test_detect_untranslated_chars_hiragana()
def test_detect_untranslated_chars_katakana()
def test_detect_untranslated_chars_clean_chinese()
def test_detect_untranslated_chars_onomatopoeia()

# test_settings.py
def test_resolve_detection_config_defaults()
def test_resolve_detection_config_custom()
def test_resolve_render_config_force_uniform_layout()

# test_translation_validation.py
def test_validate_translation_detects_residue()
def test_validate_translation_allows_clean()
```

### 集成测试

```python
# 使用真实数据测试
def test_kamui_046_residue_detection():
    # 验证 Kamui#01_046.json 被正确标记
    pass

def test_bubble_grouping_optimization():
    # 对比优化前后的气泡数量
    pass

def test_uniform_layout_enforcement():
    # 验证同一页内样式统一
    pass
```

### 回归测试

```python
# 随机抽取 100 个已翻译页面
def test_quality_review_regression():
    # 统计标记率变化
    pass

def test_performance_regression():
    # 验证性能无显著下降
    pass
```

## 错误处理

### 字符残留检测错误

```python
try:
    residue_info = _detect_untranslated_chars(text)
except Exception as e:
    print(f"[ERROR] 字符残留检测失败: {e}")
    residue_info = {"has_residue": False}  # 降级处理
```

### 配置读取错误

```python
try:
    edge_ratio_threshold = float(config.get("edge_ratio_threshold", 2.0))
except (TypeError, ValueError):
    edge_ratio_threshold = 2.0  # 使用默认值
```

### Saber 参数传递错误

```python
try:
    result = run_saber_task("detect", params)
except Exception as e:
    print(f"[ERROR] Saber 检测失败: {e}")
    # 降级到不带参数的检测
    result = run_saber_task("detect", {"image_path": image_path})
```

## 监控与日志

### 日志级别

```python
# INFO: 正常流程
print(f"[INFO] 检测到 {len(bubbles)} 个气泡")

# WARNING: 可疑情况
print(f"[WARNING] 译文验证失败: {reason}")

# ERROR: 错误情况
print(f"[ERROR] 字符残留检测失败: {e}")
```

### 关键指标

```python
# 质检指标
- 标记页面数
- 标记率（标记页面数 / 总页面数）
- 各类问题分布（mistranslation, untranslated_source, etc.）

# 性能指标
- 单页处理耗时
- 内存占用
- 质检吞吐量（页面数 / 秒）

# 质量指标
- 残留检测召回率
- 残留检测误报率
- 气泡分组准确率
```

## 部署与回滚

### 部署策略

1. **灰度发布**：先在小范围数据集测试
2. **配置开关**：通过配置控制新功能启用
3. **监控告警**：监控性能和质量指标

### 回滚方案

1. **配置回滚**：关闭新功能配置开关
2. **代码回滚**：Git revert 到上一个稳定版本
3. **数据回滚**：使用备份的质检结果

## 文档更新

### 用户文档

- 配置说明：新增配置项的含义和推荐值
- 使用指南：如何启用新功能
- 故障排查：常见问题和解决方案

### 开发文档

- API 文档：新增函数的参数和返回值
- 架构文档：模块职责和数据流
- 测试文档：测试用例和验证标准

## 后续优化

1. **自适应阈值**：根据历史数据自动调整阈值
2. **可视化质检**：在 Web UI 中展示质检结果
3. **批量重检工具**：对已翻译页面进行批量质检
4. **A/B 测试**：对比不同参数组合的效果
