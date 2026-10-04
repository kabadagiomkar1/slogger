"""Console presentation for canonical slogger records and generic JSON objects."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from rich.style import Style
from rich.text import Text

from ..core.encoding import json_spelling
from ..sources import parse_timestamp
from .text import visible_text

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


def _token(
    text: Text,
    display: str,
    source: str,
    *,
    encoded: bool = False,
    style: str = "",
    offset: int = 0,
) -> None:
    start = len(text)
    # Only literal tabs depend on the preceding display column. JSON spellings
    # already escape them; scanning the growing prefix per scalar is quadratic.
    column = len(text.plain.rsplit("\n", 1)[-1]) if not encoded and "\t" in display else 0
    mapped = False
    if not encoded:
        rendered = visible_text(display, multiline=True, column=column)
        mapped = rendered != display
        display = rendered
    text.append(display, style=style)
    text.stylize(
        Style(
            meta={
                "search_source": source,
                "search_json": encoded,
                "search_offset": offset,
                "search_column": column,
                "search_rendered": mapped,
            }
        ),
        start,
        len(text),
    )


def _json(text: Text, value: Any, *, fields: bool = False) -> None:
    if isinstance(value, dict):
        text.append("{")
        for index, (key, child) in enumerate(value.items()):
            if index:
                text.append(",")
            start = len(text)
            _token(text, json_spelling(key), key, encoded=True)
            text.append(":")
            _json(text, child)
            if fields and key:
                text.stylize(Style(meta={"field_path": (key,)}), start, len(text))
        text.append("}")
    elif isinstance(value, list):
        text.append("[")
        for index, child in enumerate(value):
            if index:
                text.append(",")
            _json(text, child)
        text.append("]")
    else:
        display = json_spelling(value, separators=(",", ":"))
        _token(
            text,
            display,
            value if isinstance(value, str) else display,
            encoded=isinstance(value, str),
        )


def _column(
    value: object,
    width: int,
    style: str = "",
    field: str = "",
    *,
    original: str | None = None,
    offset: int = 0,
) -> Text:
    display = str(value) if value is not None else ""
    source = display if original is None else original
    text = Text()
    _token(text, display, source, style=style, offset=offset)
    text.truncate(width, overflow="ellipsis")
    text.pad_right(max(0, width - text.cell_len))
    if field:
        text.stylize(Style(meta={"field_path": (field,)}))
    return text


def console_text(
    record: dict[str, Any], options: ConsoleOptions | None = None, *, light: bool = False
) -> Text:
    """Columns use terminal cell widths; only console columns may elide values."""
    options = options or ConsoleOptions()
    muted = "#596574" if light else "#91a0b2"
    accent = "#7440a0" if light else "#c8a0e8"
    level_color = "#b42332" if light else "#ff7b86"
    normal_level = "#12658d" if light else "#80c7de"
    moment = parse_timestamp(record.get("timestamp"))
    timestamp = record.get("timestamp", "")
    width = 32 if options.timestamp_mode == "original" else 12
    if options.timestamp_mode == "datetime":
        width = 23
        if moment:
            timestamp = moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    elif options.timestamp_mode == "time" and moment:
        timestamp = moment.strftime("%H:%M:%S.%f")[:12]
    original = str(record.get("timestamp", ""))
    offset = (
        max(0, original.find(str(timestamp).split(".", 1)[0]))
        if options.timestamp_mode == "time"
        else 0
    )
    text = _column(
        timestamp,
        width,
        muted,
        "timestamp" if "timestamp" in record else "",
        original=original,
        offset=offset,
    )
    text.append(" ")
    level = record.get("level", "")
    text.append_text(
        _column(
            level,
            7,
            level_color if level in ("ERROR", "CRITICAL") else normal_level,
            "level" if "level" in record else "",
        )
    )
    text.append(" ")
    text.append_text(
        _column(record.get("logger", ""), 20, muted, "logger" if "logger" in record else "")
    )
    text.append(" ")
    generic = not CONSOLE_FIELDS.intersection(record)
    start = len(text)
    message = record if generic else record.get("message", "")
    if isinstance(message, str):
        _token(text, message, message)
    else:
        _json(text, message, fields=generic)
    if not generic and "message" in record:
        text.stylize(Style(meta={"field_path": ("message",)}), start, len(text))
    span = record.get("span", record.get("span_name"))
    if span is not None:
        start = len(text)
        text.append(" [", style=accent)
        if isinstance(span, str):
            _token(text, span, span, style=accent)
        else:
            _json(text, span)
        text.append("]", style=accent)
        text.stylize(
            Style(meta={"field_path": ("span" if "span" in record else "span_name",)}),
            start,
            len(text),
        )
    for key, value in console_fields(record, options):
        if not generic and key not in CONSOLE_FIELDS | {"span_name"}:
            start = len(text)
            text.append(" ")
            _token(text, key, key, style=muted)
            text.append("=", style=muted)
            _json(text, value)
            if key:
                text.stylize(Style(meta={"field_path": (key,)}), start, len(text))
    return text
