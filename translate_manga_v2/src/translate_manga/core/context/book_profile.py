from dataclasses import dataclass
from pathlib import Path
import re


_VOLUME_PATTERNS = [
    re.compile(r"^\d{1,3}$"),
    re.compile(r"^(?:vol|volume)[._\-\s]*\d{1,3}$", re.IGNORECASE),
    re.compile(r"^第?\d{1,3}[卷巻话話集册冊]?$"),
]


@dataclass(frozen=True)
class BookProfile:
    input_dir: Path
    series_root: Path
    series_name: str
    volume_name: str
    profile_dir: Path
    series_profile_path: Path
    glossary_path: Path
    characters_path: Path
    translation_memory_path: Path


def is_volume_name(value):
    name = str(value or "").strip()
    if not name:
        return False
    return any(pattern.match(name) for pattern in _VOLUME_PATTERNS)


def build_book_profile(input_dir):
    input_path = Path(input_dir)
    leaf_name = input_path.name.strip()
    if is_volume_name(leaf_name) and input_path.parent != input_path:
        series_root = input_path.parent
        series_name = input_path.parent.name.strip() or leaf_name
        volume_name = leaf_name
    else:
        series_root = input_path
        series_name = leaf_name
        volume_name = ""

    profile_dir = series_root / "_translation_profile"
    return BookProfile(
        input_dir=input_path,
        series_root=series_root,
        series_name=series_name,
        volume_name=volume_name,
        profile_dir=profile_dir,
        series_profile_path=profile_dir / "series_profile.md",
        glossary_path=profile_dir / "glossary.tsv",
        characters_path=profile_dir / "characters.tsv",
        translation_memory_path=profile_dir / "translation_memory.json",
    )


def ensure_profile_scaffold(profile):
    profile.profile_dir.mkdir(parents=True, exist_ok=True)
    if not profile.glossary_path.exists():
        profile.glossary_path.write_text("原文\t译文\t备注\n", encoding="utf-8")
    if not profile.characters_path.exists():
        profile.characters_path.write_text("原文名\t译名\t称呼/关系\t备注\n", encoding="utf-8")
    if not profile.translation_memory_path.exists():
        profile.translation_memory_path.write_text(
            "{\n  \"confirmedTranslations\": [],\n  \"nameMappings\": {}\n}\n",
            encoding="utf-8",
        )


def _read_non_empty(path):
    try:
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError:
        return ""
    return ""


def _read_tsv_as_context(path, title):
    content = _read_non_empty(path)
    if not content:
        return ""
    rows = [line.strip() for line in content.splitlines() if line.strip()]
    data_rows = [line for line in rows[1:] if line.strip()]
    if not data_rows:
        return ""
    return "\n".join([f"## {title}", *[f"- {line}" for line in data_rows]])


def load_profile_context(profile):
    sections = []
    series_profile = _read_non_empty(profile.series_profile_path)
    if series_profile:
        sections.append(series_profile)
    glossary = _read_tsv_as_context(profile.glossary_path, "固定术语表")
    if glossary:
        sections.append(glossary)
    characters = _read_tsv_as_context(profile.characters_path, "人物称呼表")
    if characters:
        sections.append(characters)
    return "\n\n".join(sections).strip()


def find_existing_profile_context(input_dir):
    profile = build_book_profile(input_dir)
    content = load_profile_context(profile)
    if not content:
        return None
    return {
        "path": profile.series_profile_path,
        "content": content,
        "generated": False,
        "profile": profile,
    }


def split_pasted_paths(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return []

    chunks = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line:
            continue
        chunks.extend([item for item in re.split(r"(?<!^)(?=[A-Za-z]:[\\/])", line) if item.strip()])

    normalized = []
    for chunk in chunks:
        item = chunk.strip().strip("\"'")
        if item and item not in normalized:
            normalized.append(item)
    return normalized
