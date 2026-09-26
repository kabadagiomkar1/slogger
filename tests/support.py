"""Shared helpers for the test suite."""

from __future__ import annotations

import json
import logging

from slogger.formatters import JSONFormatter


class Capture(logging.Handler):
    """Collect JSON-rendered log records as dicts."""

    def __init__(self, records: list):
        super().__init__(level=logging.DEBUG)
        self.records = records
        self.setFormatter(JSONFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))
