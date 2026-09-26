"""Structured logging on top of the stdlib :mod:`logging` package."""

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
from slogger.span import Span

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
    "SLogger",
    "Span",
    "builtin_logger",
    "configure",
    "get_batched_structured_file_handler",
    "get_console_handler",
    "get_logger",
    "get_structured_file_handler",
    "instrument",
    "run_in_executor",
    "wrap_context",
]
