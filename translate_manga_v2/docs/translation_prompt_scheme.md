# 漫画翻译提示词方案

这份文档给 `translate_manga_v2` 自己看，用来约束翻译模型提示词、当前卷 `manga_context.md`、书系 `_translation_profile` 与样式 profile 的配合方式。

## 目标

- 让模型先理解“这是什么漫画”，再做三轮翻译
- 控制口吻、称呼、时代感、标点习惯
- 输出仍然保持紧凑，适合气泡嵌字
- 日漫和英漫使用不同源语言、OCR 与提示词 profile，避免提示词串线

## 实际注入顺序

1. `prompts.translation.system`
2. 当前卷 `manga_context.md`，如果存在
3. 书系 `_translation_profile/series_profile.md`，当当前卷没有 `manga_context.md` 时使用
4. 书系 `_translation_profile/glossary.tsv` 与 `characters.tsv`，随书系 profile 一起注入
5. 邻近页确认译文，纠错重跑时会读取 `_debug/pages/*.json` 里的前后页正常译文
6. 当前批次原文
7. 前一轮草稿

注意：当前实现中，当前卷 `manga_context.md` 优先级高于书系 profile；两者不会自动拼接。需要卷级特殊规则时，把该卷的 `manga_context.md` 写完整。

## 样式与提示词 Profile

| 样式 | 用途 | 排版 | 阅读方向 | OCR | 提示词 |
| --- | --- | --- | --- | --- | --- |
| `style1` | 日漫横排 | horizontal | ltr | 默认日语 OCR 配置 | `default` |
| `style2` | 日漫竖排 | vertical | rtl | 默认日语 OCR 配置 | `default` |
| `style3` | 英文欧美漫画 | horizontal | ltr | `paddle_ocr` + English ONNX | `english` |
| `auto` | 旧自动方向兼容 | auto | rtl | 默认日语 OCR 配置 | `default` |

`style3` 会把 `sourceLanguage=english`、`promptPreset=english`、`readingOrder=ltr` 注入翻译上下文。批量翻译、纠错重跑和轻量兜底翻译都必须保留这些字段，否则英文漫画会退回日语提示词。

## 缓存与提示词变更

隐藏翻译缓存的签名包含：

- 翻译 prompt profile
- `translation_quality` 质量档位
- 实际解析后的 system / draft / contextual / final 提示词
- 当前生效的 `manga_context.md` 或书系 profile 内容

因此修改 `config/defaults.json` / `config/local.json` 里的提示词、切换 `translation_quality`，或修改 `manga_context.md` / `_translation_profile/series_profile.md` 后，旧译文缓存会被降级为只复用预处理结果，并重新翻译。OCR、源语言或阅读方向变化则由预处理缓存签名负责失效。

## 当前卷 `manga_context.md` 推荐结构

```md
## 作品定位
- 作品名:
- 作者:
- 类型/气质:

## 人物与称呼
- 主角:
- 常驻角色:
- 固定译名:

## 叙事和口吻
- 成年人/少年/荒诞/冷幽默/悬疑 等
- 是否克制
- 是否保留压抑感

## 翻译建议
- 称呼统一
- 少中文全角标点
- 少网络语
- 保留时代感

## 避免事项
- 不要热血少年漫腔调
- 不要过量感叹号
- 不要擅自解释画面外信息
```

## 当前推荐用法

- `system` 只负责硬规则
- 当前卷 `manga_context.md` 负责单卷特殊背景和风格
- 书系 `_translation_profile/series_profile.md` 负责跨卷共用的作品背景、时代感和口吻
- 书系 `glossary.tsv` 负责固定人名、地名、官职、术语
- 书系 `characters.tsv` 负责人物称呼、关系和身份
- `translation_quality=high` 使用 `draft/contextual/final` 三轮，分别负责直译、统一、压缩
- `translation_quality=balanced` 使用 `draft/final` 两轮，适合大批量预览或速度优先的整本翻译
- `translation_quality=fast` 只跑单轮 final，适合快速扫图或英文短页

## 书系 Profile

当输入路径最后一段是卷号，例如 `D:/漫画/德川家康/01`，程序会把上一级目录识别为书系根目录，并自动生成或复用：

```text
德川家康/
  _translation_profile/
    series_profile.md
    glossary.tsv
    characters.tsv
    translation_memory.json
```

`series_profile.md` 是给 AI 翻译模型看的长期提示词；`glossary.tsv` 和 `characters.tsv` 可以人工维护，后续卷会继承。`translation_memory.json` 目前是跨卷记忆的脚手架，后续可接入自动更新。

## 适合的作品背景信息

- 黑色幽默短篇
- 都市怪谈
- 昭和成年漫画
- 日常校园
- 悬疑推理

不要塞太长剧情简介。重点是“翻译该怎么说话”，不是“把百科全贴进去”。
