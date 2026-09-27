"""Formal contract for one slogger JSON log line.

``LogRecord`` is the TypedDict consumers should annotate parsed lines with.
``log_record_json_schema()`` returns the same contract as a JSON Schema draft
2020-12 document for non-Python tools. Extra keys (bound fields, call kwargs,
and ``ctx_``-prefixed collisions) are allowed on both.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Literal, Mapping, TypedDict, cast

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

# Well-known span / trace fields, in console-render order. Not reserved against
# user keys the way SCHEMA_KEYS are, but part of the published contract when present.
SPAN_FIELD_ORDER = (
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
SPAN_KEYS = frozenset(SPAN_FIELD_ORDER)

REQUIRED_KEYS = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "message",
        "file",
        "func",
        "line",
    }
)

SpanEvent = Literal["span.start", "span.end"]
SpanStatus = Literal["ok", "error"]


class _LogRecordRequired(TypedDict):
    timestamp: str
    level: str
    logger: str
    message: str
    file: str
    func: str
    line: int


class LogRecord(_LogRecordRequired, total=False):
    """One flattened JSON object emitted by :class:`~slogger.formatters.JSONFormatter`.

    Required fields are always present. Optional fields appear when the record
    carries an exception, a stack dump, or span/trace context. Any additional
    keys are user context (or ``ctx_``-prefixed collisions with reserved names).
    """

    exception: str
    stack: str
    event: SpanEvent
    status: SpanStatus
    duration_ms: float
    error_type: str
    error: str
    span: str
    span_id: str
    parent_span_id: str
    trace_id: str


def log_record_json_schema() -> dict[str, Any]:
    """Return the JSON Schema (draft 2020-12) for a slogger log record."""
    schema_path = resources.files("slogger").joinpath("schemas").joinpath(
        "log-record.schema.json"
    )
    with schema_path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def validate_log_record(data: Mapping[str, Any]) -> LogRecord:
    """Check that ``data`` matches the published log-record contract.

    Extra keys are allowed. Raises :class:`ValueError` with a short reason when
    a required field is missing or has the wrong type. Does not require the
    ``jsonschema`` package.
    """
    if not isinstance(data, Mapping):
        raise ValueError(f"log record must be a mapping, got {type(data).__name__}")

    missing = sorted(REQUIRED_KEYS.difference(data))
    if missing:
        raise ValueError(f"log record missing required key(s): {missing}")

    _expect_str(data, "timestamp")
    _expect_str(data, "level")
    _expect_str(data, "logger")
    _expect_str(data, "message")
    _expect_str(data, "file")
    _expect_str(data, "func")
    if not isinstance(data["line"], int) or isinstance(data["line"], bool):
        raise ValueError("log record field 'line' must be an int")

    if "exception" in data:
        _expect_str(data, "exception")
    if "stack" in data:
        _expect_str(data, "stack")
    if "event" in data:
        if data["event"] not in ("span.start", "span.end"):
            raise ValueError("log record field 'event' must be 'span.start' or 'span.end'")
    if "status" in data:
        if data["status"] not in ("ok", "error"):
            raise ValueError("log record field 'status' must be 'ok' or 'error'")
    if "duration_ms" in data:
        value = data["duration_ms"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("log record field 'duration_ms' must be a number")
    for key in ("error_type", "error", "span", "span_id", "parent_span_id", "trace_id"):
        if key in data:
            _expect_str(data, key)

    return cast(LogRecord, dict(data))


def _expect_str(data: Mapping[str, Any], key: str) -> None:
    if not isinstance(data[key], str):
        raise ValueError(f"log record field {key!r} must be a str")
