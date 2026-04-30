from pathlib import Path


def test_health_route_and_data_dirs(tmp_path):
    from src.app import create_app

    app = create_app({"TESTING": True, "DATA_ROOT": str(tmp_path / "data")})
    client = app.test_client()

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

    data_root = Path(app.config["DATA_ROOT"])
    assert (data_root / "library" / "current" / "pages").exists()
    assert (data_root / "cache" / "pages").exists()
    assert (data_root / "exports").exists()
