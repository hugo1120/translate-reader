from src.config.settings import resolve_ocr_config
from src.integrations.saber_loader import has_saber_48px_color_model, run_saber_task


def resolve_saber_ocr_options():
    config = resolve_ocr_config()
    engine = config["engine"]
    enable_hybrid_ocr = bool(config["enable_hybrid"])
    secondary_ocr_engine = config["secondary_engine"]
    hybrid_ocr_threshold = float(config["hybrid_threshold"])

    if config["fallback_to_manga_ocr_when_48px_unavailable"] and (
        engine == "48px_ocr" or secondary_ocr_engine == "48px_ocr"
    ):
        if not has_saber_48px_color_model():
            engine = "manga_ocr"
            enable_hybrid_ocr = False
            secondary_ocr_engine = None

    payload = {
        "ocr_engine": engine,
        "enable_hybrid_ocr": enable_hybrid_ocr,
        "hybrid_ocr_threshold": hybrid_ocr_threshold,
    }
    if enable_hybrid_ocr and secondary_ocr_engine:
        payload["secondary_ocr_engine"] = secondary_ocr_engine
    return payload


def ocr_page(image_path, bubble_coords, textlines_per_bubble=None):
    return run_saber_task(
        "ocr",
        {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "textlines_per_bubble": textlines_per_bubble or [],
            **resolve_saber_ocr_options(),
        },
    )
