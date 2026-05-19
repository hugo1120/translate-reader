# Quality Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 系统性提升 translate_manga_v2 的翻译质量，通过增强质检检测、优化气泡分组、改进嵌字质量，减少翻译残留、过度合并和渲染问题。

**Context:** 用户在翻译《卡姆依传》时发现：
1. 日文残留未被检测（如 `"かん ねん なされ。"` → `"堪念なされ."`）
2. 气泡过度合并导致翻译质量下降
3. 嵌字质量不稳定，横排/竖排样式混用

**Architecture:**
- P0：在质检流程增加硬性字符检查，在翻译流程增加即时验证
- P1：启用 Saber 的边缘距离比例检测，通过配置传递参数
- P2：在嵌字流程增加全局方向判断，优化渲染参数和复杂度阈值

**Tech Stack:** Python 3.10, pytest, Saber-Translator, OpenAI-compatible API

---

## Phase 1: P0 翻译质量检测增强

### Task 1: 增加字符残留检测函数

**Files:**
- Modify: `src/translate_manga/cli/quality_review.py`
- Modify: `tests/test_quality_review.py`

- [ ] **Step 1: 在 quality_review.py 增加字符残留检测函数**

```python
def _detect_untranslated_chars(translated_text, original_text=""):
    """
    检测译文中的残留字符（日文假名、日文汉字、英文字母）

    Returns:
        dict: {
            "has_residue": bool,
            "residue_ratio": float,
            "residue_count": int,
            "residue_types": list[str]  # ["hiragana", "katakana", "kanji", "latin"]
        }
    """
    # 日文平假名/片假名
    hiragana_pattern = re.compile(r'[\u3040-\u309f]')
    katakana_pattern = re.compile(r'[\u30a0-\u30ff]')

    # 日文汉字（排除中文常用字）- 使用白名单策略
    # 检测连续3+个拉丁字母（排除常见拟声词）
    latin_pattern = re.compile(r'[A-Za-z]{3,}')

    # 常见拟声词白名单
    onomatopoeia = {"啊", "呀", "哦", "嗯", "唔", "咦", "哎", "嘿"}

    # 实现检测逻辑...
```

- [ ] **Step 2: 在 load_reviewable_page_records() 中调用检测**

在第 264-298 行的 `load_reviewable_page_records()` 函数中，对每个 record 的 `translatedTexts` 进行检测：

```python
for translated_text in translated_texts:
    residue_info = _detect_untranslated_chars(translated_text, original_texts)
    if residue_info["has_residue"]:
        if "quality_untranslated_source" not in record.get("reviewReasons", []):
            record.setdefault("reviewReasons", []).append("quality_untranslated_source")
```

- [ ] **Step 3: 写测试用例**

在 `tests/test_quality_review.py` 增加：

```python
def test_detect_untranslated_chars_hiragana():
    result = _detect_untranslated_chars("堪念なされ.")
    assert result["has_residue"] is True
    assert "hiragana" in result["residue_types"]

def test_detect_untranslated_chars_clean_chinese():
    result = _detect_untranslated_chars("请稍等。")
    assert result["has_residue"] is False
```

- [ ] **Step 4: 运行测试确认 green**

```bash
python -m pytest tests/test_quality_review.py::test_detect_untranslated_chars_hiragana -v
python -m pytest tests/test_quality_review.py::test_detect_untranslated_chars_clean_chinese -v
```

### Task 2: 增强 LLM 质检提示词

**Files:**
- Modify: `src/translate_manga/cli/quality_review.py`

- [ ] **Step 1: 修改 _QUALITY_REVIEW_SYSTEM_PROMPT**

在第 31-35 行增强提示词：

```python
_QUALITY_REVIEW_SYSTEM_PROMPT = """你是专业漫画汉化校对。你的任务是找出"值得重翻并重新嵌字"的页，而不是润色所有句子。

只标记明确问题：
- 误译：译文与原文含义不符
- 人物/术语前后不一致：同一角色或术语在不同页面翻译不同
- 译文残留原文：译文中不应出现日文假名（ひらがな、カタカナ）、日文汉字或英文单词（拟声词除外）
- OCR 噪声导致译错：OCR 识别错误导致翻译错误
- 中文明显不通顺：语法错误或表达不自然
- 气泡内译文明显过长：译文长度超出气泡容量
- 提示词语言/阅读方向不匹配：横排/竖排样式与内容不符

不要因为个人措辞偏好、标点风格、轻微口语差异而标记。
只输出 JSON，不输出解释文本。

正例（需要标记）：
- 原文："こんにちは" → 译文："こんにちは" （残留日文）
- 原文："Hello" → 译文："Hello" （残留英文）

反例（不需要标记）：
- 原文："ドキドキ" → 译文："怦怦" （正确翻译拟声词）
- 原文："OK" → 译文："OK" （常见拟声词保留）
"""
```

