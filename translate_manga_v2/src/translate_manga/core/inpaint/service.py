from translate_manga.integrations.saber_loader import run_saber_task


def inpaint_page(
    image_path,
    bubble_coords,
    raw_mask=None,
    bubble_polygons=None,
    output_path=None,
    method="solid",
    saber_session=None,
    mask_dilate_size=1,
    mask_box_expand_ratio=0,
):
    payload = {
        "image_path": image_path,
        "bubble_coords": bubble_coords,
        "raw_mask": raw_mask,
        "bubble_polygons": bubble_polygons or [],
        "output_path": output_path,
        "method": method,
        "mask_dilate_size": int(mask_dilate_size or 0),
        "mask_box_expand_ratio": int(mask_box_expand_ratio or 0),
    }
    if method != "solid":
        payload["lama_model"] = method
    if saber_session is None:
        return run_saber_task("inpaint", payload)
    return run_saber_task("inpaint", payload, session=saber_session)
