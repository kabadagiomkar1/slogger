"""Fetch a record and its neighbours / same-trace context."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.query import Page
from slogger.tools.reader import Order, Reader, Source, parse_id, replay_sources


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

    Memory is bounded: a ``deque`` of filter-matching neighbours before the
    anchor, at most ``after`` neighbours after it, and (when enabled) at most
    ``max_trace`` same-trace records from a second pass.
    """
    parse_id(record_id)  # ValueError → CLI 64
    if before < 0 or after < 0:
        raise ValueError("before and after must be >= 0")
    if max_trace < 0:
        raise ValueError("max_trace must be >= 0")
    predicate = filters if filters is not None else Filters()
    with replay_sources(sources) as resolved:

        before_window: deque[tuple[int, dict[str, Any]]] = deque(
            maxlen=before if before > 0 else 0
        )
        after_rows: list[tuple[int, dict[str, Any]]] = []
        anchor: dict[str, Any] | None = None
        order_index: dict[str, int] = {}

        reader = Reader(resolved, order=order)
        for index, record in enumerate(reader):
            row = dict(record)
            rid = row["_id"]
            if anchor is None:
                if rid == record_id:
                    anchor = row
                    anchor["_anchor"] = True
                    order_index[rid] = index
                elif before > 0 and predicate.matches(row):
                    before_window.append((index, row))
                continue

            if len(after_rows) < after and predicate.matches(row):
                after_rows.append((index, row))
                order_index[rid] = index
            if len(after_rows) >= after:
                break

        if anchor is None:
            raise ToolError("record_not_found", f"no record with id {record_id!r}")

        for index, row in before_window:
            order_index[row["_id"]] = index

        target_trace = (
            anchor["trace_id"] if isinstance(anchor.get("trace_id"), str) else None
        )

        trace_rows: list[dict[str, Any]] = []
        trace_capped = False
        if same_trace and target_trace is not None and max_trace > 0:
            for index, record in enumerate(Reader(resolved, order=order)):
                if record.get("trace_id") != target_trace:
                    continue
                if len(trace_rows) >= max_trace:
                    trace_capped = True
                    break
                copied = dict(record)
                if copied["_id"] == record_id:
                    copied["_anchor"] = True
                order_index[copied["_id"]] = index
                trace_rows.append(copied)

        combined: dict[str, dict[str, Any]] = {}
        for _, row in before_window:
            combined[row["_id"]] = dict(row)
        combined[record_id] = anchor
        for _, row in after_rows:
            combined[row["_id"]] = dict(row)
        for row in trace_rows:
            rid = row["_id"]
            if rid == record_id:
                combined[rid] = anchor
            else:
                combined.setdefault(rid, row)

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
