import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import create_app


@pytest.fixture
def app(tmp_path):
    data_root = tmp_path / "data"
    return create_app({"TESTING": True, "DATA_ROOT": str(data_root)})


@pytest.fixture
def client(app):
    return app.test_client()
