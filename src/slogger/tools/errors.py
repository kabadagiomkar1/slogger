"""Errors raised by :mod:`slogger.tools`."""

from __future__ import annotations


class ToolError(Exception):
    """A query or source error with a stable code and diagnostic context."""

    def __init__(self, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra
