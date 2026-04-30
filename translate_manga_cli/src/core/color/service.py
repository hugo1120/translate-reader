from src.integrations.saber_loader import has_saber_48px_color_model, run_saber_task


def extract_bubble_colors(image_path, bubble_coords, textlines_per_bubble):
    if not has_saber_48px_color_model():
        return {
            "colors": [
                {
                    "textColor": None,
                    "bgColor": None,
                    "autoFgColor": None,
                    "autoBgColor": None,
                    "colorConfidence": 0.0,
                }
                for _ in bubble_coords
            ]
        }
    return run_saber_task(
        "color",
        {
            "image_path": image_path,
            "bubble_coords": bubble_coords,
            "textlines_per_bubble": textlines_per_bubble,
        },
    )
