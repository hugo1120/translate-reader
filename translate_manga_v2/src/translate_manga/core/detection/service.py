from translate_manga.integrations.saber_loader import run_saber_task


def detect_page(image_path):
    return run_saber_task("detect", {"image_path": image_path})
