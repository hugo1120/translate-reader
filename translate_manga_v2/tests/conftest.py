import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from translate_manga.core.pipeline.runtime import PipelineRuntime


@pytest.fixture
def runtime(tmp_path):
    return PipelineRuntime(tmp_path / "workspace")


@pytest.fixture
def app(runtime):
    return runtime
