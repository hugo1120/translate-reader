# V4 Readability Implementation Plan

> 历史实现计划：该计划最初面向旧 `translate_manga_cli`，相关策略随后进入 `translate_manga_v2`。当前开发与同步以 `translate_manga_v2` 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `translate_manga_cli` 的嵌字可读性策略替换为新的全局默认 `V4 readability`，统一为黑字双样式，并用亮度、复杂度和小框优先规则改善漫画观感。

**Architecture:** 复杂度特征不修改 Saber render 协议，而是在 Python 侧 `src/core/color/service.py` 对颜色结果做二次增强，并沿现有 `bubbleColors` 预处理缓存链路向下游传递。样式决策仍集中在 `src/core/pipeline/service.py`，只输出 `black + white stroke` 与 `black + no stroke` 两种最终 payload。

**Tech Stack:** Python 3.10、Pillow、pytest、现有 Saber 子进程桥接

---

**接手说明:** 本轮接手时 `service.py` 与 `test_pipeline_service.py` 已存在未提交的 V4 样式决策改动，因此 Task 1/2 的样式测试 RED 阶段未在本轮重新回滚复现；本轮补做了颜色复杂度链路的 RED/GREEN，以及 V4 样式测试和 pipeline 全量验证。

### Task 1: 先用测试锁定 V4 样式决策

**Files:**
- Modify: `D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py`
- Test: `D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py`

- [x] **Step 1: 在 `test_pipeline_service.py` 新增 V4 样式决策测试**

```python
def test_build_bubbles_uses_black_text_with_white_stroke_for_dark_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#eeeeee",
                    "bgColor": "#111111",
                    "autoFgColor": [238, 238, 238],
                    "autoBgColor": [17, 17, 17],
                    "colorConfidence": 0.95,
                    "grayStdDev": 14.0,
                    "edgeDensity": 0.08,
                    "darkPixelRatio": 0.41,
                }
            ],
        },
        {
            "originalTexts": ["欲望の行方"],
            "ocrResults": [{"text": "欲望の行方", "engine": "48px_ocr"}],
        },
        ["欲望的去向"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 1


def test_build_bubbles_uses_black_text_without_stroke_for_clean_light_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#f8f8f8",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [248, 248, 248],
                    "colorConfidence": 0.95,
                    "grayStdDev": 4.0,
                    "edgeDensity": 0.01,
                    "darkPixelRatio": 0.02,
                }
            ],
        },
        {
            "originalTexts": ["毎朝早い"],
            "ocrResults": [{"text": "毎朝早い", "engine": "48px_ocr"}],
        },
        ["每天都起得早"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 0


def test_build_bubbles_uses_white_stroke_for_light_but_busy_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120]],
            "bubblePolygons": [[[10, 20], [140, 20], [140, 120], [10, 120]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#efefef",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [239, 239, 239],
                    "colorConfidence": 0.88,
                    "grayStdDev": 28.0,
                    "edgeDensity": 0.17,
                    "darkPixelRatio": 0.16,
                }
            ],
        },
        {
            "originalTexts": ["見えるか"],
            "ocrResults": [{"text": "見えるか", "engine": "48px_ocr"}],
        },
        ["看得见吗"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 1


def test_build_bubbles_keeps_tiny_boxes_unstroked_even_on_dark_background():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 34, 44]],
            "bubblePolygons": [[[10, 20], [34, 20], [34, 44], [10, 44]]],
            "autoDirections": ["vertical"],
            "textlinesPerBubble": [[]],
            "bubbleColors": [
                {
                    "textColor": "#f4f4f4",
                    "bgColor": "#101010",
                    "autoFgColor": [244, 244, 244],
                    "autoBgColor": [16, 16, 16],
                    "colorConfidence": 0.91,
                    "grayStdDev": 18.0,
                    "edgeDensity": 0.11,
                    "darkPixelRatio": 0.48,
                }
            ],
        },
        {
            "originalTexts": ["第1話"],
            "ocrResults": [{"text": "第1話", "engine": "48px_ocr"}],
        },
        ["第1话"],
    )

    bubble = bubbles[0]

    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 0


def test_build_bubbles_uses_complexity_fallback_when_color_is_unreliable():
    bubbles = _build_bubbles(
        {
            "bubbleCoords": [[10, 20, 140, 120], [160, 20, 290, 120]],
            "bubblePolygons": [
                [[10, 20], [140, 20], [140, 120], [10, 120]],
                [[160, 20], [290, 20], [290, 120], [160, 120]],
            ],
            "autoDirections": ["vertical", "vertical"],
            "textlinesPerBubble": [[], []],
            "bubbleColors": [
                {
                    "textColor": "#020201",
                    "bgColor": "#020201",
                    "autoFgColor": [2, 2, 1],
                    "autoBgColor": [2, 2, 1],
                    "colorConfidence": 0.12,
                    "grayStdDev": 5.0,
                    "edgeDensity": 0.01,
                    "darkPixelRatio": 0.03,
                },
                {
                    "textColor": "#020201",
                    "bgColor": "#020201",
                    "autoFgColor": [2, 2, 1],
                    "autoBgColor": [2, 2, 1],
                    "colorConfidence": 0.12,
                    "grayStdDev": 34.0,
                    "edgeDensity": 0.21,
                    "darkPixelRatio": 0.24,
                },
            ],
        },
        {
            "originalTexts": ["ほんとに", "騒ぐな"],
            "ocrResults": [
                {"text": "ほんとに", "engine": "48px_ocr"},
                {"text": "騒ぐな", "engine": "48px_ocr"},
            ],
        },
        ["真的", "别吵"],
    )

    assert bubbles[0]["strokeWidth"] == 0
    assert bubbles[1]["strokeWidth"] == 1
```

