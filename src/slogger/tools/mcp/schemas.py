"""Input contracts for the stdio tools."""

from __future__ import annotations

from typing import Any

_STRING = {"type": "string"}
_BOOL = {"type": "boolean"}
_COUNT = {"type": "integer", "minimum": 0}
_SOURCES = {"anyOf": [_STRING, {"type": "array", "items": _STRING, "minItems": 1}]}
_FILTERS = {
    "type": "object",
    "properties": {
        **{key: {"type": ["string", "null"]} for key in
           ("logger", "grep", "since", "until", "span", "trace")},
        **{key: {"type": ["integer", "null"]} for key in ("level_min", "level_exact")},
        **{key: {"type": "array", "items": _STRING} for key in ("has", "missing")},
        "exclude_events": _BOOL,
        "where": {
            "type": "array",
            "items": {
                "type": "object", "required": ["key", "op", "value"],
                "properties": {
                    "key": _STRING, "value": _STRING,
                    "op": {"enum": ["=", "!=", ">", "<", ">=", "<=", "~", "!~"]},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}
_PAGE = {
    "after": _STRING, "limit": _COUNT,
    "fields": {"type": "array", "items": _STRING}, "truncate": _COUNT,
}
_GROUP = {"group_by": _STRING, "top": _COUNT}
_SPECIFIC: dict[str, dict[str, Any]] = {
    "meta": {},
    "fields": {"scan": _COUNT, "key": _STRING, "top": _COUNT,
               "cache": _BOOL, "cache_dir": _STRING},
    "query": {**_PAGE, "last": _COUNT},
    "tail_once": _PAGE,
    "summary": {**_GROUP, "after": _STRING},
    "trace": {
        "trace_id": _STRING,
        "group_by": {"anyOf": [
            {"type": "array", "items": _STRING, "minItems": 2, "maxItems": 2},
            {"type": "object", "required": ["key", "value"],
             "properties": {"key": _STRING, "value": _STRING}, "additionalProperties": False},
        ]},
    },
    "tree": {**_GROUP, "status": {"enum": ["ok", "error", "unknown"]},
             "slower_than_ms": {"type": "number", "minimum": 0}, "span": _STRING,
             "sort": {"enum": ["started", "duration"]}},
    "stats": {**_GROUP, "spans": _BOOL,
              "bucket": {"anyOf": [_STRING, {"type": "integer", "minimum": 1}]}},
    "failures": {"top": _COUNT, "samples": _COUNT, "show_trace": _BOOL},
    "validate": {"max_diagnostics": _COUNT},
    "context": {"record_id": _STRING, "before": _COUNT, "after": _COUNT,
                "no_same_trace": _BOOL, "max_trace": _COUNT},
    "diff": {**_GROUP, "spans": _BOOL, "before": _SOURCES, "after": _SOURCES},
    "watch": {"path": _STRING, "timeout": {"type": "number", "exclusiveMinimum": 0},
              "interval": {"type": "number", "exclusiveMinimum": 0}, "existing": _BOOL},
    "explain": {},
}


def input_schema(name: str) -> dict[str, Any]:
    properties = dict(_SPECIFIC[name])
    required = []
    if name not in ("diff", "watch", "explain"):
        properties["sources"] = _SOURCES
        required.append("sources")
    if name != "validate":
        properties["filters"] = _FILTERS
    if name not in ("watch", "explain", "validate"):
        properties["order"] = {"enum": ["concat", "time"]}
    if name == "context":
        required.append("record_id")
    elif name == "diff":
        required.extend(("before", "after"))
    elif name == "watch":
        required.append("path")
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}
