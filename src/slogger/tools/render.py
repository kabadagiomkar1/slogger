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

    ts_text = timestamp if isinstance(timestamp, str) and timestamp else "-"
    level_text = f"{str(level):<8}" if level not in (None, "") else f"{'-':<8}"
    logger_text = str(logger_name) if logger_name not in (None, "") else "-"
    message_text = "" if message is None else str(message)

    if color:
        colors = ConsoleFormatter.COLORS
        reset = ConsoleFormatter.RESET
        level_key = level if isinstance(level, str) else ""
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
            if key != "_id" and isinstance(value, str) and len(value) > truncate:
                out[key] = value[:truncate] + "..."
    return out


def render_table(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    *,
    max_width: int = 40,
) -> str:
    """Render ``rows`` as a plain-text table with a header and dash rule."""

    def format_cell(value: object) -> str:
        if value is None:
            text = ""
        else:
            text = str(value)
        if len(text) > max_width:
            return text[: max_width - 3] + "..."
        return text

    def is_numeric_column(name: str) -> bool:
        for row in rows:
            value = row.get(name)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                return False
            if isinstance(value, (int, float)):
                return True
            return False
        return False

    cells = [[format_cell(row.get(column)) for column in columns] for row in rows]
    widths = [len(column) for column in columns]
    for row_cells in cells:
        for index, cell in enumerate(row_cells):
            widths[index] = max(widths[index], len(cell))
    numeric = [is_numeric_column(column) for column in columns]

    def join_row(values: Sequence[str], *, header: bool = False) -> str:
        parts = []
        for index, value in enumerate(values):
            width = widths[index]
            if header or not numeric[index]:
                parts.append(value.ljust(width))
            else:
                parts.append(value.rjust(width))
        return "  ".join(parts)

    header = join_row(list(columns), header=True)
    rule = "  ".join("-" * width for width in widths)
    lines = [header, rule]
    if not cells:
        lines.append("(no rows)")
    else:
        for row_cells in cells:
            lines.append(join_row(row_cells))
    return "\n".join(lines)
