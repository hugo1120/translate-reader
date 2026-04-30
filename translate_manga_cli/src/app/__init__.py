from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS


def create_app(test_config=None):
    static_folder = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_folder), static_url_path="")
    CORS(app)

    project_root = Path(__file__).resolve().parents[2]
    data_root = project_root / "data"

    defaults = {
        "DATA_ROOT": str(data_root),
        "LIBRARY_ROOT": str(data_root / "library" / "current"),
        "CACHE_ROOT": str(data_root / "cache"),
        "EXPORT_ROOT": str(data_root / "exports"),
    }
    app.config.update(defaults)
    if test_config:
        app.config.update(test_config)
    _normalize_storage_config(app)

    _ensure_data_dirs(app)

    from .routes.health import health_bp
    from .routes.library import library_bp
    from .routes.pipeline import pipeline_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(pipeline_bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/data/<path:filename>")
    def data_files(filename):
        return send_from_directory(app.config["DATA_ROOT"], filename)

    return app


def _normalize_storage_config(app):
    data_root = Path(app.config["DATA_ROOT"])
    app.config["LIBRARY_ROOT"] = str(data_root / "library" / "current")
    app.config["CACHE_ROOT"] = str(data_root / "cache")
    app.config["EXPORT_ROOT"] = str(data_root / "exports")


def _ensure_data_dirs(app):
    data_root = Path(app.config["DATA_ROOT"])
    for path in (
        data_root / "library" / "current" / "pages",
        data_root / "cache" / "pages",
        data_root / "exports",
    ):
        path.mkdir(parents=True, exist_ok=True)
