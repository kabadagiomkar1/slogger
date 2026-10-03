"""Structured logging on top of the stdlib :mod:`logging` package.

Quick start::

    import slogger

    slogger.configure(level=slogger.INFO, json_file="app.log")
    log = slogger.get_logger("app")
    log.info("started", version="1.4.0")

    with log.span("checkout", user="ada"):
        log.info("charging", order_id="42")

Public exports are listed in ``__all__``. Finite-source query tooling lives
in :mod:`slogger.tools` and is documented in ``docs/api.md``.
"""

from slogger.config import configure
from slogger.context import run_in_executor, wrap_context
from slogger.formatters import ColoredFormatter, ConsoleFormatter, JSONFormatter
from slogger.handlers import (
    get_batched_structured_file_handler,
    get_console_handler,
    get_structured_file_handler,
)
from slogger.instrument import instrument
from slogger.logger import (
    CRITICAL,
    DEBUG,
    ERROR,
    FATAL,
    INFO,
    WARNING,
    SLogger,
    builtin_logger,
    get_logger,
)
from slogger.schema import (
    LogRecord,
    log_record_json_schema,
    validate_log_record,
)
from slogger.span import Span
from slogger.testing import capture_logs

__all__ = [
    "CRITICAL",
    "DEBUG",
    "ERROR",
    "FATAL",
    "INFO",
    "WARNING",
    "ColoredFormatter",
    "ConsoleFormatter",
    "JSONFormatter",
    "LogRecord",
    "SLogger",
    "Span",
    "builtin_logger",
    "capture_logs",
    "configure",
    "get_batched_structured_file_handler",
    "get_console_handler",
    "get_logger",
    "get_structured_file_handler",
    "instrument",
    "log_record_json_schema",
    "run_in_executor",
    "validate_log_record",
    "wrap_context",
]
