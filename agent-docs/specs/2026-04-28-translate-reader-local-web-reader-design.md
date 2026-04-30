# translate-reader 本地 Web 机翻阅读器首版设计

日期：2026-04-28

## 1. 目标

基于本地图片目录构建一个精简的本地 Web 日漫机翻阅读器，实现以下核心链路：

`检测 -> OCR -> 翻译 -> 擦字 -> 写字 -> 阅读展示 -> 结果缓存`

目标效果：

- 让日漫生肉在浏览器中尽快转成可阅读的熟肉
- 保持原页面阅读顺序、文字区域和整体画风基本不变
- 支持按页即时处理，而不是先做一整套重型翻译平台

## 2. 首版边界

### 2.1 范围内

- 运行形态：本地 Web 工具，`Python 后端 + 浏览器前端`
- 输入：本地图片目录，首版支持 `jpg/png/webp`
- 阅读方式：按页浏览、切页、原图/译图切换
- 处理模式：单页即时处理，支持缓存中间结果和最终译图
- 调试能力：可查看检测框、OCR 文本、最终排版框
- 翻译方式：在线 OpenAI-compatible API

### 2.2 暂不纳入首版

- PDF / CBZ / ZIP 导入
- 书架、章节、会话管理
- 插件系统
- Manga Insight / 分析能力
- 网页导入
- 大规模批处理任务池
- 复杂设置中心
- 人工精修编辑器、手动画笔、手动框编辑

## 3. 设计原则

- 以“阅读器”而不是“翻译工作台”为中心
- 优先保证 OCR、擦字、写字链路能跑通
- 借用 `Saber-Translator` 的成熟核心算法路径，但不迁其产品壳层
- API 设计保留分步骤调用，方便后续调试和逐步增强
- 数据结构尽量兼容 `bubble / textline / ocrResult` 思路，减少迁移成本

## 4. 方案选择

本项目采用“选择性迁移 Saber 核心模块”的方案。

原因：

- 整套裁剪 Saber：实现快，但项目会迅速失控，演变成另一个重型平台
- 从零重写：结构干净，但 OCR、擦字、排版质量很难快速接近目标
- 迁核心、重写壳：能复用成熟算法路径，同时把产品形态收敛到阅读器

## 5. 总体架构

系统拆分为 4 个层次：

### 5.1 reader-web

浏览器界面，负责：

- 当前目录页列表展示
- 当前页原图/译图切换
- 单页触发 OCR / 整页翻译
- 调试层切换显示

### 5.2 pipeline-api

Python 后端 API，负责：

- 串联完整流水线
- 暴露分步骤接口
- 管理缓存和页面元数据

### 5.3 core

从 `Saber-Translator` 精简迁移的核心能力：

- `detection`
- `ocr`
- `translate`
- `inpaint`
- `render`
- `pipeline`

### 5.4 storage

本地运行数据与缓存：

- 图片目录索引
- 单页中间结果 JSON
- 最终译图
- OCR / 翻译 / 排版产物

## 6. 目录结构

建议在 `D:/github/translate-reader/translate-reader` 下建立如下结构：

```text
translate-reader/
  app.py
  requirements.txt
  src/
    app/
      routes/
      static/
      templates/
    core/
      detection/
      ocr/
      translate/
      inpaint/
      render/
      pipeline/
    models/
    services/
    storage/
  data/
    library/
    cache/
    exports/
```

说明：

- `src/app`：只放 Web 壳和 HTTP 路由
- `src/core`：放算法和处理链
- `src/storage`：读写目录索引、缓存和页面状态
- `data/cache`：保存单页产物，避免重复计算

## 7. 模块迁移策略

### 7.1 迁移或改造自 Saber 的部分

#### 检测层

参考：

- [detection.py](/D:/github/translate-reader/Saber-Translator/src/core/detection.py:1)
- `Saber-Translator/src/core/detector/`

首版策略：

- 只保留一个主检测路径
- 输出统一的 `bubble_coords / bubble_polygons / auto_directions / textlines_per_bubble`
- 不首发引入完整多检测器切换界面

#### OCR 层

参考：

- [ocr.py](/D:/github/translate-reader/Saber-Translator/src/core/ocr.py:1)
- [paddle_ocr_onnx_interface.py](/D:/github/translate-reader/Saber-Translator/src/interfaces/paddle_ocr_onnx_interface.py:1)

首版保留：

- `manga_ocr`：默认日文识别
- `paddle_ocr_onnx`：兜底或多语言支持
- 按框 OCR，不做整页硬识别

#### 擦字层

参考：

- [inpainting.py](/D:/github/translate-reader/Saber-Translator/src/core/inpainting.py:1)

首版保留：

- 基于检测框或精确掩膜的修复掩膜生成
- `solid fill`
- `lama` 或 `litelama` 其中一个修复后端

#### 写字层

