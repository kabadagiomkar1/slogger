"""Minimal stdio MCP server over :mod:`slogger.tools`.

Run with::

    python3 -m slogger.tools.mcp

Speaks newline-delimited JSON-RPC 2.0 over stdio. No third-party MCP SDK required.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import Any, TextIO

from slogger.tools._schema import validate_schema
from slogger.tools.context import context
from slogger.tools.diff import diff
from slogger.tools.failures import failures
from slogger.tools.fields import fields
from slogger.tools.filters import Filters
from slogger.tools.mcp.schemas import input_schema
from slogger.tools.meta import meta
from slogger.tools.query import Page, query, summary
from slogger.tools.stats import stats
from slogger.tools.tail import tail_once
from slogger.tools.trace import trace
from slogger.tools.tree import tree
from slogger.tools.validate import validate
from slogger.tools.watch import watch

SERVER_NAME = "slogger.tools"
try:
    SERVER_VERSION = version("slogger")
except PackageNotFoundError:  # pragma: no cover - editable/dev edge
    SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "call_tool",
    "handle_request",
    "list_tools",
    "main",
    "serve",
]


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


def _page_payload(page: Page, *, include_context_meta: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "records": page.records,
        "next_cursor": page.next_cursor,
        "skipped_lines": page.skipped_lines,
        "warnings": page.warnings,
    }
    if include_context_meta:
        payload["context_meta"] = page.context_meta
    return payload


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
    return _page_payload(page)


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
        # Pass None when omitted: trace(group_by=...) rejects filters is not None.
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
    return _page_payload(page, include_context_meta=True)


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
    return _page_payload(page)


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

def list_tools() -> list[dict[str, Any]]:
    """Return MCP tool descriptors with per-tool argument contracts."""
    return [
        {"name": name, "description": f"slogger.tools.{name}",
         "inputSchema": input_schema(name)}
        for name in sorted(_TOOL_HANDLERS)
    ]


def call_tool(name: str, arguments: Mapping[str, Any] | None = None) -> Any:
    """Dispatch one tool call and return a JSON-serialisable result."""
    if name not in _TOOL_HANDLERS:
        raise ValueError(f"unknown tool: {name!r}")
    arguments = {} if arguments is None else arguments
    schema = input_schema(name)
    validate_schema(arguments, schema, root=schema, path=name)
    for key in ("sources", "path", "before", "after"):
        source = arguments.get(key)
        if source == "-" or isinstance(source, list) and "-" in source:
            raise ValueError("stdin cannot be used as a log source through MCP")
    return _TOOL_HANDLERS[name](arguments)


def _json_result(result: Any) -> dict[str, Any]:
    text = json.dumps(result, default=str)
    return {"content": [{"type": "text", "text": text}], "structuredContent": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(message: Any) -> dict[str, Any] | None:
    """Handle one request; notifications never receive a response."""
    if not isinstance(message, Mapping):
        return _rpc_error(None, -32600, "request must be an object")
    req_id = message.get("id")
    if (
        message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)
        or isinstance(req_id, bool)
        or not isinstance(req_id, (str, int, type(None)))
    ):
        return _rpc_error(None, -32600, "invalid JSON-RPC request")
    if "id" not in message:
        return None
    method = message["method"]
    params = message.get("params", {})
    if not isinstance(params, Mapping):
        return _rpc_error(req_id, -32602, "params must be an object")
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": list_tools()}
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or name not in _TOOL_HANDLERS:
            return _rpc_error(req_id, -32602, "unknown tool name")
        if not isinstance(arguments, Mapping):
            return _rpc_error(req_id, -32602, "arguments must be an object")
        try:
            result = _json_result(call_tool(name, arguments))
        except Exception as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    else:
        return _rpc_error(req_id, -32601, f"method not found: {method!r}")
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _write_message(message: Mapping[str, Any], stdout: TextIO) -> None:
    stdout.write(json.dumps(message, default=str) + "\n")
    stdout.flush()


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Serve newline-delimited MCP requests until stdin closes."""
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    for line in in_stream:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _rpc_error(None, -32700, f"parse error: {exc}")
        else:
            response = handle_request(message)
        if response is not None:
            _write_message(response, out_stream)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    return serve()
