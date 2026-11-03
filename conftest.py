"""Root conftest: marks the legacy tests, which live directly in tests/."""
from pathlib import Path

import pytest

TESTS = Path(__file__).parent / "tests"
LAYERS = ("unit", "component", "integration", "e2e")


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true", default=False,
                     help="rewrite the expected-JSON files; review the diff before committing (D24)")


def pytest_collection_modifyitems(items):
    """Marker per layer folder; tests directly in tests/ are the legacy suite."""
    for item in items:
        path = Path(str(item.fspath))
        if path.parent == TESTS:
            item.add_marker(pytest.mark.legacy)
        elif path.parent.parent == TESTS / "indexer" and path.parent.name in LAYERS:
            item.add_marker(getattr(pytest.mark, path.parent.name))
