import logging

import pytest

from slogger.config import configure, reset
from tests.support import Capture


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    reset()


@pytest.fixture
def records():
    reset()
    found: list = []
    configure(level=logging.DEBUG, console=False, handlers=[Capture(found)])
    yield found
