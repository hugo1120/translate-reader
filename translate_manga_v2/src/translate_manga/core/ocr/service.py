from translate_manga.config.settings import resolve_ocr_config
from translate_manga.integrations.saber_loader import has_saber_48px_color_model, run_saber_task


def resolve_saber_ocr_options(overrides=None):
    config = resolve_ocr_config()
    overrides = overrides or {}
    engine = config["engine"]
    enable_hybrid_ocr = bool(config["enable_hybrid"])
    secondary_ocr_engine = config["secondary_engine"]
    hybrid_ocr_threshold = float(config["hybrid_threshold"])
    source_language = str(config.get("source_language") or "japanese").strip() or "japanese"

    if "engine" in overrides and overrides.get("engine"):
        engine = str(overrides.get("engine")).strip()
    if "enable_hybrid" in overrides:
        enable_hybrid_ocr = bool(overrides.get("enable_hybrid"))
    if "secondary_engine" in overrides:
        secondary_ocr_engine = overrides.get("secondary_engine")
    if "hybrid_threshold" in overrides and overrides.get("hybrid_threshold") is not None:
        hybrid_ocr_threshold = float(overrides.get("hybrid_threshold"))
    if "source_language" in overrides and overrides.get("source_language"):
        source_language = str(overrides.get("source_language")).strip()
    reading_order = str(overrides.get("reading_order") or "").strip()

    if config["fallback_to_manga_ocr_when_48px_unavailable"] and (
        engine == "48px_ocr" or secondary_ocr_engine == "48px_ocr"
    ):
        if not has_saber_48px_color_model():
            engine = "manga_ocr"
            enable_hybrid_ocr = False
            secondary_ocr_engine = None

    payload = {
        "source_language": source_language,
        "ocr_engine": engine,
        "enable_hybrid_ocr": enable_hybrid_ocr,
        "hybrid_ocr_threshold": hybrid_ocr_threshold,
    }
    if reading_order:
        payload["reading_order"] = reading_order
    if enable_hybrid_ocr and secondary_ocr_engine:
        payload["secondary_ocr_engine"] = secondary_ocr_engine
    return payload


def ocr_page(image_path, bubble_coords, textlines_per_bubble=None, ocr_options=None):
    return run_saber_task(
        "ocr",
        {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "textlines_per_bubble": textlines_per_bubble or [],
            **resolve_saber_ocr_options(ocr_options),
        },
    )
