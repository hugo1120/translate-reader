import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.pipeline.runtime import PipelineRuntime


@pytest.fixture
def runtime(tmp_path):
    return PipelineRuntime(tmp_path / "workspace")


@pytest.fixture
def app(runtime):
    return runtime
