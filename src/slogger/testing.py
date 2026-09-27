"""Helpers for asserting on structured log output in tests."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from slogger.config import configure, is_configured
from slogger.filters import ContextFilter
from slogger.formatters import JSONFormatter
from slogger.logger import DEBUG
from slogger.schema import LogRecord


class _CapturingHandler(logging.Handler):
    """Collect JSON-rendered records as dicts without writing anywhere."""

    def __init__(self, records: list[LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self.records = records
        self.setFormatter(JSONFormatter())
        self.addFilter(ContextFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))


@contextmanager
def capture_logs(
    *,
    level: int = DEBUG,
    logger: str | None = None,
) -> Iterator[list[LogRecord]]:
    """Capture structured log records while the block runs.

    Yields a list of the same flat dicts that :class:`~slogger.formatters.JSONFormatter`
    would emit (:class:`~slogger.schema.LogRecord` plus open user-context keys).
    The list is mutable and grows as records are emitted.

    A temporary handler is attached to the root logger by default, or to
    ``logging.getLogger(logger)`` when ``logger`` is set. Other handlers are
    left in place. If slogger has never been configured, a silent
    ``configure(console=False)`` runs so the first emit does not also install
    a console handler.

    Example::

        from slogger import capture_logs, get_logger

        def test_checkout():
            log = get_logger("shop")
            with capture_logs() as records:
                log.info("charging", order_id="42")
            assert records[0]["message"] == "charging"
            assert records[0]["order_id"] == "42"
    """
    records: list[LogRecord] = []
    handler = _CapturingHandler(records)
    handler.setLevel(level)

    if not is_configured():
        # Avoid the lazy default (console at INFO) during capture-only tests.
        configure(level=level, console=False)

    target = logging.getLogger(logger) if logger is not None else logging.getLogger()
    previous_level = target.level
    target.addHandler(handler)
    # Make sure the target logger itself will accept records at ``level``.
    if previous_level == logging.NOTSET or previous_level > level:
        target.setLevel(level)
    try:
        yield records
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)