- [x] **Step 2: 只跑新增样式测试，确认 RED**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" -k "dark_background_adaptive_style or clean_light_background or light_but_busy_background or tiny_boxes_unstroked or complexity_fallback" -v
```

Expected:

- 至少原有深底测试会失败，因为当前实现输出白字黑描边
- 新增测试会失败，因为当前实现没有复杂度和黑字双样式逻辑

- [x] **Step 3: 在同文件更新旧断言，避免保留 V3 预期**

```python
def test_build_bubbles_uses_dark_background_adaptive_style():
    ...
    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
    assert bubble["strokeWidth"] == 1


def test_build_bubbles_falls_back_to_black_text_when_fg_bg_are_same_dark_color():
    ...
    assert bubble["textColor"] == "#111111"
    assert bubble["strokeColor"] == "#FFFFFF"
```

- [x] **Step 4: 再跑一遍样式测试，确认失败原因已只剩生产代码未实现**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" -k "dark_background_adaptive_style or clean_light_background or light_but_busy_background or tiny_boxes_unstroked or complexity_fallback" -v
```

Expected:

- FAIL
- 失败信息集中在 `textColor` / `strokeWidth` 与 V4 预期不一致

### Task 2: 用最小改动实现 V4 样式决策

**Files:**
- Modify: `D:/github/translate-reader/translate_manga_cli/src/core/pipeline/service.py`
- Test: `D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py`

- [x] **Step 1: 在 `service.py` 增加小框、亮度、复杂度、不可信颜色辅助函数**

```python
def _is_tiny_bubble(coords):
    x1, y1, x2, y2 = coords
    box_width = max(0, int(x2) - int(x1))
    box_height = max(0, int(y2) - int(y1))
    return min(box_width, box_height) <= 32 or (box_width * box_height) <= 1100


def _resolve_background_luminance(color):
    bg_rgb = color.get("autoBgColor") or _parse_hex_color(color.get("bgColor"))
    return _relative_luminance(bg_rgb)


def _resolve_background_complexity(color):
    gray_stddev = float(color.get("grayStdDev", 0.0) or 0.0)
    edge_density = float(color.get("edgeDensity", 0.0) or 0.0)
    dark_ratio = float(color.get("darkPixelRatio", 0.0) or 0.0)
    return max(
        min(1.0, gray_stddev / 32.0),
        min(1.0, edge_density / 0.16),
        min(1.0, dark_ratio / 0.18),
    )


def _is_color_unreliable(color):
    bg_rgb = color.get("autoBgColor") or _parse_hex_color(color.get("bgColor"))
    fg_rgb = color.get("autoFgColor") or _parse_hex_color(color.get("textColor"))
    confidence = float(color.get("colorConfidence", 0.0) or 0.0)
    bg_luminance = _relative_luminance(bg_rgb)
    fg_bg_distance = _rgb_distance(fg_rgb, bg_rgb)
    return (
        (bg_rgb is None and fg_rgb is None)
        or confidence < 0.45
        or (
            fg_bg_distance is not None
            and fg_bg_distance <= 12
            and bg_luminance is not None
            and bg_luminance <= 24
        )
    )
```

- [x] **Step 2: 重写 `_resolve_bubble_readability_style()`，只输出黑字双样式**

