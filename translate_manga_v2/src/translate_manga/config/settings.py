import json
import os
from copy import deepcopy
from pathlib import Path

from translate_manga.config.paths import find_project_root


_BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off"}

_DEFAULT_TRANSLATION_PROMPTS = {
    "system": """你是专业漫画翻译器。

任务是把漫画中的日文文本翻译成自然、准确、紧凑的简体中文。

硬性要求:
- 逐条处理输入文本, 严格保留 `<|数字|>` 编号前缀
- 只输出译文, 不要解释, 不要加注释
- 人名、称呼、语气前后一致
- 拟声词、音效词、已经是中文的内容可原样保留
- 尽量少用中文全角标点, 优先使用更紧凑的半角标点
- 半角标点要自然, 不要影响阅读
""",
    "rounds": {
        "draft": "第1轮 初稿: 忠实翻译, 先保证信息完整和语义正确。",
        "contextual": "第2轮 上下文修订: 结合已给出的上下文和第1轮草稿, 统一称呼、语气和前后逻辑。",
        "final": "第3轮 气泡定稿: 不改变含义, 压缩成更适合漫画气泡的自然中文, 少标点, 更顺眼。",
    },
    "profiles": {
        "english": {
            "system": """你是专业漫画翻译器。

任务是把漫画中的英文文本翻译成自然、准确、紧凑的简体中文。

硬性要求:
- 逐条处理输入文本, 严格保留 `<|数字|>` 编号前缀
- 只输出译文, 不要解释, 不要加注释
- 人名、称呼、语气前后一致
- 拟声词、音效词、已经是中文的内容可原样保留
- 尽量少用中文全角标点, 优先使用更紧凑的半角标点
- OCR 可能把 O/0、I/1/l、E/F、字母重复或撇号识别错; 结合英文上下文纠正明显 OCR 噪声, 不要机械照抄错字
""",
            "rounds": {
                "draft": "第1轮 初稿: 忠实翻译英文原意, 先修正明显 OCR 噪声并保证信息完整。",
                "contextual": "第2轮 上下文修订: 结合上下文和第1轮草稿, 统一称呼、语气和前后逻辑。",
                "final": "第3轮 气泡定稿: 不改变含义, 压缩成适合欧美漫画横排气泡的自然中文, 少标点, 更顺眼。",
            },
        }
    },
}

_ENV_MAPPINGS = {
    "TRANSLATE_MANGA_CLI_INPUT_DIR": ("paths", "input_dir", "str"),
    "TRANSLATE_MANGA_CLI_OUTPUT_DIR": ("paths", "output_dir", "str"),
    "TRANSLATE_MANGA_CLI_WORKSPACE_ROOT": ("paths", "workspace_root", "str"),
    "TRANSLATE_MANGA_CLI_CACHE_ROOT": ("paths", "cache_root", "str"),
    "TRANSLATE_MANGA_CLI_SABER_ROOT": ("paths", "saber_root", "str"),
    "TRANSLATE_MANGA_CLI_SABER_PYTHON": ("paths", "saber_python", "str"),
    "TRANSLATE_MANGA_CLI_MODEL": ("translation", "model", "str"),
    "TRANSLATE_MANGA_CLI_BASE_URL": ("translation", "base_url", "str"),
    "TRANSLATE_MANGA_CLI_API_KEY": ("translation", "api_key", "str"),
    "TRANSLATE_MANGA_CLI_REQUEST_TIMEOUT_SECONDS": ("translation", "request_timeout_seconds", "float"),
    "TRANSLATE_MANGA_CLI_CURL_TIMEOUT_SECONDS": ("translation", "curl_timeout_seconds", "int"),
    "TRANSLATE_MANGA_CLI_OCR_ENGINE": ("ocr", "engine", "str"),
    "TRANSLATE_MANGA_CLI_OCR_SOURCE_LANGUAGE": ("ocr", "source_language", "str"),
    "TRANSLATE_MANGA_CLI_OCR_ENABLE_HYBRID": ("ocr", "enable_hybrid", "bool"),
    "TRANSLATE_MANGA_CLI_OCR_SECONDARY_ENGINE": ("ocr", "secondary_engine", "str"),
    "TRANSLATE_MANGA_CLI_OCR_HYBRID_THRESHOLD": ("ocr", "hybrid_threshold", "float"),
    "TRANSLATE_MANGA_CLI_OCR_FALLBACK_TO_MANGA_OCR_WHEN_48PX_UNAVAILABLE": (
        "ocr",
        "fallback_to_manga_ocr_when_48px_unavailable",
        "bool",
    ),
    "TRANSLATE_MANGA_CLI_OVERWRITE_EXISTING": ("pipeline", "overwrite_existing", "bool"),
    "TRANSLATE_MANGA_CLI_DEBUG_OUTPUT": ("pipeline", "debug_output", "bool"),
    "TRANSLATE_MANGA_CLI_SKIP_FRONTMATTER": ("pipeline", "skip_frontmatter", "bool"),
    "TRANSLATE_MANGA_CLI_TRANSLATE_BATCH_SIZE": ("pipeline", "translate_batch_size", "int"),
    "TRANSLATE_MANGA_CLI_TRANSLATE_BATCH_MAX_CHARS": ("pipeline", "translate_batch_max_chars", "int"),
    "TRANSLATE_MANGA_CLI_INPAINT_METHOD": ("inpaint", "method", "str"),
    "TRANSLATE_MANGA_CLI_MASK_DILATE_SIZE": ("inpaint", "mask_dilate_size", "int"),
    "TRANSLATE_MANGA_CLI_MASK_BOX_EXPAND_RATIO": ("inpaint", "mask_box_expand_ratio", "int"),
    "TRANSLATE_MANGA_CLI_FONT_FAMILY": ("render", "font_family", "str"),
    "TRANSLATE_MANGA_CLI_LAYOUT_MODE": ("render", "layout_mode", "str"),
    "TRANSLATE_MANGA_CLI_STROKE_ENABLED": ("render", "stroke_enabled", "bool"),
    "TRANSLATE_MANGA_CLI_STROKE_COLOR": ("render", "stroke_color", "str"),
    "TRANSLATE_MANGA_CLI_STROKE_WIDTH": ("render", "stroke_width", "int"),
    "TRANSLATE_MANGA_CLI_LINE_SPACING": ("render", "line_spacing", "float"),
    "TRANSLATE_MANGA_CLI_TEXT_ALIGN": ("render", "text_align", "str"),
    "TRANSLATE_MANGA_CLI_AUTO_FONT_MIN_SIZE": ("render", "auto_font", "min_size", "int"),
    "TRANSLATE_MANGA_CLI_AUTO_FONT_MAX_SIZE": ("render", "auto_font", "max_size", "int"),
    "TRANSLATE_MANGA_CLI_AUTO_FONT_PADDING_RATIO": ("render", "auto_font", "padding_ratio", "float"),
    "TRANSLATE_MANGA_CLI_SABER_SESSION_TIMEOUT_SECONDS": ("runtime", "saber_session_timeout_seconds", "float"),
    "TRANSLATE_MANGA_CLI_SABER_SUBPROCESS_TIMEOUT_SECONDS": ("runtime", "saber_subprocess_timeout_seconds", "float"),
    "TRANSLATE_MANGA_CLI_MANGA_CONTEXT_FILE_NAMES": ("pipeline", "manga_context_file_names", "str"),
    "TRANSLATE_MANGA_CLI_AUTO_GENERATE_MANGA_CONTEXT": ("pipeline", "auto_generate_manga_context", "bool"),
}

_LEGACY_ENV_MAPPINGS = {
    "TRANSLATE_READER_INPAINT_METHOD": ("inpaint", "method", "str"),
    "TRANSLATE_READER_SABER_PYTHON": ("paths", "saber_python", "str"),
    "TRANSLATE_READER_SABER_SESSION_TIMEOUT_SECONDS": ("runtime", "saber_session_timeout_seconds", "float"),
    "TRANSLATE_READER_SABER_SUBPROCESS_TIMEOUT_SECONDS": ("runtime", "saber_subprocess_timeout_seconds", "float"),
}


def _resolve_project_root(project_root=None):
    return Path(project_root) if project_root is not None else find_project_root(__file__)


def _session_state_path(project_root=None):
    return _resolve_project_root(project_root) / "config" / "session.json"


def _load_json(path):
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def _deep_merge(base, override):
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _coerce_value(raw_value, value_type):
    if value_type == "str":
        return str(raw_value)
    if value_type == "int":
        return int(float(raw_value))
    if value_type == "float":
        return float(raw_value)
    if value_type == "bool":
        lowered = str(raw_value).strip().lower()
        if lowered in _BOOL_TRUE_VALUES:
            return True
        if lowered in _BOOL_FALSE_VALUES:
            return False
        raise ValueError(f"invalid boolean value: {raw_value}")
    raise ValueError(f"unsupported value type: {value_type}")


def _set_nested_value(target, path_parts, value):
    cursor = target
    for key in path_parts[:-1]:
        next_cursor = cursor.get(key)
        if not isinstance(next_cursor, dict):
            next_cursor = {}
            cursor[key] = next_cursor
        cursor = next_cursor
    cursor[path_parts[-1]] = value


