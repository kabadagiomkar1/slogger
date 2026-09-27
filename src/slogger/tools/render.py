"""Render structured log dicts for console and JSON output."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from slogger.formatters import ConsoleFormatter, format_value, json_default
from slogger.schema import SCHEMA_KEYS, SPAN_FIELD_ORDER


def use_color(stream: object, *, force: bool | None = None) -> bool:
    """Match :meth:`ConsoleFormatter._use_color` rules for an arbitrary stream."""
    if force is True:
        return True
    if force is False:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if "NO_COLOR" in os.environ:
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def render_console_line(record: Mapping[str, Any], *, color: bool) -> str:
    """Render one record the way :class:`ConsoleFormatter` would."""
    timestamp = record.get("timestamp")
    level = record.get("level")
    logger_name = record.get("logger")
    message = record.get("message")

    ts_text = str(timestamp) if isinstance(timestamp, str) and timestamp else "-"
    level_text = f"{str(level):<8}" if level not in (None, "") else f"{'-':<8}"
    logger_text = str(logger_name) if logger_name not in (None, "") else "-"
    message_text = "" if message is None else str(message)

    if color:
        colors = ConsoleFormatter.COLORS
        reset = ConsoleFormatter.RESET
        level_key = str(level) if isinstance(level, str) else ""
        level_text = f"{colors.get(level_key, reset)}{level_text}{reset}"
        message_text = f"{ConsoleFormatter.WHITE}{message_text}{reset}"

    user_keys = sorted(
        key
        for key in record
        if key not in SCHEMA_KEYS
        and key not in SPAN_FIELD_ORDER
        and key != "_id"
        and key not in ("exception", "stack")
    )
    parts = [f"{key}={format_value(record[key])}" for key in user_keys]
    tail = [
        f"{key}={format_value(record[key])}"
        for key in SPAN_FIELD_ORDER
        if key in record
    ]
    if color and tail:
        dim = ConsoleFormatter.DIM
        reset = ConsoleFormatter.RESET
        tail = [f"{dim}{part}{reset}" for part in tail]

    line = f"{ts_text} {level_text} {logger_text}  {message_text}"
    fields = parts + tail
    if fields:
        line += "  " + " ".join(fields)

    exception = record.get("exception")
    if isinstance(exception, str) and exception:
        line += "\n" + exception
    stack = record.get("stack")
    if isinstance(stack, str) and stack:
        line += "\n" + stack
    return line


def render_json_line(record: Mapping[str, Any]) -> str:
    return json.dumps(record, default=json_default, ensure_ascii=False)


def project(
    record: Mapping[str, Any],
    fields: Sequence[str] | None,
    truncate: int | None,
) -> dict[str, Any]:
    """Project and optionally truncate string values. Always keeps ``_id``."""
    if fields is None:
        out = dict(record)
    else:
        out = {"_id": record.get("_id")}
        for key in fields:
            if key in record:
                out[key] = record[key]
    if truncate is not None:
        for key, value in list(out.items()):
            if isinstance(value, str) and len(value) > truncate:
                out[key] = value[:truncate] + "..."
    return out