```python
def _resolve_bubble_readability_style(style, color, coords):
    fill_color = color.get("bgColor")
    if _is_tiny_bubble(coords):
        return {
            "textColor": "#111111",
            "fillColor": fill_color,
            "strokeEnabled": style["strokeEnabled"],
            "strokeColor": "#FFFFFF",
            "strokeWidth": 0,
        }

    complexity = _resolve_background_complexity(color)
    color_unreliable = _is_color_unreliable(color)
    bg_luminance = _resolve_background_luminance(color)

    use_stroke = False
    if color_unreliable:
        use_stroke = complexity >= 0.5
    elif bg_luminance is None:
        use_stroke = complexity >= 0.5
    elif bg_luminance < 165:
        use_stroke = True
    elif bg_luminance >= 225:
        use_stroke = complexity >= 0.5
    else:
        use_stroke = complexity >= 0.35

    return {
        "textColor": "#111111",
        "fillColor": fill_color,
        "strokeEnabled": style["strokeEnabled"],
        "strokeColor": "#FFFFFF",
        "strokeWidth": 1 if style["strokeEnabled"] and use_stroke else 0,
    }
```

- [x] **Step 3: 跑样式测试，确认 GREEN**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" -k "dark_background_adaptive_style or clean_light_background or light_but_busy_background or tiny_boxes_unstroked or complexity_fallback" -v
```

Expected:

- PASS

- [x] **Step 4: 跑 `test_pipeline_service.py` 全量，确认没有打穿其他 pipeline 断言**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" -v
```

Expected:

- PASS

### Task 3: 在颜色服务补背景复杂度特征

**Files:**
- Modify: `D:/github/translate-reader/translate_manga_cli/src/core/color/service.py`
- Modify: `D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py`
- Test: `D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py`

- [x] **Step 1: 先写颜色服务增强测试**

```python
def test_extract_bubble_colors_enriches_results_with_background_metrics(tmp_path, monkeypatch):
    image_path = tmp_path / "page.png"
    image = Image.new("L", (80, 80), color=245)
    draw = ImageDraw.Draw(image)
    draw.line((10, 10, 70, 70), fill=0, width=3)
    image.convert("RGB").save(image_path)

    monkeypatch.setattr("src.core.color.service.has_saber_48px_color_model", lambda: True)
    monkeypatch.setattr(
        "src.core.color.service.run_saber_task",
        lambda *args, **kwargs: {
            "colors": [
                {
                    "textColor": "#111111",
                    "bgColor": "#f5f5f5",
                    "autoFgColor": [17, 17, 17],
                    "autoBgColor": [245, 245, 245],
                    "colorConfidence": 0.9,
                }
            ]
        },
    )

    result = extract_bubble_colors(
        str(image_path),
        [[8, 8, 72, 72]],
        [[{"polygon": [[20, 20], [60, 20], [60, 30], [20, 30]], "direction": "h"}]],
    )

    color = result["colors"][0]
    assert color["grayStdDev"] > 0
    assert color["edgeDensity"] > 0
    assert color["darkPixelRatio"] >= 0
```

- [x] **Step 2: 只跑新增颜色服务测试，确认 RED**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py" -k "background_metrics" -v
```

Expected:

- FAIL，缺少 `grayStdDev` / `edgeDensity` / `darkPixelRatio`

- [x] **Step 3: 在 `color/service.py` 为颜色结果追加复杂度特征**

```python
from PIL import Image, ImageDraw, ImageFilter, ImageStat


def _build_background_mask(size, textlines):
    mask = Image.new("L", size, 255)
    draw = ImageDraw.Draw(mask)
    for line in textlines or []:
        polygon = line.get("polygon") or []
        if polygon:
            draw.polygon([tuple(point) for point in polygon], fill=0)
    return mask


def _measure_background_metrics(image, coords, textlines):
    x1, y1, x2, y2 = [int(value) for value in coords[:4]]
    crop = image.crop((x1, y1, x2, y2)).convert("L")
    mask = _build_background_mask(crop.size, [
        {
            "polygon": [[point[0] - x1, point[1] - y1] for point in (line.get("polygon") or [])]
        }
        for line in (textlines or [])
    ])
    stat = ImageStat.Stat(crop, mask=mask)
    stddev = float(stat.stddev[0] if stat.stddev else 0.0)
    edges = crop.filter(ImageFilter.FIND_EDGES)
    edge_values = list(edges.getdata())
    mask_values = list(mask.getdata())
    active_values = [edge_values[index] for index, value in enumerate(mask_values) if value > 0]
    gray_values = [crop.getdata()[index] for index, value in enumerate(mask_values) if value > 0]
    edge_density = sum(1 for value in active_values if value >= 24) / max(1, len(active_values))
    dark_ratio = sum(1 for value in gray_values if value <= 96) / max(1, len(gray_values))
    return {
        "grayStdDev": stddev,
        "edgeDensity": edge_density,
        "darkPixelRatio": dark_ratio,
    }


