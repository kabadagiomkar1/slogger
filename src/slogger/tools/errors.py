"""Errors raised by :mod:`slogger.tools`."""

from __future__ import annotations


class ToolError(Exception):
    """A data or selection error with a stable ``code`` for machine output."""

    def __init__(self, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"error": self.code, "message": self.message}
        payload.update(self.extra)
        return payload


class CursorError(ToolError):
    """The ``--after`` cursor is not valid for the current input set."""

    def __init__(self, message: str, **extra: object) -> None:
        super().__init__("cursor_invalid", message, **extra)
