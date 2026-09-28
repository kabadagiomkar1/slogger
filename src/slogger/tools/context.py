"""Fetch a record and its neighbours / same-trace context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.query import Page
from slogger.tools.reader import Order, Reader, Source, parse_id, resolve_sources


def context(
    sources: Source | Sequence[Source],
    *,
    record_id: str,
    before: int = 10,
    after: int = 10,
    same_trace: bool = True,
    filters: Filters | None = None,
    max_trace: int = 1_000,
    order: Order = "concat",
) -> Page:
    """Return a record and its neighbours / same-trace window.

    ``record_id`` is ``path:line``. CLI uses ``-B``/``-A`` for neighbour counts
    (not ``--after``, which remains the shared cursor flag elsewhere).
    """
    parse_id(record_id)  # ValueError → CLI 64
    predicate = filters if filters is not None else Filters()
    resolved = resolve_sources(sources)

    all_rows: list[dict[str, Any]] = []
    reader = Reader(resolved, order=order)
    for record in reader:
        all_rows.append(dict(record))

    anchor_index = next(
        (i for i, row in enumerate(all_rows) if row["_id"] == record_id), None
    )
    if anchor_index is None:
        raise ToolError("record_not_found", f"no record with id {record_id!r}")

    anchor = dict(all_rows[anchor_index])
    anchor["_anchor"] = True
    target_trace = (
        anchor["trace_id"] if isinstance(anchor.get("trace_id"), str) else None
    )

    before_rows: list[dict[str, Any]] = []
    for row in reversed(all_rows[:anchor_index]):
        if predicate.matches(row):
            before_rows.append(dict(row))
            if len(before_rows) >= before:
                break
    before_rows.reverse()

    after_rows: list[dict[str, Any]] = []
    for row in all_rows[anchor_index + 1 :]:
        if predicate.matches(row):
            after_rows.append(dict(row))
            if len(after_rows) >= after:
                break

    trace_rows: list[dict[str, Any]] = []
    trace_capped = False
    if same_trace and target_trace is not None:
        for row in all_rows:
            if row.get("trace_id") != target_trace:
                continue
            if len(trace_rows) >= max_trace:
                trace_capped = True
                break
            copied = dict(row)
            if copied["_id"] == record_id:
                copied["_anchor"] = True
            trace_rows.append(copied)

    combined: dict[str, dict[str, Any]] = {}
    for row in before_rows:
        combined[row["_id"]] = row
    combined[record_id] = anchor
    for row in after_rows:
        combined[row["_id"]] = row
    for row in trace_rows:
        rid = row["_id"]
        if rid == record_id:
            combined[rid] = anchor
        else:
            combined.setdefault(rid, row)

    order_index = {row["_id"]: i for i, row in enumerate(all_rows)}
    records = sorted(combined.values(), key=lambda row: order_index[row["_id"]])

    return Page(
        records=records,
        next_cursor=None,
        skipped_lines=reader.skipped_lines,
        warnings=list(reader.warnings),
        context_meta={
            "anchor": record_id,
            "trace_id": target_trace,
            "before": before,
            "after": after,
            "trace_records": len(trace_rows),
            "trace_capped": trace_capped,
        },
    )