def extract_bubble_colors(image_path, bubble_coords, textlines_per_bubble):
    ...
    with Image.open(image_path) as image:
        for index, color in enumerate(colors):
            metrics = _measure_background_metrics(
                image,
                bubble_coords[index],
                textlines_per_bubble[index] if index < len(textlines_per_bubble) else [],
            )
            color.update(metrics)
```

- [x] **Step 4: 再跑颜色服务测试，确认 GREEN**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py" -k "extract_bubble_colors" -v
```

Expected:

- PASS

### Task 4: 让无模型 fallback 和 pipeline 结果也携带复杂度字段

**Files:**
- Modify: `D:/github/translate-reader/translate_manga_cli/src/core/color/service.py`
- Modify: `D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py`
- Modify: `D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py`

- [x] **Step 1: 为无 48px 模型 fallback 补默认复杂度字段**

```python
return {
    "colors": [
        {
            "textColor": None,
            "bgColor": None,
            "autoFgColor": None,
            "autoBgColor": None,
            "colorConfidence": 0.0,
            "grayStdDev": 0.0,
            "edgeDensity": 0.0,
            "darkPixelRatio": 0.0,
        }
        for _ in bubble_coords
    ]
}
```

- [x] **Step 2: 更新现有 pipeline 预处理断言，显式接受复杂度字段**

```python
assert result["bubbleColors"] == [
    {
        "textColor": "#0f0f0f",
        "bgColor": "#ffffff",
        "autoFgColor": [15, 15, 15],
        "autoBgColor": [255, 255, 255],
        "colorConfidence": 0.95,
        "grayStdDev": 12.0,
        "edgeDensity": 0.03,
        "darkPixelRatio": 0.01,
    }
]
```

- [x] **Step 3: 跑相关颜色和预处理测试**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py" "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" -k "extract_bubble_colors or preprocess_page" -v
```

Expected:

- PASS

### Task 5: 做回归验证并锁定新的默认行为

**Files:**
- Modify: `D:/github/translate-reader/agent-docs/index.md`
- Modify: `D:/github/translate-reader/agent-docs/specs/2026-05-08-v4-readability-design.md`
- Test: `D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py`
- Test: `D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py`

- [x] **Step 1: 跑目标测试集合，确认代码层回归通过**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py" -v
```

Expected:

- PASS

Actual:

- `31 passed` for `test_pipeline_service.py` and `test_inpaint_render_services.py`

- [ ] **Step 2: 用本地样本页做人工回归渲染**

Run:

```bash
python "D:/github/translate-reader/translate_manga_cli/batch_translate.py" --input "D:/github/translate-reader/翻译测试日漫/德川家康/05" --output "D:/github/translate-reader/翻译测试日漫/德川家康/05/out-v4-check" --overwrite-existing
python "D:/github/translate-reader/translate_manga_cli/batch_translate.py" --input "D:/github/translate-reader/翻译测试日漫/卡姆依传/01" --output "D:/github/translate-reader/翻译测试日漫/卡姆依传/01/out-v4-check" --overwrite-existing
```

Expected:

- 输出成功
- 指定样本页只出现黑字双样式
- 干净对白框多数无描边
- 复杂底图上的字明显更清晰，但白描边存在感仍低

- [x] **Step 3: 更新设计文档状态说明，注明 V4 已作为新的全局默认落地**

```markdown
## 落地状态

- `2026-05-08` 起，V4 readability 已替换 V3 成为全局默认
- 输出样式固定为 `black + white stroke` 与 `black + no stroke`
```

- [ ] **Step 4: 最终全量验证当前相关测试**

Run:

```bash
pytest "D:/github/translate-reader/translate_manga_cli/tests/test_pipeline_service.py" "D:/github/translate-reader/translate_manga_cli/tests/test_inpaint_render_services.py" "D:/github/translate-reader/translate_manga_cli/tests/test_cli_batch.py" -v
```

Expected:

- PASS

Actual:

- 未完成。包含 `test_cli_batch.py` 的集合在 `124s` 超时；单跑 `test_run_batch_translation_records_run_options_in_debug_summary` 约 `30.73s` 通过，说明该文件整体耗时超过当前验证窗口。

## Self-Review

- Spec coverage
  - 黑字双样式：Task 1、Task 2
  - 小框优先：Task 1、Task 2
  - 亮度 + 复杂度：Task 2、Task 3
  - 颜色不可信兜底：Task 1、Task 2、Task 4
  - 全局默认替换：Task 5
- Placeholder scan
  - 已避免 `TBD/TODO/稍后实现/适当处理`
- Type consistency
  - 统一使用 `grayStdDev`、`edgeDensity`、`darkPixelRatio`
  - 统一使用 `strokeWidth` 为 `0/1`
