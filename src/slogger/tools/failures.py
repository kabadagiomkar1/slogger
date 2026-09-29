"""Group error records and failed spans (CLI command: ``errors``)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from slogger.tools.filters import Filters, level_number
from slogger.tools.reader import Order, Reader, Source, parse_timestamp
from slogger.tools.spans import SpanCollector
from slogger.tools.tree import _walk

_FILE_LINE = re.compile(r'File "([^"]+)", line (\d+)')


def _error_type_from_record(record: Mapping[str, Any]) -> str:
    et = record.get("error_type")
    if isinstance(et, str) and et:
        return et
    exc = record.get("exception")
    if isinstance(exc, str) and exc.strip():
        last = [line for line in exc.splitlines() if line.strip()][-1]
        if ":" in last:
            return last.split(":", 1)[0].strip()
        return last.strip()
    return "unknown"


def _frame_from_record(record: Mapping[str, Any]) -> str:
    exc = record.get("exception")
    if isinstance(exc, str):
        matches = list(_FILE_LINE.finditer(exc))
        if matches:
            path, line = matches[-1].group(1), matches[-1].group(2)
            return f"{os.path.basename(path)}:{line}"
    file_name = record.get("file")
    line = record.get("line")
    if isinstance(file_name, str) and isinstance(line, int) and not isinstance(line, bool):
        return f"{file_name}:{line}"
    return "?"


def _is_error_record(record: Mapping[str, Any]) -> bool:
    if record.get("event") == "span.end":
        return False
    level = record.get("level")
    try:
        if isinstance(level, str) and level_number(level) >= 40:
            return True
    except ValueError:
        pass
    return "exception" in record


@dataclass
class _Group:
    kind: str
    error_type: str
    frame: str
    count: int = 0
    traces: set[str] = field(default_factory=set)
    traces_capped: bool = False
    first_seen: str | None = None
    last_seen: str | None = None
    first_moment: Any = None
    last_moment: Any = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)

    def add_record(self, record: Mapping[str, Any], *, samples: int, show_trace: bool) -> None:
        self.count += 1
        tid = record.get("trace_id")
        if isinstance(tid, str):
            if tid not in self.traces:
                if len(self.traces) < 10_000:
                    self.traces.add(tid)
                    if show_trace and len(self.trace_ids) < samples:
                        self.trace_ids.append(tid)
                else:
                    self.traces_capped = True
        moment = parse_timestamp(record.get("timestamp"))
        ts = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        if moment is not None and ts is not None:
            if self.first_moment is None or moment < self.first_moment:
                self.first_moment = moment
                self.first_seen = ts
            if self.last_moment is None or moment > self.last_moment:
                self.last_moment = moment
                self.last_seen = ts
        if len(self.samples) < samples:
            message = record.get("message")
            if isinstance(message, str) and len(message) > 200:
                message = message[:200]
            self.samples.append(
                {
                    "_id": record.get("_id"),
                    "timestamp": record.get("timestamp"),
                    "logger": record.get("logger"),
                    "message": message,
                }
            )


def failures(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    top: int = 20,
    samples: int = 3,
    show_trace: bool = False,
    max_groups: int = 1_000,
    order: Order = "concat",
) -> dict[str, Any]:
    """Group error records and failed spans by ``error_type`` and top frame.

    CLI command: ``python3 -m slogger errors``.
    """
    predicate = filters if filters is not None else Filters()
    select = replace(predicate, span=None)
    reader = Reader(sources, order=order)
    collector = SpanCollector(keep_logs=False, predicate=select.matches)
    span_ends: dict[tuple[str, str], dict[str, Any]] = {}
    groups: dict[tuple[str, str, str], _Group] = {}
    groups_capped = False
    error_records = 0
    failed_spans = 0
    records_scanned = 0

    def take(kind: str, record: Mapping[str, Any], error_type: str, frame: str) -> None:
        nonlocal groups_capped
        key = (kind, error_type, frame)
        if key not in groups:
            if len(groups) >= max_groups:
                groups_capped = True
                return
            groups[key] = _Group(kind=kind, error_type=error_type, frame=frame)
        groups[key].add_record(record, samples=samples, show_trace=show_trace)

    for record in reader:
        tid = record.get("trace_id")
        if isinstance(tid, str):
            tracked = collector.add(record, tid)
            sid = record.get("span_id")
            if (
                tracked
                and record.get("event") == "span.end"
                and isinstance(sid, str)
                and record.get("status") == "error"
            ):
                span_ends[(tid, sid)] = dict(record)
        if not predicate.matches(record):
            continue
        records_scanned += 1
        if not _is_error_record(record):
            continue
        if predicate.exclude_events and record.get("event") in (
            "span.start",
            "span.end",
        ):
            continue
        error_records += 1
        take(
            "record",
            record,
            _error_type_from_record(record),
            _frame_from_record(record),
        )

    for _, tr in collector.finish():
        assert tr.trace_id is not None
        for node in _walk(tr.spans):
            if node.status != "error" or (predicate.span and node.span != predicate.span):
                continue
            failed_spans += 1
            end = span_ends.get((tr.trace_id, node.span_id), {})
            sample = {
                "_id": end.get("_id"),
                "timestamp": end.get("timestamp") or node.ended or node.started,
                "logger": end.get("logger"),
                "message": end.get("message") or node.span or "span.end",
                "trace_id": tr.trace_id,
                "error_type": node.error_type or end.get("error_type"),
                "exception": end.get("exception"),
                "file": end.get("file"),
                "line": end.get("line"),
            }
            take(
                "span",
                sample,
                _error_type_from_record(sample),
                _frame_from_record(sample),
            )

    ordered = sorted(
        groups.values(),
        key=lambda g: (
            -g.count,
            g.last_seen is None,
            tuple(-ord(c) for c in (g.last_seen or "")),
            g.kind,
            g.error_type,
            g.frame,
        ),
    )
    returned = ordered[:top]
    return {
        "schema_version": 1,
        "order": order,
        "records_scanned": records_scanned,
        "skipped_lines": reader.skipped_lines,
        "error_records": error_records,
        "failed_spans": failed_spans,
        "total_groups": len(groups),
        "returned": len(returned),
        "groups_capped": groups_capped or collector.groups_capped,
        "groups": [
            {
                "kind": g.kind,
                "error_type": g.error_type,
                "frame": g.frame,
                "count": g.count,
                "traces": len(g.traces),
                "traces_capped": g.traces_capped,
                "first_seen": g.first_seen,
                "last_seen": g.last_seen,
                "samples": g.samples,
                "trace_ids": g.trace_ids if show_trace else [],
            }
            for g in returned
        ],
        "warnings": list(reader.warnings),
    }
