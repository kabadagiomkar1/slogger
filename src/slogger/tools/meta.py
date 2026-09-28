"""Summarise a set of log sources."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Sequence
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import (
    Order,
    Reader,
    Source,
    parse_timestamp,
    resolve_sources,
)

_LOGGER_CAP = 1000
_SPAN_CAP = 1000
_TRACE_CAP = 10_000


def meta(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    order: Order = "concat",
) -> dict[str, Any]:
    """Summarise sources: counts, time range, loggers, spans, level histogram.

    Example::

        from slogger.tools import meta

        info = meta("app.log")
        print(info["records"], info["levels"])
    """
    _ = order  # aggregates are order-invariant; parameter kept for API parity
    predicate = filters if filters is not None else Filters()
    resolved = resolve_sources(sources)

    source_rows: list[dict[str, Any]] = []
    levels: Counter[str] = Counter()
    loggers: set[str] = set()
    spans: set[str] = set()
    traces: set[str] = set()
    loggers_capped = False
    spans_capped = False
    traces_capped = False
    first_ts: str | None = None
    last_ts: str | None = None
    first_moment = None
    last_moment = None
    total_records = 0
    total_skipped = 0

    for source in resolved:
        reader = Reader(source)
        count = 0
        for record in reader:
            if not predicate.matches(record):
                continue
            count += 1
            total_records += 1
            level = record.get("level")
            if isinstance(level, str):
                levels[level] += 1
            logger = record.get("logger")
            if isinstance(logger, str):
                if len(loggers) < _LOGGER_CAP:
                    loggers.add(logger)
                elif logger not in loggers:
                    loggers_capped = True
            span = record.get("span")
            if isinstance(span, str):
                if len(spans) < _SPAN_CAP:
                    spans.add(span)
                elif span not in spans:
                    spans_capped = True
            trace_id = record.get("trace_id")
            if isinstance(trace_id, str):
                if len(traces) < _TRACE_CAP:
                    traces.add(trace_id)
                elif trace_id not in traces:
                    traces_capped = True
            moment = parse_timestamp(record.get("timestamp"))
            if moment is not None:
                ts = record["timestamp"]
                assert isinstance(ts, str)
                if first_moment is None or moment < first_moment:
                    first_moment = moment
                    first_ts = ts
                if last_moment is None or moment > last_moment:
                    last_moment = moment
                    last_ts = ts
        total_skipped += reader.skipped_lines
        path = source if isinstance(source, str) else "mem"
        bytes_count: int | None
        if isinstance(source, str) and source != "-":
            try:
                bytes_count = os.path.getsize(source)
            except OSError:
                bytes_count = None
        else:
            bytes_count = None
        source_rows.append(
            {
                "path": path,
                "records": count,
                "skipped_lines": reader.skipped_lines,
                "bytes": bytes_count,
            }
        )

    return {
        "schema_version": 1,
        "sources": source_rows,
        "records": total_records,
        "skipped_lines": total_skipped,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "levels": dict(sorted(levels.items())),
        "loggers": sorted(loggers),
        "loggers_capped": loggers_capped,
        "spans": sorted(spans),
        "spans_capped": spans_capped,
        "traces": len(traces),
        "traces_capped": traces_capped,
    }
