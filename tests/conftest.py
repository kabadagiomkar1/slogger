from pathlib import Path

import pytest

from slogger import capture_logs
from slogger.config import reset

REPO_ROOT = Path(__file__).resolve().parent.parent


def fixture_path(name: str) -> str:
    """Return a fixture path relative to the repository root."""
    return f"tests/fixtures/logs/{name}"


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    reset()


@pytest.fixture
def records():
    reset()
    with capture_logs() as found:
        yield found
