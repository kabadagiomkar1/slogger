"""Console presentation for canonical slogger records and generic JSON objects."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

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


@dataclass(frozen=True)
class ConsoleOptions:
    """Temporary consumer presentation choices; captured records stay unchanged."""

    wrap: bool = False
    timestamp_mode: Literal["time", "datetime", "original"] = "time"
    show_duration: bool = False

    def __post_init__(self) -> None:
        if self.timestamp_mode not in ("time", "datetime", "original"):
            raise ValueError("timestamp_mode must be time, datetime, or original")


def console_fields(
    record: dict[str, Any], options: ConsoleOptions | None = None
) -> Iterator[tuple[str, Any]]:
    """Yield complete original console names/values, before formatting or clipping.

    This consumer field policy can supply later console search independently of
    timestamp formatting, ellipsis, wrapping, and horizontal viewport position.
    """
    options = options or ConsoleOptions()
    if not CONSOLE_FIELDS.intersection(record):
        yield from record.items()
        return
    for key, value in record.items():
        if key in CONSOLE_FIELDS or key not in HIDDEN_FIELDS:
            yield key, value
        elif key == "span_name" and "span" not in record:
            yield key, value
        elif key == "duration_ms" and options.show_duration:
            yield key, value


def _column(value: object, width: int, style: str = "") -> Text:
    text = Text(str(value) if value is not None else "", style=style)
    text.truncate(width, overflow="ellipsis")
    text.pad_right(max(0, width - text.cell_len))
    return text


def console_text(record: dict[str, Any], options: ConsoleOptions | None = None) -> Text:
    """Columns use terminal cell widths; only console columns may elide values."""
    options = options or ConsoleOptions()
    moment = parse_timestamp(record.get("timestamp"))
    timestamp = record.get("timestamp", "")
    width = 32 if options.timestamp_mode == "original" else 12
    if options.timestamp_mode == "datetime":
        width = 23
        if moment:
            timestamp = moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    elif options.timestamp_mode == "time" and moment:
        timestamp = moment.strftime("%H:%M:%S.%f")[:12]
    text = _column(timestamp, width, "dim")
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
    for key, value in console_fields(record, options):
        if not generic and key not in CONSOLE_FIELDS | {"span_name"}:
            text.append(f" {key}=", style="dim")
            text.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return text
