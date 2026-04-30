from io import BytesIO

from PIL import Image


def _png_bytes(color):
    image = Image.new("RGB", (8, 8), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def test_import_list_and_page_detail(client):
    response = client.post(
        "/api/library/import",
        data={
            "files": [
                (_png_bytes("white"), "002.png"),
                (_png_bytes("black"), "001.png"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["imported"] == 2

    pages = client.get("/api/library/pages").get_json()["pages"]
    assert [page["fileName"] for page in pages] == ["001.png", "002.png"]

    detail = client.get(f"/api/library/page/{pages[0]['id']}").get_json()
    assert detail["page"]["fileName"] == "001.png"
    assert detail["page"]["sourceUrl"].startswith("/data/library/current/pages/")
    assert detail["page"]["translatedUrl"] is None


def test_import_library_uses_natural_numeric_order(client):
    response = client.post(
        "/api/library/import",
        data={
            "files": [
                (_png_bytes("white"), "10.png"),
                (_png_bytes("black"), "2.png"),
                (_png_bytes("gray"), "1.png"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200

    pages = client.get("/api/library/pages").get_json()["pages"]

    assert [page["fileName"] for page in pages] == ["1.png", "2.png", "10.png"]
