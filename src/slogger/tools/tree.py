"""Summarise reconstructed traces as a flat tree listing."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal

from slogger.tools.filters import Filters
from slogger.tools.grouping import group_value
from slogger.tools.reader import Order, Reader, Source, parse_timestamp
from slogger.tools.spans import SpanCollector
from slogger.tools.trace import SpanNode, Trace


def _walk(nodes: Sequence[SpanNode]) -> list[SpanNode]:
    out: list[SpanNode] = []
    for node in nodes:
        out.append(node)
        out.extend(_walk(node.children))
    return out


def _stable_group_key(type_name: str, norm: object) -> str:
    return json.dumps([type_name, norm], sort_keys=True, separators=(",", ":"), default=str)


def _row_from_trace(
    tr: Trace,
    *,
    group: dict[str, object] | None,
    index: int,
) -> dict[str, Any]:
    nodes = _walk(tr.spans)
    completed = sum(1 for n in nodes if n.started is not None and n.ended is not None)
    failed = sum(1 for n in nodes if n.status == "error")
    unfinished = sum(1 for n in nodes if n.started is not None and n.ended is None)
    missing_start = sum(1 for n in nodes if n.missing_start)
    root_span = tr.spans[0].span if tr.spans else None
    return {
        "trace_id": None if group is not None else tr.trace_id,
        "group": group,
        "root_span": root_span,
        "roots": len(tr.spans),
        "spans": len(nodes),
        "completed": completed,
        "failed": failed,
        "unfinished": unfinished,
        "missing_start": missing_start,
        "status": tr.status,
        "started": tr.started,
        "ended": tr.ended,
        "duration_ms": tr.duration_ms,
        "warnings": len(tr.warnings),
        "_order": index,
    }


def _has_span_named(tr: Trace, name: str) -> bool:
    return any(node.span == name for node in _walk(tr.spans))


def _anchor_in_window(tr: Trace, filters: Filters) -> bool:
    if filters.since is None and filters.until is None:
        return True
    anchor = tr.started or tr.ended
    moment = parse_timestamp(anchor)
    if moment is None:
        return False
    if filters.since is not None and moment < filters.since:
        return False
    if filters.until is not None and moment > filters.until:
        return False
    return True


def tree(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    group_by: str | None = None,
    status: Literal["ok", "error", "unknown"] | None = None,
    slower_than_ms: float | None = None,
    span: str | None = None,
    sort: Literal["started", "duration"] = "started",
    top: int = 50,
    max_groups: int = 10_000,
    order: Order = "concat",
) -> dict[str, Any]:
    """List reconstructed traces as one summary row each.

    ``group_by`` correlates on a flat key instead of ``trace_id``. Unfinished
    spans appear with ``status="unknown"`` and ``duration_ms=null``.

    Example::

        from slogger.tools import tree

        rows = tree("app.log", status="error", slower_than_ms=500)
    """
    if sort not in ("started", "duration"):
        raise ValueError(f"invalid sort: {sort!r}")

    predicate = filters if filters is not None else Filters()
    # --span on tree is an aggregate filter, not a record selector.
    select_filters = replace(predicate, span=None)
    collector = SpanCollector(keep_logs=False, max_groups=max_groups)
    reader = Reader(sources, order=order)
    ungrouped = 0
    group_meta: dict[str, dict[str, object]] = {}

    for record in reader:
        if group_by is None:
            tid = record.get("trace_id")
            if not isinstance(tid, str):
                ungrouped += 1
                continue
            collector.add(record, tid)
        else:
            gv = group_value(record, group_by)
            if gv is None:
                ungrouped += 1
                continue
            type_name, norm = gv
            key = _stable_group_key(type_name, norm)
            group_meta[key] = {
                "key": group_by,
                "value": norm,
                "type": type_name,
            }
            collector.add(record, key)

    rows: list[dict[str, Any]] = []
    for index, (group_key, tr) in enumerate(
        collector.finish(predicate=select_filters.matches)
    ):
        if not tr.spans:
            continue
        if not _anchor_in_window(tr, select_filters):
            continue
        group = None
        if group_by is not None:
            meta = group_meta[group_key]
            group = {"key": meta["key"], "value": meta["value"]}
        row = _row_from_trace(tr, group=group, index=index)
        if status is not None and row["status"] != status:
            continue
        if slower_than_ms is not None:
            duration = row["duration_ms"]
            if duration is None or not (duration > slower_than_ms):
                continue
        if span is not None and not _has_span_named(tr, span):
            continue
        rows.append(row)

    total = len(rows)
    if sort == "started":
        rows.sort(key=lambda r: (r["started"] if r["started"] is not None else "~", r["_order"]))
    else:
        rows.sort(
            key=lambda r: (
                r["duration_ms"] is None,
                -(r["duration_ms"] or 0.0),
                r["started"] if r["started"] is not None else "~",
                r["_order"],
            )
        )

    returned_rows = rows[:top] if top >= 0 else rows
    for row in returned_rows:
        row.pop("_order", None)

    truncated = total > len(returned_rows) or collector.groups_capped
    return {
        "schema_version": 1,
        "order": order,
        "group_by": group_by,
        "total": total,
        "returned": len(returned_rows),
        "truncated": truncated,
        "groups_capped": collector.groups_capped,
        "ungrouped": ungrouped,
        "skipped_lines": reader.skipped_lines,
        "traces": returned_rows,
        "warnings": list(reader.warnings),
    }
