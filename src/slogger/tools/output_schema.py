"""Published JSON contracts for :mod:`slogger.tools` aggregate outputs.

The schema document lives at ``slogger/schemas/tool-output.schema.json``.
:func:`validate_tool_output` checks required keys and a few known types without
depending on the ``jsonschema`` package (same spirit as
:func:`slogger.validate_log_record`).
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Literal, Mapping, cast

ToolOutputKind = Literal[
    "meta",
    "fields",
    "fields_top",
    "summary",
    "tree",
    "stats",
    "errors",
    "validate",
    "diff",
    "trace",
    "explain",
    "page_meta",
    "watch_meta",
]

_REQUIRED: dict[ToolOutputKind, frozenset[str]] = {
    "meta": frozenset(
        {
            "schema_version",
            "sources",
            "records",
            "skipped_lines",
            "first_timestamp",
            "last_timestamp",
            "levels",
            "loggers",
            "loggers_capped",
            "spans",
            "spans_capped",
            "traces",
            "traces_capped",
        }
    ),
    "fields": frozenset({"schema_version", "scanned", "scan_capped", "keys"}),
    "fields_top": frozenset({"schema_version", "key", "scanned", "top"}),
    "summary": frozenset(
        {
            "schema_version",
            "order",
            "matched",
            "skipped_lines",
            "levels",
            "loggers",
            "group_by",
            "groups",
            "groups_capped",
            "ungrouped",
            "warnings",
        }
    ),
    "tree": frozenset(
        {
            "schema_version",
            "order",
            "group_by",
            "total",
            "returned",
            "truncated",
            "groups_capped",
            "ungrouped",
            "skipped_lines",
            "traces",
            "warnings",
        }
    ),
    "stats": frozenset(
        {
            "schema_version",
            "order",
            "records",
            "skipped_lines",
            "group_by",
            "spans",
            "bucket",
            "totals",
            "groups",
            "groups_capped",
            "ungrouped",
            "warnings",
        }
    ),
    "errors": frozenset(
        {
            "schema_version",
            "order",
            "records_scanned",
            "skipped_lines",
            "error_records",
            "failed_spans",
            "total_groups",
            "returned",
            "groups_capped",
            "groups",
            "warnings",
        }
    ),
    "validate": frozenset(
        {
            "schema_version",
            "sources",
            "lines",
            "valid",
            "invalid",
            "kinds",
            "diagnostics",
            "diagnostics_capped",
        }
    ),
    "diff": frozenset(
        {
            "schema_version",
            "order",
            "group_by",
            "spans",
            "before",
            "after",
            "totals",
            "groups",
            "added",
            "removed",
            "truncated",
            "warnings",
        }
    ),
    "trace": frozenset(
        {
            "schema_version",
            "trace_id",
            "status",
            "started",
            "ended",
            "duration_ms",
            "spans",
            "warnings",
        }
    ),
    "explain": frozenset({"schema_version", "filters", "notes"}),
    "page_meta": frozenset(
        {
            "schema_version",
            "returned",
            "skipped_lines",
            "next_cursor",
            "warnings",
        }
    ),
    "watch_meta": frozenset(
        {"schema_version", "matched", "elapsed_ms", "records_seen"}
    ),
}

_BOOL_KEYS: dict[ToolOutputKind, frozenset[str]] = {
    "meta": frozenset({"loggers_capped", "spans_capped", "traces_capped"}),
    "fields": frozenset({"scan_capped"}),
    "summary": frozenset({"groups_capped"}),
    "tree": frozenset({"truncated", "groups_capped"}),
    "stats": frozenset({"spans", "groups_capped"}),
    "errors": frozenset({"groups_capped"}),
    "validate": frozenset({"diagnostics_capped"}),
    "diff": frozenset({"spans", "truncated"}),
    "watch_meta": frozenset({"matched"}),
}

_INT_KEYS: dict[ToolOutputKind, frozenset[str]] = {
    "meta": frozenset({"records", "skipped_lines", "traces"}),
    "fields": frozenset({"scanned"}),
    "fields_top": frozenset({"scanned"}),
    "summary": frozenset({"matched", "skipped_lines", "ungrouped"}),
    "tree": frozenset({"total", "returned", "ungrouped", "skipped_lines"}),
    "stats": frozenset({"records", "skipped_lines", "ungrouped"}),
    "errors": frozenset(
        {
            "records_scanned",
            "skipped_lines",
            "error_records",
            "failed_spans",
            "total_groups",
            "returned",
        }
    ),
    "validate": frozenset({"lines", "valid", "invalid"}),
    "page_meta": frozenset({"returned", "skipped_lines"}),
    "watch_meta": frozenset({"records_seen"}),
}


def output_schemas() -> dict[str, Any]:
    """Return the tool-output JSON Schema (draft 2020-12) document."""
    schema_path = resources.files("slogger").joinpath("schemas").joinpath(
        "tool-output.schema.json"
    )
    with schema_path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def validate_tool_output(kind: ToolOutputKind, data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Check that ``data`` matches the published contract for ``kind``.

    Extra keys are allowed. Raises :class:`ValueError` when required fields are
    missing or have the wrong top-level type. Does not require ``jsonschema``.
    """
    if kind not in _REQUIRED:
        raise ValueError(f"unknown tool output kind: {kind!r}")
    if not isinstance(data, Mapping):
        raise ValueError(f"tool output must be a mapping, got {type(data).__name__}")

    missing = sorted(_REQUIRED[kind].difference(data))
    if missing:
        raise ValueError(f"{kind} output missing required key(s): {missing}")

    version = data.get("schema_version")
    if version != 1:
        raise ValueError(f"{kind} schema_version must be 1, got {version!r}")

    for key in _BOOL_KEYS.get(kind, ()):
        value = data[key]
        if not isinstance(value, bool):
            raise ValueError(f"{kind} field {key!r} must be a bool")

    for key in _INT_KEYS.get(kind, ()):
        value = data[key]
        if type(value) is not int:  # bool is a subclass of int
            raise ValueError(f"{kind} field {key!r} must be an int")

    if kind == "explain":
        filters = data["filters"]
        if not isinstance(filters, Mapping):
            raise ValueError("explain filters must be a mapping")
        notes = data["notes"]
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            raise ValueError("explain notes must be a list of strings")

    if kind == "page_meta":
        cursor = data["next_cursor"]
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("page_meta next_cursor must be a str or null")
        warnings = data["warnings"]
        if not isinstance(warnings, list) or not all(
            isinstance(item, str) for item in warnings
        ):
            raise ValueError("page_meta warnings must be a list of strings")

    if kind == "watch_meta":
        elapsed = data["elapsed_ms"]
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool):
            raise ValueError("watch_meta elapsed_ms must be a number")

    return data


__all__ = [
    "ToolOutputKind",
    "output_schemas",
    "validate_tool_output",
]
