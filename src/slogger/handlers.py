"""Handler factories for console and rotating JSON files."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from slogger.formatters import ConsoleFormatter, JSONFormatter


def get_console_handler(
    level: int = logging.INFO,
    stream=None,
    color: bool | None = None,
) -> logging.Handler:
    """Stderr (or ``stream``) handler using :class:`ConsoleFormatter`."""
    if stream is None:
        stream = sys.stderr
    console_handler = logging.StreamHandler(stream)
    console_handler.setFormatter(ConsoleFormatter(color=color, stream=stream))
    console_handler.setLevel(level)
    return console_handler


def get_structured_file_handler(filename: str, level: int = logging.INFO) -> logging.Handler:
    """UTC midnight-rotating file handler that writes one JSON object per line.

    Seven rotated files are kept.
    """
    structured_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=filename,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
        utc=True,
    )
    structured_file_handler.setFormatter(JSONFormatter())
    structured_file_handler.setLevel(level)
    return structured_file_handler


def get_batched_structured_file_handler(
    filename: str,
    level: int = logging.INFO,
) -> logging.Handler:
    """Buffer JSON records and flush at 10 records or on ERROR, whichever comes first."""
    structured_file_handler = get_structured_file_handler(filename, level=level)
    return logging.handlers.MemoryHandler(
        capacity=10,
        flushLevel=logging.ERROR,
        target=structured_file_handler,
    )
