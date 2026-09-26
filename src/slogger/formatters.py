"""Render log records as JSON or as a single console line."""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import enum
import json
import logging
import os
import pathlib
import sys
import uuid

# Name of the LogRecord attribute under which slogger stores user-supplied
# context. Keeping it in a single namespaced attribute means user keys can
# never collide with LogRecord's own attributes (``name``, ``module``, ...).
CONTEXT_ATTR = "slog_context"

# Keys always written by slogger. User context that reuses one of these is
# emitted as ``ctx_<key>`` so the schema stays stable.
SCHEMA_KEYS = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "message",
        "file",
        "func",
        "line",
        "exception",
        "stack",
    }
)

# Span/trace fields rendered after user keys on the console, in this order.
CONSOLE_TAIL_KEYS = (
    "event",
    "status",
    "duration_ms",
    "error_type",
    "error",
    "span",
    "span_id",
    "parent_span_id",
    "trace_id",
)

# Attributes present on every LogRecord, derived from the running interpreter
# so new attributes (e.g. ``taskName`` in 3.12) are excluded automatically.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}

_PLAIN_FORMATTER = logging.Formatter()


def json_default(obj: object) -> object:
    """Fallback serializer so a log call never fails because of its payload."""
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (decimal.Decimal, uuid.UUID, pathlib.PurePath)):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, BaseException):
        return repr(obj)
    return repr(obj)


def format_timestamp(record: logging.LogRecord, datefmt: str | None = None) -> str:
    """UTC ISO-8601 with milliseconds, unless ``datefmt`` overrides it."""
    if datefmt:
        return _PLAIN_FORMATTER.formatTime(record, datefmt)
    moment = datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


def record_to_dict(record: logging.LogRecord, datefmt: str | None = None) -> dict[str, object]:
    """Flat structured view of ``record``.

    Fixed schema keys come first. Stdlib ``extra`` fields and slogger context
    are merged on top; a key that would overwrite the schema is prefixed with
    ``ctx_``.
    """
    data: dict[str, object] = {
        "timestamp": format_timestamp(record, datefmt),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "file": record.filename,
        "func": record.funcName,
        "line": record.lineno,
    }
    if record.exc_info:
        data["exception"] = _PLAIN_FORMATTER.formatException(record.exc_info)
    if record.stack_info:
        data["stack"] = _PLAIN_FORMATTER.formatStack(record.stack_info)

    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and key != CONTEXT_ATTR
    }
    context = getattr(record, CONTEXT_ATTR, None) or {}

    for key, value in {**extras, **context}.items():
        output_key = f"ctx_{key}" if key in SCHEMA_KEYS else key
        while output_key in data:
            output_key = f"ctx_{output_key}"
        data[output_key] = value
    return data


def format_value(value: object) -> str:
    """Render one context value for the console line."""
    if isinstance(value, str):
        if value == "" or any(ch.isspace() for ch in value) or "=" in value:
            return repr(value)
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=json_default)
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
    return str(json_default(value)) if not isinstance(value, str) else value


class JSONFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_to_dict(record, self.datefmt), default=json_default)


class ConsoleFormatter(logging.Formatter):
    """``timestamp LEVEL logger message key=value`` for humans.

    ``color=None`` (the default) enables ANSI colours when ``stream`` is a TTY,
    ``NO_COLOR`` is unset, and ``FORCE_COLOR`` is not required. Pass ``True`` or
    ``False`` to force the choice. ``FORCE_COLOR`` turns colour on in auto mode;
    ``NO_COLOR`` turns it off unless ``FORCE_COLOR`` is also set.
    """

    COLORS = {
        "DEBUG": "\033[1;36m",
        "INFO": "\033[1;32m",
        "WARNING": "\033[1;33m",
        "ERROR": "\033[1;31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"
    WHITE = "\033[1;37m"
    DIM = "\033[2m"

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        *,
        color: bool | None = None,
        stream: object | None = None,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.color = color
        self.stream = stream if stream is not None else sys.stderr

    def _use_color(self) -> bool:
        if self.color is True:
            return True
        if self.color is False:
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        if "NO_COLOR" in os.environ:
            return False
        isatty = getattr(self.stream, "isatty", None)
        if not callable(isatty):
            return False
        try:
            return bool(isatty())
        except Exception:
            return False

    def format(self, record: logging.LogRecord) -> str:
        data = record_to_dict(record, self.datefmt)
        use_color = self._use_color()

        level_name = f"{record.levelname:<8}"
        message = str(data["message"])
        if use_color:
            color = self.COLORS.get(record.levelname, self.RESET)
            level_name = f"{color}{level_name}{self.RESET}"
            message = f"{self.WHITE}{message}{self.RESET}"

        user_keys = [
            key
            for key in data
            if key not in SCHEMA_KEYS and key not in CONSOLE_TAIL_KEYS
        ]
        parts = [f"{key}={format_value(data[key])}" for key in sorted(user_keys)]
        tail = [
            f"{key}={format_value(data[key])}"
            for key in CONSOLE_TAIL_KEYS
            if key in data
        ]
        if use_color and tail:
            tail = [f"{self.DIM}{part}{self.RESET}" for part in tail]

        line = f"{data['timestamp']} {level_name} {data['logger']}  {message}"
        fields = parts + tail
        if fields:
            line += "  " + " ".join(fields)

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            line += "\n" + self.formatStack(record.stack_info)
        return line


# Previous name, kept so existing imports continue to work.
ColoredFormatter = ConsoleFormatter