def _apply_env_overrides(settings, env):
    updated = deepcopy(settings)
    for mapping_group in (_LEGACY_ENV_MAPPINGS, _ENV_MAPPINGS):
        for env_name, mapping in mapping_group.items():
            raw_value = env.get(env_name)
            if raw_value is None or str(raw_value).strip() == "":
                continue
            *path_parts, value_type = mapping
            _set_nested_value(updated, path_parts, _coerce_value(raw_value, value_type))
    return updated


def load_settings(project_root=None):
    resolved_root = _resolve_project_root(project_root)
    config_root = resolved_root / "config"
    defaults = _load_json(config_root / "defaults.json")
    local = _load_json(config_root / "local.json")
    return _apply_env_overrides(_deep_merge(defaults, local), os.environ)


def load_session_state(project_root=None):
    try:
        payload = _load_json(_session_state_path(project_root))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}

    if not isinstance(payload, dict):
        return {}

    state = {}
    input_dirs = []
    raw_input_dirs = payload.get("last_input_dirs")
    if isinstance(raw_input_dirs, list):
        for item in raw_input_dirs:
            input_dir_item = str(item or "").strip()
            if input_dir_item:
                input_dirs.append(input_dir_item)

    input_dir = str(payload.get("last_input_dir") or "").strip()
    output_dir = str(payload.get("last_output_dir") or "").strip()
    style_id = str(payload.get("last_style_id") or "").strip()
    layout_mode = str(payload.get("last_layout_mode") or "").strip()
    overwrite_existing = payload.get("last_overwrite_existing")

    if not input_dirs and input_dir:
        input_dirs.append(input_dir)

    if input_dirs:
        state["last_input_dirs"] = input_dirs
        state["last_input_dir"] = input_dirs[0]
        if not output_dir:
            output_dir = (Path(input_dirs[0]) / "out").as_posix()
    if input_dir:
        state["last_input_dir"] = input_dir
    if output_dir:
        state["last_output_dir"] = output_dir
    if style_id:
        state["last_style_id"] = style_id
    if layout_mode:
        state["last_layout_mode"] = layout_mode
    if isinstance(overwrite_existing, bool):
        state["last_overwrite_existing"] = overwrite_existing

    return state


def save_session_state(
    *,
    last_input_dirs=None,
    last_input_dir=None,
    last_output_dir=None,
    last_style_id=None,
    last_layout_mode=None,
    last_overwrite_existing=None,
    project_root=None,
):
    session_path = _session_state_path(project_root)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    payload = load_session_state(project_root=project_root)

    if last_input_dirs is not None:
        normalized_input_dirs = []
        for item in last_input_dirs or []:
            candidate = str(item or "").strip()
            if not candidate:
                continue
            normalized_input_dirs.append(Path(candidate).expanduser().resolve().as_posix())
        payload["last_input_dirs"] = normalized_input_dirs
        if normalized_input_dirs:
            payload["last_input_dir"] = normalized_input_dirs[0]
            payload["last_output_dir"] = (Path(normalized_input_dirs[0]) / "out").expanduser().resolve().as_posix()
    if last_input_dir is not None:
        normalized_input_dir = Path(last_input_dir).expanduser().resolve().as_posix()
        payload["last_input_dir"] = normalized_input_dir
        if last_input_dirs is None:
            payload["last_input_dirs"] = [normalized_input_dir]
    if last_output_dir is not None:
        payload["last_output_dir"] = Path(last_output_dir).expanduser().resolve().as_posix()
    if last_style_id is not None:
        normalized_style_id = str(last_style_id).strip()
        if normalized_style_id:
            payload["last_style_id"] = normalized_style_id
    if last_layout_mode is not None:
        normalized_layout_mode = str(last_layout_mode).strip()
        if normalized_layout_mode:
            payload["last_layout_mode"] = normalized_layout_mode
    if last_overwrite_existing is not None:
        payload["last_overwrite_existing"] = bool(last_overwrite_existing)

    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def resolve_path_value(value, project_root=None):
    candidate = str(value or "").strip()
    if not candidate:
        return None
    path = Path(candidate)
    if path.is_absolute():
        return str(path)
    resolved_root = _resolve_project_root(project_root)
    return str((resolved_root / path).resolve())


def resolve_translation_config(project_root=None, settings=None):
    payload = deepcopy(settings if settings is not None else load_settings(project_root))
    translation = payload.get("translation") or {}
    return {
        "model": str(translation.get("model") or "mimo-v2.5-pro"),
        "base_url": str(translation.get("base_url") or "https://your-openai-compatible-base-url/v1"),
        "api_key": str(translation.get("api_key") or ""),
        "request_timeout_seconds": float(translation.get("request_timeout_seconds") or 90.0),
        "curl_timeout_seconds": int(float(translation.get("curl_timeout_seconds") or 95)),
    }


def resolve_ocr_config(project_root=None, settings=None):
    payload = deepcopy(settings if settings is not None else load_settings(project_root))
    ocr = payload.get("ocr") or {}
    engine = str(ocr.get("engine") or "48px_ocr").strip() or "48px_ocr"
    secondary_engine = str(ocr.get("secondary_engine") or "manga_ocr").strip() or "manga_ocr"
    return {
        "source_language": str(ocr.get("source_language") or "japanese").strip() or "japanese",
        "engine": engine,
        "enable_hybrid": bool(ocr.get("enable_hybrid", True)),
        "secondary_engine": secondary_engine,
        "hybrid_threshold": float(ocr.get("hybrid_threshold", 0.2) or 0.2),
        "fallback_to_manga_ocr_when_48px_unavailable": bool(
            ocr.get("fallback_to_manga_ocr_when_48px_unavailable", True)
        ),
    }


def resolve_translation_prompt_config(project_root=None, settings=None, prompt_profile=None):
    payload = deepcopy(settings if settings is not None else load_settings(project_root))
    default_prompt_config = deepcopy(_DEFAULT_TRANSLATION_PROMPTS)
    if settings is None:
        resolved_root = _resolve_project_root(project_root)
        defaults = _load_json(resolved_root / "config" / "defaults.json")
        default_prompt_config = _deep_merge(
            default_prompt_config,
            ((defaults.get("prompts") or {}).get("translation") or {}),
        )

    prompt_config = _deep_merge(
        default_prompt_config,
        ((payload.get("prompts") or {}).get("translation") or {}),
    )
    selected_profile = str(prompt_profile or "").strip()
    if selected_profile and selected_profile != "default":
        profile_config = (prompt_config.get("profiles") or {}).get(selected_profile) or {}
        prompt_config = _deep_merge(prompt_config, profile_config)
    rounds = prompt_config.get("rounds") or {}
    default_rounds = default_prompt_config["rounds"]
    return {
        "system": str(prompt_config.get("system") or default_prompt_config["system"]),
        "rounds": {
            "draft": str(rounds.get("draft") or default_rounds["draft"]),
            "contextual": str(rounds.get("contextual") or default_rounds["contextual"]),
            "final": str(rounds.get("final") or default_rounds["final"]),
        },
    }


def resolve_runtime_config(project_root=None, settings=None):
    payload = deepcopy(settings if settings is not None else load_settings(project_root))
    runtime = payload.get("runtime") or {}
    operation_timeouts = runtime.get("saber_operation_timeout_seconds") or {}
    normalized_operation_timeouts = {}
    if isinstance(operation_timeouts, dict):
        for operation, raw_value in operation_timeouts.items():
            key = str(operation or "").strip()
            if not key:
                continue
            normalized_operation_timeouts[key] = float(raw_value or 0.0)
    return {
        "saber_session_timeout_seconds": float(runtime.get("saber_session_timeout_seconds") or 45.0),
        "saber_subprocess_timeout_seconds": float(runtime.get("saber_subprocess_timeout_seconds") or 45.0),
        "saber_operation_timeout_seconds": normalized_operation_timeouts,
    }


def resolve_pipeline_config(project_root=None, settings=None):
    payload = deepcopy(settings if settings is not None else load_settings(project_root))
    pipeline = payload.get("pipeline") or {}
    translation_quality = str(pipeline.get("translation_quality") or "high").strip().lower()
    if translation_quality not in {"fast", "balanced", "high"}:
        translation_quality = "high"
    raw_context_file_names = pipeline.get("manga_context_file_names")
    if isinstance(raw_context_file_names, str):
        context_file_names = [
            item.strip()
            for item in raw_context_file_names.replace(";", ",").split(",")
            if item.strip()
        ]
    elif isinstance(raw_context_file_names, list):
        context_file_names = [str(item).strip() for item in raw_context_file_names if str(item).strip()]
    else:
        context_file_names = []

    if not context_file_names:
        context_file_names = ["manga_context.md", "manga_context.txt"]

    return {
        "overwrite_existing": bool(pipeline.get("overwrite_existing", False)),
        "debug_output": bool(pipeline.get("debug_output", True)),
        "debug_flush_interval": max(1, int(pipeline.get("debug_flush_interval", 25) or 25)),
        "color_fast_mode": bool(pipeline.get("color_fast_mode", True)),
        "translation_quality": translation_quality,
        "skip_frontmatter": bool(pipeline.get("skip_frontmatter", True)),
        "translate_batch_size": max(1, int(pipeline.get("translate_batch_size", 3) or 3)),
        "translate_batch_max_chars": max(1, int(pipeline.get("translate_batch_max_chars", 1600) or 1600)),
        "manga_context_file_names": context_file_names,
        "auto_generate_manga_context": bool(pipeline.get("auto_generate_manga_context", True)),
    }