- [ ] **Step 2: 在 _build_review_messages() 中增加原文语言提示**

在第 313-342 行的 `_build_review_messages()` 函数中：

```python
user_prompt = (
    f"请审核以下漫画页的汉化质量。原文语言：{style_profile.get('source_language', 'japanese')}。"
    "只返回需要重翻的页。\n"
    # ... 其余内容
)
```

- [ ] **Step 3: 验证提示词效果**

使用 `Kamui#01_046.json` 测试：

```bash
python -m translate_manga.cli.service quality-review --output-dir "D:/github/translate-reader/翻译测试日漫/卡姆依传/out"
```

### Task 3: 翻译后即时验证

**Files:**
- Modify: `src/translate_manga/core/translate/openai_compatible.py`
- Modify: `tests/test_openai_compatible.py` (if exists)

- [ ] **Step 1: 在 openai_compatible.py 增加验证函数**

在第 42 行 `_CJK_PATTERN` 定义后增加：

```python
def _validate_translation(translated_text, original_text=""):
    """
    验证译文质量，检测残留字符

    Returns:
        tuple: (is_valid: bool, reason: str)
    """
    # 复用 quality_review.py 的检测逻辑
    from translate_manga.cli.quality_review import _detect_untranslated_chars

    residue_info = _detect_untranslated_chars(translated_text, original_text)
    if residue_info["has_residue"]:
        return False, f"检测到残留字符: {', '.join(residue_info['residue_types'])}"

    return True, ""
```

- [ ] **Step 2: 在 _parse_numbered_translations() 后调用验证**

在第 200-218 行的 `_parse_numbered_translations()` 函数返回前增加验证：

```python
# 验证译文质量
for i, translation in enumerate(translations):
    is_valid, reason = _validate_translation(translation, original_texts[i] if i < len(original_texts) else "")
    if not is_valid:
        translations[i] = TRANSLATION_FAILURE_TEXT
        # 记录日志
        print(f"[WARNING] 译文验证失败: {reason}")
```

- [ ] **Step 3: 测试验证逻辑**

```python
def test_validate_translation_with_residue():
    is_valid, reason = _validate_translation("堪念なされ.")
    assert is_valid is False
    assert "hiragana" in reason.lower() or "残留" in reason

def test_validate_translation_clean():
    is_valid, reason = _validate_translation("请稍等。")
    assert is_valid is True
```

- [ ] **Step 4: 运行测试确认 green**

```bash
python -m pytest tests/test_openai_compatible.py -v
```

---

## Phase 2: P1 气泡分组优化

### Task 4: 增加检测配置段

**Files:**
- Modify: `config/defaults.json`
- Modify: `config/local.example.json`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 在 defaults.json 增加 detection 配置段**

在第 115 行（文件末尾）前增加：

```json
"detection": {
  "edge_ratio_threshold": 2.0,
  "reading_order": "rtl"
}
```

- [ ] **Step 2: 同步更新 local.example.json**

在 `config/local.example.json` 增加相同配置段。

- [ ] **Step 3: 在 settings.py 增加配置读取函数**

```python
def resolve_detection_config(settings=None):
    """
    解析检测配置

    Returns:
        dict: {
            "edge_ratio_threshold": float,
            "reading_order": str
        }
    """
    if settings is None:
        settings = load_settings()

    detection = settings.get("detection") or {}
    return {
        "edge_ratio_threshold": float(detection.get("edge_ratio_threshold", 2.0)),
        "reading_order": str(detection.get("reading_order", "rtl")).strip().lower(),
    }
```

- [ ] **Step 4: 写测试用例**

在 `tests/test_settings.py` 增加：

```python
def test_resolve_detection_config_defaults():
    config = resolve_detection_config()
    assert config["edge_ratio_threshold"] == 2.0
    assert config["reading_order"] == "rtl"

def test_resolve_detection_config_custom():
    settings = {"detection": {"edge_ratio_threshold": 1.5}}
    config = resolve_detection_config(settings)
    assert config["edge_ratio_threshold"] == 1.5
```

- [ ] **Step 5: 运行测试确认 green**

```bash
python -m pytest tests/test_settings.py::test_resolve_detection_config_defaults -v
python -m pytest tests/test_settings.py::test_resolve_detection_config_custom -v
```

