"""Console presentation for canonical slogger records and generic JSON objects."""

from __future__ import annotations

import json
from typing import Any

from rich.text import Text

from ..sources import parse_timestamp

HIDDEN_FIELDS = frozenset(
    {
        "file",
        "func",
        "line",
        "trace_id",
        "span_id",
        "parent_span_id",
        "event",
        "duration_ms",
        "exception",
        "stack",
        "error",
        "error_type",
        "status",
        "filename",
        "function",
        "lineno",
        "span_name",
        "trace_name",
        "pathname",
        "module",
        "funcName",
        "process",
        "processName",
        "thread",
        "threadName",
        "stack_info",
        "exc_info",
        "traceback",
        "name",
        "created",
        "msecs",
        "relativeCreated",
    }
)
CONSOLE_FIELDS = frozenset({"timestamp", "level", "logger", "message", "span"})


def _column(value: object, width: int, style: str = "") -> Text:
    text = Text(str(value) if value is not None else "", style=style)
    text.truncate(width, overflow="ellipsis")
    text.pad_right(max(0, width - text.cell_len))
    return text


def console_text(record: dict[str, Any]) -> Text:
    """Columns use terminal cell widths; only console columns may elide values."""
    moment = parse_timestamp(record.get("timestamp"))
    timestamp = moment.strftime("%H:%M:%S.%f")[:12] if moment else record.get("timestamp", "")
    text = _column(timestamp, 12, "dim")
    text.append(" ")
    level = record.get("level", "")
    text.append_text(_column(level, 7, "red" if level in ("ERROR", "CRITICAL") else "cyan"))
    text.append(" ")
    text.append_text(_column(record.get("logger", ""), 20, "dim"))
    text.append(" ")
    generic = not CONSOLE_FIELDS.intersection(record)
    message = json.dumps(record, ensure_ascii=False) if generic else record.get("message", "")
    text.append(message if isinstance(message, str) else json.dumps(message, ensure_ascii=False))
    span = record.get("span", record.get("span_name"))
    if span is not None:
        text.append(f" [{span}]", style="magenta")
    for key, value in record.items():
        if not generic and key not in HIDDEN_FIELDS | CONSOLE_FIELDS:
            text.append(f" {key}=", style="dim")
            text.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return text
