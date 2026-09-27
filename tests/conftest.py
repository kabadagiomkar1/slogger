import pytest

from slogger import capture_logs
from slogger.config import reset


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    reset()


@pytest.fixture
def records():
    reset()
    with capture_logs() as found:
        yield found