### Task 5: 传递检测参数到 Saber

**Files:**
- Modify: `src/translate_manga/core/detection/service.py`
- Modify: `src/translate_manga/integrations/saber_loader.py`

- [ ] **Step 1: 修改 detection/service.py 传递参数**

```python
from translate_manga.config.settings import resolve_detection_config

def detect_page(image_path):
    detection_config = resolve_detection_config()
    return run_saber_task("detect", {
        "image_path": image_path,
        "edge_ratio_threshold": detection_config["edge_ratio_threshold"],
        "reading_order": detection_config["reading_order"],
    })
```

- [ ] **Step 2: 修改 saber_loader.py 的 detect 脚本**

在第 27-62 行的 `detect` 脚本中，修改 `get_bubble_detection_result_with_auto_directions()` 调用：

```python
payload = json.loads(sys.argv[1])
image = Image.open(payload["image_path"]).convert("RGB")
result = get_bubble_detection_result_with_auto_directions(
    image,
    right_to_left=reading_order_to_right_to_left(payload),
    edge_ratio_threshold=float(payload.get("edge_ratio_threshold", 0.0)),
)
```

- [ ] **Step 3: 验证参数传递**

在 Saber 的 `get_bubble_detection_result_with_auto_directions()` 函数中确认参数被正确接收。

- [ ] **Step 4: 测试检测效果**

使用测试图片验证气泡分组效果：

```bash
python -m translate_manga.cli.service translate --input-dir "测试目录" --output-dir "测试输出"
```

对比优化前后的 `_debug/pages/*.json` 中的 `bubbleCoords` 数量。

---

## Phase 3: P2 嵌字质量改进

### Task 6: 增加嵌字配置选项

**Files:**
- Modify: `config/defaults.json`
- Modify: `config/local.example.json`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: 在 defaults.json 的 render 段增加配置**

在第 72-107 行的 `render` 配置段中：

```json
"render": {
  "font_family": "fonts/思源黑体SourceHanSansK-Bold.TTF",
  "layout_mode": "vertical",
  "force_uniform_layout": false,
  "stroke_enabled": true,
  "stroke_color": "#FFFFFF",
  "stroke_width": 1.2,
  "line_spacing": 0.88,
  "text_align": "center",
  "vertical_layout": {
    "font_family": "fonts/汉仪正圆-65W.TTF",
    "stroke_width": 1.1,
    "line_spacing": 1.06,
    "auto_font": {
      "min_size": 14,
      "max_size": 60,
      "padding_ratio": 0.86
    }
  },
  // ... 其余配置
}
```

- [ ] **Step 2: 同步更新 local.example.json**

- [ ] **Step 3: 在 settings.py 增加配置读取**

```python
def resolve_render_config(settings=None):
    # 在现有函数中增加 force_uniform_layout 读取
    render = settings.get("render") or {}
    return {
        # ... 现有配置
        "force_uniform_layout": bool(render.get("force_uniform_layout", False)),
        "stroke_width": float(render.get("stroke_width", 1.2)),
        "line_spacing": float(render.get("line_spacing", 0.88)),
    }
```

- [ ] **Step 4: 写测试用例**

```python
def test_resolve_render_config_force_uniform_layout():
    settings = {"render": {"force_uniform_layout": True}}
    config = resolve_render_config(settings)
    assert config["force_uniform_layout"] is True
```

- [ ] **Step 5: 运行测试确认 green**

### Task 7: 实现强制样式分离

**Files:**
- Modify: `src/translate_manga/core/pipeline/service.py`

- [ ] **Step 1: 在 _build_bubbles() 增加全局方向判断**

在第 569-616 行的 `_build_bubbles()` 函数开头增加：

```python
def _build_bubbles(detection, ocr, translated_texts, *, layout_mode_override=None, font_family_override=None):
    style = _resolve_render_style(layout_mode_override=layout_mode_override, font_family_override=font_family_override)
    vertical_style = _resolve_vertical_render_style()

    # 读取配置
    settings = load_settings()
    render_config = settings.get("render") or {}
    force_uniform_layout = bool(render_config.get("force_uniform_layout", False))

    # 如果启用强制统一样式且为 auto 模式
    dominant_direction = None
    if force_uniform_layout and style["layoutMode"] == "auto":
        auto_directions = detection.get("autoDirections", []) or []
        if auto_directions:
            vertical_count = sum(1 for d in auto_directions if _normalize_layout_direction(d) == "vertical")
            # 60% 阈值判断主导方向
            dominant_direction = "vertical" if vertical_count >= len(auto_directions) * 0.6 else "horizontal"

    bubbles = []
    # ... 现有代码
```

