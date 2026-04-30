from pathlib import Path
import re

from src.config.settings import resolve_pipeline_config, resolve_translation_config
from src.core.translate.openai_compatible import OpenAICompatibleTranslator


DEFAULT_CONTEXT_GENERATION_PROMPT = """你是漫画背景整理助手。

任务: 根据给定的漫画目录名、作者名、卷名、文件名风格，整理一份给漫画翻译模型使用的简明背景说明。

输出要求:
- 只输出 Markdown 正文，不要解释
- 控制在 180-320 字中文
- 优先包含: 作品名、作者、时代/题材、主角或核心人物、整体语气、常见翻译口吻约束
- 如果信息不确定，明确写“可能/大致”，不要编造细节
- 最后补一个“翻译建议”小节，强调称呼、语气、标点、时代感
"""


def _candidate_context_paths(input_dir, pipeline_config=None):
    pipeline_config = pipeline_config or resolve_pipeline_config()
    names = pipeline_config.get("manga_context_file_names") or ["manga_context.md", "manga_context.txt"]
    root = Path(input_dir)
    return [root / str(name).strip() for name in names if str(name).strip()]


def find_existing_manga_context(input_dir, pipeline_config=None):
    for path in _candidate_context_paths(input_dir, pipeline_config=pipeline_config):
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return {
                    "path": path,
                    "content": content,
                    "generated": False,
                }
    return None


def _guess_manga_metadata(input_dir):
    path = Path(input_dir)
    parts = [part.strip() for part in path.parts if str(part).strip()]
    folder_name = path.name.strip()
    parent_name = path.parent.name.strip() if path.parent != path else ""

    author = ""
    title = folder_name
    match = re.search(r"\[([^\]]+)\]\s*(.+)", folder_name)
    if match:
        author = match.group(1).strip()
        title = match.group(2).strip()
    elif parent_name:
        parent_match = re.search(r"\[([^\]]+)\]\s*(.+)", parent_name)
        if parent_match:
            author = parent_match.group(1).strip()
            title = folder_name or parent_match.group(2).strip()

    return {
        "folder_name": folder_name,
        "parent_name": parent_name,
        "author": author,
        "title": title,
        "path_parts": parts[-6:],
    }


def _build_generation_messages(input_dir):
    metadata = _guess_manga_metadata(input_dir)
    lines = [
        "请根据这些目录信息整理漫画背景提示词。",
        f"当前目录: {Path(input_dir)}",
        f"目录名: {metadata['folder_name']}",
    ]
    if metadata["parent_name"]:
        lines.append(f"上级目录: {metadata['parent_name']}")
    if metadata["author"]:
        lines.append(f"推测作者: {metadata['author']}")
    if metadata["title"]:
        lines.append(f"推测作品/卷名: {metadata['title']}")
    if metadata["path_parts"]:
        lines.append("路径片段:")
        lines.extend(f"- {item}" for item in metadata["path_parts"])
    lines.append("请输出可直接保存为 manga_context.md 的正文。")
    return [
        {"role": "system", "content": DEFAULT_CONTEXT_GENERATION_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def generate_manga_context(input_dir):
    translation = resolve_translation_config()
    translator = OpenAICompatibleTranslator()
    content, usage = translator._request_completion(
        model=translation["model"],
        base_url=translation["base_url"],
        api_key=translation["api_key"],
        messages=_build_generation_messages(input_dir),
    )
    normalized = str(content or "").strip()
    if not normalized:
        raise RuntimeError("generated manga context is empty")
    return {
        "content": normalized,
        "usage": usage,
    }


def load_or_generate_manga_context(input_dir, *, auto_generate=None, pipeline_config=None):
    pipeline_config = pipeline_config or resolve_pipeline_config()
    existing = find_existing_manga_context(input_dir, pipeline_config=pipeline_config)
    if existing is not None:
        return existing

    if auto_generate is None:
        auto_generate = bool(pipeline_config.get("auto_generate_manga_context", True))
    if not auto_generate:
        return None

    candidate_paths = _candidate_context_paths(input_dir, pipeline_config=pipeline_config)
    target_path = candidate_paths[0] if candidate_paths else Path(input_dir) / "manga_context.md"

    generated = generate_manga_context(input_dir)
    target_path.write_text(generated["content"], encoding="utf-8")
    return {
        "path": target_path,
        "content": generated["content"],
        "generated": True,
        "usage": generated.get("usage"),
    }
