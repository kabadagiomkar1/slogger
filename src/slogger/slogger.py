"""Compatibility shim. Prefer ``import slogger``.

``from slogger.slogger import builtin_logger, instrument`` keeps working.
"""

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

__all__ = [
    "CRITICAL",
    "DEBUG",
    "ERROR",
    "FATAL",
    "INFO",
    "WARNING",
    "SLogger",
    "builtin_logger",
    "get_logger",
    "instrument",
]
