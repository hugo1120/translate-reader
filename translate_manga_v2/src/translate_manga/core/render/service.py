from translate_manga.integrations.saber_loader import run_saber_task


def render_page(
    clean_image_path,
    page_id,
    bubbles,
    output_path=None,
    auto_font_size=True,
    auto_font_settings=None,
    saber_session=None,
):
    payload = {
        "clean_image_path": clean_image_path,
        "page_id": page_id,
        "bubbles": bubbles,
        "output_path": output_path,
        "auto_font_size": auto_font_size,
        "auto_font_settings": auto_font_settings,
    }
    if saber_session is None:
        return run_saber_task("render", payload)
    return run_saber_task("render", payload, session=saber_session)
