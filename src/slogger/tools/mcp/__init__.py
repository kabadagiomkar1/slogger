"""Minimal stdio MCP server over :mod:`slogger.tools`.

Run with::

    python3 -m slogger.tools.mcp

Speaks JSON-RPC 2.0 with MCP-style ``Content-Length`` framing (also accepts
one JSON object per line for tests). No third-party MCP SDK required.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from slogger.tools.context import context
from slogger.tools.diff import diff
from slogger.tools.failures import failures
from slogger.tools.fields import fields
from slogger.tools.filters import Filters
from slogger.tools.meta import meta
from slogger.tools.query import query, summary
from slogger.tools.stats import stats
from slogger.tools.tail import tail_once
from slogger.tools.trace import trace
from slogger.tools.tree import tree
from slogger.tools.validate import validate
from slogger.tools.watch import watch

SERVER_NAME = "slogger.tools"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"


def _filters_arg(arguments: Mapping[str, Any]) -> Filters:
    raw = arguments.get("filters")
    if raw is None:
        return Filters()
    if not isinstance(raw, Mapping):
        raise ValueError("filters must be an object")
    return Filters.from_mapping(raw)


def _sources_arg(arguments: Mapping[str, Any], *, key: str = "sources") -> Any:
    if key not in arguments:
        raise ValueError(f"missing required argument: {key}")
    return arguments[key]


def _tool_meta(arguments: Mapping[str, Any]) -> Any:
    return meta(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        order=arguments.get("order", "concat"),
    )


def _tool_fields(arguments: Mapping[str, Any]) -> Any:
    return fields(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        scan=int(arguments.get("scan", 100_000)),
        key=arguments.get("key"),
        top=int(arguments.get("top", 10)),
        order=arguments.get("order", "concat"),
        cache=bool(arguments.get("cache", False)),
        cache_dir=arguments.get("cache_dir"),
    )


def _tool_query(arguments: Mapping[str, Any]) -> Any:
    page = query(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        limit=arguments.get("limit"),
        after=arguments.get("after"),
        last=arguments.get("last"),
        fields=arguments.get("fields"),
        truncate=arguments.get("truncate"),
        order=arguments.get("order", "concat"),
    )
    return {
        "records": page.records,
        "next_cursor": page.next_cursor,
        "skipped_lines": page.skipped_lines,
        "warnings": page.warnings,
    }


def _tool_summary(arguments: Mapping[str, Any]) -> Any:
    return summary(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        after=arguments.get("after"),
        group_by=arguments.get("group_by"),
        top=int(arguments.get("top", 50)),
        order=arguments.get("order", "concat"),
    )


def _tool_trace(arguments: Mapping[str, Any]) -> Any:
    group_by = arguments.get("group_by")
    if isinstance(group_by, list) and len(group_by) == 2:
        group_by = (str(group_by[0]), str(group_by[1]))
    elif isinstance(group_by, Mapping):
        group_by = (str(group_by["key"]), str(group_by["value"]))
    result = trace(
        _sources_arg(arguments),
        trace_id=arguments.get("trace_id"),
        filters=_filters_arg(arguments) if arguments.get("filters") else None,
        order=arguments.get("order", "concat"),
        group_by=group_by,
    )
    return result.to_dict()


def _tool_tree(arguments: Mapping[str, Any]) -> Any:
    return tree(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        group_by=arguments.get("group_by"),
        status=arguments.get("status"),
        slower_than_ms=arguments.get("slower_than_ms"),
        span=arguments.get("span"),
        sort=arguments.get("sort", "started"),
        top=int(arguments.get("top", 50)),
        order=arguments.get("order", "concat"),
    )


def _tool_stats(arguments: Mapping[str, Any]) -> Any:
    return stats(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        group_by=arguments.get("group_by"),
        spans=bool(arguments.get("spans", False)),
        bucket=arguments.get("bucket"),
        top=int(arguments.get("top", 50)),
        order=arguments.get("order", "concat"),
    )


def _tool_failures(arguments: Mapping[str, Any]) -> Any:
    return failures(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        top=int(arguments.get("top", 20)),
        samples=int(arguments.get("samples", 3)),
        show_trace=bool(arguments.get("show_trace", False)),
        order=arguments.get("order", "concat"),
    )


def _tool_validate(arguments: Mapping[str, Any]) -> Any:
    return validate(
        _sources_arg(arguments),
        max_diagnostics=int(arguments.get("max_diagnostics", 100)),
    )


def _tool_context(arguments: Mapping[str, Any]) -> Any:
    page = context(
        _sources_arg(arguments),
        record_id=str(arguments["record_id"]),
        before=int(arguments.get("before", 10)),
        after=int(arguments.get("after", 10)),
        same_trace=not bool(arguments.get("no_same_trace", False)),
        filters=_filters_arg(arguments),
        max_trace=int(arguments.get("max_trace", 1_000)),
        order=arguments.get("order", "concat"),
    )
    return {
        "records": page.records,
        "next_cursor": page.next_cursor,
        "skipped_lines": page.skipped_lines,
        "warnings": page.warnings,
        "context_meta": page.context_meta,
    }


def _tool_diff(arguments: Mapping[str, Any]) -> Any:
    return diff(
        _sources_arg(arguments, key="before"),
        _sources_arg(arguments, key="after"),
        filters=_filters_arg(arguments),
        group_by=arguments.get("group_by"),
        spans=bool(arguments.get("spans", False)),
        top=int(arguments.get("top", 50)),
        order=arguments.get("order", "concat"),
    )


def _tool_watch(arguments: Mapping[str, Any]) -> Any:
    result = watch(
        str(arguments["path"]),
        filters=_filters_arg(arguments),
        timeout=float(arguments.get("timeout", 30.0)),
        existing=bool(arguments.get("existing", False)),
        interval=float(arguments.get("interval", 0.25)),
    )
    return {
        "matched": result.matched,
        "timed_out": result.timed_out,
        "elapsed_ms": result.elapsed_ms,
        "records_seen": result.records_seen,
    }


def _tool_tail_once(arguments: Mapping[str, Any]) -> Any:
    page = tail_once(
        _sources_arg(arguments),
        filters=_filters_arg(arguments),
        after=arguments.get("after"),
        limit=arguments.get("limit"),
        fields=arguments.get("fields"),
        truncate=arguments.get("truncate"),
        order=arguments.get("order", "concat"),
    )
    return {
        "records": page.records,
        "next_cursor": page.next_cursor,
        "skipped_lines": page.skipped_lines,
        "warnings": page.warnings,
    }


def _tool_explain(arguments: Mapping[str, Any]) -> Any:
    return _filters_arg(arguments).explain()


_TOOL_HANDLERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "meta": _tool_meta,
    "fields": _tool_fields,
    "query": _tool_query,
    "summary": _tool_summary,
    "trace": _tool_trace,
    "tree": _tool_tree,
    "stats": _tool_stats,
    "failures": _tool_failures,
    "validate": _tool_validate,
    "context": _tool_context,
    "diff": _tool_diff,
    "watch": _tool_watch,
    "tail_once": _tool_tail_once,
    "explain": _tool_explain,
}

_FILTERS_SCHEMA = {
    "type": "object",
    "description": "Same shape as Filters.explain()['filters'].",
    "additionalProperties": True,
}


def list_tools() -> list[dict[str, Any]]:
    """Return MCP ``tools/list`` tool descriptors."""
    source = {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ]
    }
    return [
        {
            "name": name,
            "description": f"slogger.tools.{name}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sources": source,
                    "filters": _FILTERS_SCHEMA,
                    "order": {"type": "string", "enum": ["concat", "time"]},
                },
                "additionalProperties": True,
            },
        }
        for name in sorted(_TOOL_HANDLERS)
    ]


def call_tool(name: str, arguments: Mapping[str, Any] | None = None) -> Any:
    """Dispatch one tool call and return a JSON-serialisable result."""
    if name not in _TOOL_HANDLERS:
        raise ValueError(f"unknown tool: {name!r}")
    return _TOOL_HANDLERS[name](arguments or {})


def _json_result(result: Any) -> dict[str, Any]:
    text = json.dumps(result, default=str)
    return {"content": [{"type": "text", "text": text}], "structuredContent": result}


def handle_request(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request; return a response or ``None`` for notifications."""
    method = message.get("method")
    req_id = message.get("id", None)
    params = message.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": list_tools()},
        }
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if not isinstance(name, str):
                raise ValueError("tool name must be a string")
            if not isinstance(arguments, Mapping):
                raise ValueError("arguments must be an object")
            result = call_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _json_result(result),
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }
    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method!r}"},
    }


def _read_message(stdin: TextIO) -> dict[str, Any] | None:
    """Read one MCP message (Content-Length framed or a single JSON line)."""
    # Peek-style: if the first line looks like Content-Length, use framing.
    line = stdin.readline()
    if line == "":
        return None
    if line.lower().startswith("content-length:"):
        length = int(line.split(":", 1)[1].strip())
        # Consume headers until blank line.
        while True:
            header = stdin.readline()
            if header in ("", "\n", "\r\n"):
                break
        body = stdin.read(length)
        return json.loads(body)
    # Newline-delimited JSON (tests / simple clients).
    return json.loads(line)


def _write_message(message: Mapping[str, Any], stdout: TextIO) -> None:
    body = json.dumps(message, default=str)
    stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    stdout.flush()


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Serve MCP requests until stdin closes."""
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    while True:
        try:
            message = _read_message(in_stream)
        except json.JSONDecodeError as exc:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"parse error: {exc}"},
                },
                out_stream,
            )
            continue
        if message is None:
            return 0
        response = handle_request(message)
        if response is not None:
            _write_message(response, out_stream)


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
