import json
import logging

import pytest

from slogger.config import configure, reset
from slogger.formatters import JSONFormatter


class Capture(logging.Handler):
    def __init__(self, records: list):
        super().__init__(level=logging.DEBUG)
        self.records = records
        self.setFormatter(JSONFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))


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