- [ ] **Step 2: 在气泡构建循环中应用主导方向**

在第 587 行修改：

```python
direction = dominant_direction if dominant_direction else (
    auto_direction if style["layoutMode"] == "auto" else style["layoutMode"]
)
```

- [ ] **Step 3: 测试样式分离效果**

使用混合横排/竖排的测试页面验证：

```bash
python -m translate_manga.cli.service translate --input-dir "测试目录" --output-dir "测试输出"
```

检查 `_debug/pages/*.json` 中所有气泡的 `direction` 是否统一。

### Task 8: 优化背景复杂度判断

**Files:**
- Modify: `src/translate_manga/core/pipeline/service.py`

- [ ] **Step 1: 调整 _resolve_background_complexity() 阈值**

在第 197-206 行修改：

```python
def _resolve_background_complexity(color):
    gray_stddev = float(color.get("grayStdDev", 0.0) or 0.0)
    edge_density = float(color.get("edgeDensity", 0.0) or 0.0)
    dark_pixel_ratio = float(color.get("darkPixelRatio", 0.0) or 0.0)
    return max(
        min(1.0, gray_stddev / 28.0),  # 32.0 → 28.0
        min(1.0, edge_density / 0.14),  # 0.16 → 0.14
        min(1.0, dark_pixel_ratio / 0.15),  # 0.18 → 0.15
    )
```

- [ ] **Step 2: 测试复杂度判断效果**

对比优化前后的描边启用率：

```bash
# 统计 _debug/pages/*.json 中 strokeEnabled=true 的比例
```

- [ ] **Step 3: 验证渲染效果**

使用复杂背景的测试页面验证描边效果是否改善。

---

## Phase 4: 测试与验证

### Task 9: 更新单元测试

**Files:**
- Modify: `tests/test_quality_review.py`
- Modify: `tests/test_settings.py`
- Create: `tests/test_translation_validation.py`

- [ ] **Step 1: 补充 quality_review 测试**

```python
def test_load_reviewable_page_records_with_residue_detection():
    # 测试字符残留检测是否正确标记 reviewReasons
    pass

def test_quality_review_system_prompt_includes_residue_check():
    # 测试提示词是否包含残留检测说明
    assert "日文假名" in _QUALITY_REVIEW_SYSTEM_PROMPT
    assert "残留" in _QUALITY_REVIEW_SYSTEM_PROMPT
```

- [ ] **Step 2: 补充 settings 测试**

```python
def test_resolve_detection_config():
    # 已在 Task 4 完成
    pass

def test_resolve_render_config_with_new_options():
    # 已在 Task 6 完成
    pass
```

- [ ] **Step 3: 创建翻译验证测试**

```python
def test_validate_translation_detects_hiragana():
    pass

def test_validate_translation_detects_katakana():
    pass

def test_validate_translation_allows_clean_chinese():
    pass
```

- [ ] **Step 4: 运行所有测试**

```bash
python -m pytest tests/ -v
```

### Task 10: 集成测试与验证

**Files:**
- N/A (使用真实数据测试)

- [ ] **Step 1: 使用 Kamui#01_046.json 验证残留检测**

```bash
# 1. 清空质检记录
rm "D:/github/translate-reader/翻译测试日漫/卡姆依传/out/_debug/quality-review.tsv"

# 2. 运行质检
python -m translate_manga.cli.service quality-review --output-dir "D:/github/translate-reader/翻译测试日漫/卡姆依传/out"

# 3. 检查 Kamui#01_046.json 是否被标记
cat "D:/github/translate-reader/翻译测试日漫/卡姆依传/out/_debug/quality-review.tsv" | grep "046"
```

- [ ] **Step 2: 对比气泡分组效果**

```bash
# 1. 备份当前检测结果
cp -r "D:/github/translate-reader/翻译测试日漫/测试目录/out/_debug/pages" "backup_pages_before"

# 2. 修改配置启用边缘检测
# 在 config/local.json 设置 "edge_ratio_threshold": 2.0

# 3. 重新检测
python -m translate_manga.cli.service translate --input-dir "测试目录" --output-dir "测试输出" --overwrite

# 4. 对比气泡数量
python -c "
import json
from pathlib import Path
before = list(Path('backup_pages_before').glob('*.json'))
after = list(Path('测试输出/_debug/pages').glob('*.json'))
for b, a in zip(before, after):
    before_count = len(json.loads(b.read_text())['bubbleCoords'])
    after_count = len(json.loads(a.read_text())['bubbleCoords'])
    print(f'{b.name}: {before_count} → {after_count}')
"
```