参考：

- [rendering.py](/D:/github/translate-reader/Saber-Translator/src/core/rendering.py:1)

首版保留：

- 横排/竖排
- 自动字号
- 描边
- 日漫竖排标点处理

#### 步骤式 API 设计

参考：

- [parallel_routes.py](/D:/github/translate-reader/Saber-Translator/src/app/api/translation/parallel_routes.py:1)

首版保留思路：

- 每一步独立接口
- 再提供一个完整单页流水线接口

### 7.2 不迁移的 Saber 部分

- 书架、章节、会话系统
- 插件系统
- Manga Insight
- 网页导入
- 高质量多图上下文翻译模式
- 大规模并行任务池
- 复杂设置与高级配置 UI

## 8. API 设计

### 8.1 阅读器接口

`GET /api/library/pages`

- 返回当前目录的页面列表
- 返回每页缓存状态

`GET /api/library/page/<id>`

- 返回单页原图路径
- 返回单页译图路径
- 返回当前页元数据

### 8.2 流水线接口

`POST /api/pipeline/run-page`

- 对单页执行完整链路：
  `detect -> ocr -> translate -> inpaint -> render`

`POST /api/pipeline/detect`

- 输入图片
- 输出检测框、方向、文本行信息

`POST /api/pipeline/ocr`

- 输入图片和检测框
- 输出 `original_texts` 与 `ocr_results`

`POST /api/pipeline/translate`

- 输入 OCR 文本
- 输出翻译文本

`POST /api/pipeline/inpaint`

- 输入原图和检测结果
- 输出 clean image

`POST /api/pipeline/render`

- 输入 clean image、翻译文本和气泡布局
- 输出最终译图

### 8.3 缓存接口

`GET /api/page/<id>/result`

- 读取单页已有中间结果和最终结果

`POST /api/page/<id>/save-edits`

- 为第二阶段编辑能力预留接口
- 首版可只保存当前文本和渲染参数

## 9. 页面交互

页面采用阅读器优先布局：

- 左侧：页缩略图列表
- 中间：阅读画布
- 右侧：当前页状态与调试面板
- 顶部：动作按钮

首版按钮：

- `读取文字`
- `整页翻译`
- `重做擦字`
- `重做写字`

首版调试层：

- 检测框
- OCR 文本
- 排版框

## 10. 核心数据结构

### 10.1 PageRecord

- `id`
- `file_name`
- `source_path`
- `translated_path`
- `status`
- `cache_key`

### 10.2 Bubble

- `coords`
- `polygon`
- `direction`
- `textlines`
- `original_text`
- `translated_text`
- `ocr_result`

### 10.3 OcrResult

字段参考 Saber 的 `ocr_types`，首版保留：

- `text`
- `confidence`
- `confidence_supported`
- `engine`
- `primary_engine`
- `fallback_used`

## 11. 翻译适配策略

翻译后端不迁 Saber 的多服务商系统，单独实现一个精简的 OpenAI-compatible adapter。

默认配置来源：

- 根目录 `翻译api.txt` 脱敏示例

首版只要求：

- 支持 `base_url`
- 支持 `model`
- 支持标准 `chat/completions`
- 支持流式或非流式二选一，优先非流式闭环

## 12. 首版实现优先级

### P0

- 本地图片目录读取
- 单页检测
- 单页 OCR
- 单页翻译
- 单页擦字
- 单页写字
- 阅读器展示与缓存

### P1

- 结果复用
- 调试层可视化
- 原图/译图切换体验优化

### P2

- 手工修正框
- 批量处理
- 更多输入格式

## 13. 风险与控制

### 13.1 OCR 质量风险

风险：

- 单一 OCR 引擎对复杂漫画页不稳定

控制：

- 先保留 `manga_ocr + paddle_ocr_onnx`
- 必须坚持“先检测后 OCR”

### 13.2 擦字与排版观感风险

风险：

- 擦字后背景不自然
- 译文过长导致气泡内排版崩坏

控制：

- 首版保留自动字号
- 翻译提示词中约束字数
- 擦字先保证可用，再追求极致细节

### 13.3 项目范围膨胀风险

风险：

- 逐步滑向完整 Saber 复刻

控制：

- 首版只做阅读器闭环
- 非阅读器刚需功能一律延后

## 14. 验收标准

给定本地日漫图片目录，系统应能：

- 列出页面并切换阅读
- 对单页完成完整流水线处理
- 生成可查看的译图
- 保留检测框、OCR 文本和中间结果缓存
- 在典型竖排日漫页上得到可阅读结果

## 15. 实施结论

首版 `translate-reader` 应被实现为：

- 一个轻量的本地 Web 日漫机翻阅读器
- 一个使用 Saber 核心算法路径但不复刻其完整产品壳的项目
- 一个以单页即时处理和阅读体验为核心的最小闭环系统
