from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_project_root_from_nested_package_file():
    from translate_manga.config.paths import find_project_root

    nested_file = PROJECT_ROOT / "src" / "translate_manga" / "core" / "pipeline" / "service.py"

    assert find_project_root(nested_file) == PROJECT_ROOT