- [ ] **Step 3: 对比嵌字质量**

```bash
# 1. 启用 force_uniform_layout
# 在 config/local.json 设置 "force_uniform_layout": true

# 2. 重新渲染
python -m translate_manga.cli.service translate --input-dir "测试目录" --output-dir "测试输出" --overwrite

# 3. 人工对比渲染效果
```

- [ ] **Step 4: 回归测试**

```bash
# 随机抽取 100 个已翻译页面
python -c "
import random
from pathlib import Path
pages = list(Path('D:/github/translate-reader/翻译测试日漫/卡姆依传/out/_debug/pages').glob('*.json'))
sample = random.sample(pages, min(100, len(pages)))
print('\n'.join(str(p) for p in sample))
" > sample_pages.txt

# 运行质检
python -m translate_manga.cli.service quality-review --output-dir "D:/github/translate-reader/翻译测试日漫/卡姆依传/out"

# 统计标记率
python -c "
import csv
with open('D:/github/translate-reader/翻译测试日漫/卡姆依传/out/_debug/quality-review.tsv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    flagged = list(reader)
    print(f'标记页面数: {len(flagged)}')
    print(f'标记率: {len(flagged) / 100 * 100:.1f}%')
"
```

---

## 验证标准

### P0 验证标准
- [ ] `Kamui#01_046.json` 被正确标记为 `quality_untranslated_source`
- [ ] 字符残留检测召回率 ≥ 90%（使用人工标注的测试集）
- [ ] 误报率 ≤ 5%（拟声词不被误判）

### P1 验证标准
- [ ] 启用边缘检测后，平均气泡数量增加 10-30%
- [ ] 过度合并案例减少 ≥ 30%（人工评估）
- [ ] 翻译质量评分提升（使用 LLM 评分）

### P2 验证标准
- [ ] 启用 `force_uniform_layout` 后，同一页内所有气泡方向统一
- [ ] 渲染清晰度提升（人工主观评分）
- [ ] 描边启用率提升 10-20%（复杂背景页面）

### 性能验证标准
- [ ] 单页处理耗时增加 < 10%
- [ ] 内存占用增加 < 5%

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 | 负责人 |
|------|------|---------|--------|
| 字符检测误报 | 拟声词被误判为残留 | 建立白名单，可配置阈值 | Task 1 |
| 气泡分割过度 | 单个气泡被拆分 | 保守调参，提供配置开关 | Task 5 |
| 性能下降 | 增加验证步骤导致变慢 | 仅对可疑页面深度检测 | Task 3 |
| 兼容性问题 | 旧配置文件不兼容 | 提供默认值，向后兼容 | Task 4, 6 |
| Saber API 变更 | 参数传递失败 | 版本锁定，增加参数验证 | Task 5 |

---

## 实施时间线

| 阶段 | 任务 | 预计耗时 | 依赖 |
|------|------|---------|------|
| Phase 1 | Task 1-3 | 1-2 天 | 无 |
| Phase 2 | Task 4-5 | 2-3 天 | Phase 1 |
| Phase 3 | Task 6-8 | 2-3 天 | Phase 2 |
| Phase 4 | Task 9-10 | 1-2 天 | Phase 1-3 |
| **总计** | | **6-10 天** | |

---

## 交付清单

- [ ] 修改后的 `quality_review.py`（字符残留检测）
- [ ] 修改后的 `openai_compatible.py`（即时验证）
- [ ] 修改后的 `defaults.json` 和 `local.example.json`（新配置项）
- [ ] 修改后的 `detection/service.py`（参数传递）
- [ ] 修改后的 `saber_loader.py`（Saber 集成）
- [ ] 修改后的 `pipeline/service.py`（样式分离、复杂度优化）
- [ ] 更新后的单元测试
- [ ] 验证报告（包含对比数据）
- [ ] 用户文档更新（配置说明）

---

## 后续优化方向

1. **P3 整体流程优化**（未包含在本计划）
   - 在渲染前增加译文验证步骤
   - 译文长度检查（过长/过短）
   - 标点符号合理性检查

2. **批量重检工具**
   - 对已翻译的 4894 个页面进行批量质检
   - 生成质量报告和重翻优先级列表

3. **可视化质检工具**
   - 在 Web UI 中展示质检结果
   - 支持人工标注和反馈

4. **自适应参数调优**
   - 根据历史数据自动调整阈值
   - A/B 测试不同参数组合
