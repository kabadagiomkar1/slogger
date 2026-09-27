"""Aggregate record and span statistics."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.grouping import group_value
from slogger.tools.reader import Order, Reader, Source, parse_timestamp
from slogger.tools.spans import SpanCollector
from slogger.tools.timeparse import parse_bucket, parse_duration_ms
from slogger.tools.trace import SpanNode
from slogger.tools.tree import _walk

__all__ = ["parse_bucket", "parse_duration_ms", "percentile", "stats"]


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Exact nearest-rank percentile. ``sorted_values`` must be ascending and non-empty."""
    if not sorted_values:
        raise ValueError("percentile requires a non-empty sample")
    if p <= 0 or p > 100:
        raise ValueError(f"percentile p out of range: {p!r}")
    n = len(sorted_values)
    k = max(1, math.ceil(p / 100.0 * n))
    return float(sorted_values[k - 1])


def _duration_stats(samples: list[float], *, count: int, total: float, min_v: float | None,
                    max_v: float | None, capped: bool) -> dict[str, Any]:
    if count == 0:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "percentiles_capped": False,
        }
    ordered = sorted(samples)
    return {
        "count": count,
        "min": min_v,
        "max": max_v,
        "mean": total / count,
        "p50": percentile(ordered, 50) if ordered else None,
        "p95": percentile(ordered, 95) if ordered else None,
        "p99": percentile(ordered, 99) if ordered else None,
        "percentiles_capped": capped,
    }


@dataclass
class _DurationAcc:
    samples: list[float] = field(default_factory=list)
    count: int = 0
    total: float = 0.0
    min_v: float | None = None
    max_v: float | None = None
    capped: bool = False
    max_samples: int = 100_000

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.min_v = value if self.min_v is None else min(self.min_v, value)
        self.max_v = value if self.max_v is None else max(self.max_v, value)
        if len(self.samples) < self.max_samples:
            self.samples.append(value)
        else:
            self.capped = True

    def to_dict(self) -> dict[str, Any]:
        return _duration_stats(
            self.samples,
            count=self.count,
            total=self.total,
            min_v=self.min_v,
            max_v=self.max_v,
            capped=self.capped,
        )


@dataclass
class _BucketAcc:
    records: int = 0
    spans: int = 0
    completed: int = 0
    failed: int = 0
    unfinished: int = 0
    missing_start: int = 0
    invalid_durations: int = 0
    duration: _DurationAcc = field(default_factory=_DurationAcc)

    def to_dict(self, *, spans: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"records": self.records}
        if spans:
            out.update(
                {
                    "spans": self.spans,
                    "completed": self.completed,
                    "failed": self.failed,
                    "unfinished": self.unfinished,
                    "missing_start": self.missing_start,
                    "invalid_durations": self.invalid_durations,
                    "duration_ms": self.duration.to_dict(),
                }
            )
        return out


@dataclass
class _GroupAcc:
    value: object
    type_name: str
    records: int = 0
    levels: Counter[str] = field(default_factory=Counter)
    spans: int = 0
    completed: int = 0
    failed: int = 0
    unfinished: int = 0
    missing_start: int = 0
    invalid_durations: int = 0
    duration: _DurationAcc = field(default_factory=_DurationAcc)
    buckets: dict[str | None, _BucketAcc] = field(default_factory=dict)

    def to_dict(self, *, spans: bool, with_buckets: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value,
            "type": self.type_name,
            "records": self.records,
        }
        if not spans:
            out["levels"] = dict(sorted(self.levels.items()))
        if spans:
            out.update(
                {
                    "spans": self.spans,
                    "completed": self.completed,
                    "failed": self.failed,
                    "unfinished": self.unfinished,
                    "missing_start": self.missing_start,
                    "invalid_durations": self.invalid_durations,
                    "duration_ms": self.duration.to_dict(),
                }
            )
        if with_buckets:
            out["buckets"] = _format_buckets(self.buckets, spans=spans)
        return out


def _bucket_start(moment: datetime | None, size: int) -> str | None:
    if moment is None:
        return None
    epoch = int(moment.timestamp())
    floored = (epoch // size) * size
    return datetime.fromtimestamp(floored, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _format_buckets(
    buckets: Mapping[str | None, _BucketAcc], *, spans: bool
) -> list[dict[str, Any]]:
    def sort_key(item: tuple[str | None, _BucketAcc]) -> tuple[int, str]:
        start, _ = item
        if start is None:
            return (1, "")
        return (0, start)

    rows = []
    for start, acc in sorted(buckets.items(), key=sort_key):
        row = {"start": start, **acc.to_dict(spans=spans)}
        rows.append(row)
    return rows


def _is_valid_duration(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value >= 0 and math.isfinite(float(value))


def _add_node_stats(
    node: SpanNode,
    *,
    duration_acc: _DurationAcc,
    counters: Any,
) -> None:
    counters.spans += 1
    if node.started is not None and node.ended is not None:
        counters.completed += 1
    if node.status == "error":
        counters.failed += 1
    if node.started is not None and node.ended is None:
        counters.unfinished += 1
    if node.missing_start:
        counters.missing_start += 1
    if node.ended is not None:
        if _is_valid_duration(node.duration_ms):
            duration_acc.add(float(node.duration_ms))  # type: ignore[arg-type]
        else:
            counters.invalid_durations += 1


def _node_anchor(node: SpanNode) -> datetime | None:
    return parse_timestamp(node.started or node.ended)


def stats(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    group_by: str | None = None,
    spans: bool = False,
    bucket: str | int | None = None,
    top: int = 50,
    max_groups: int = 10_000,
    max_buckets: int = 10_000,
    max_samples: int = 100_000,
    order: Order = "concat",
) -> dict[str, Any]:
    predicate = filters if filters is not None else Filters()
    bucket_size: int | None
    if bucket is None:
        bucket_size = None
        bucket_label = None
    elif isinstance(bucket, int):
        bucket_size = bucket
        bucket_label = f"{bucket}s"
    else:
        bucket_size = parse_bucket(bucket)
        bucket_label = bucket

    if spans:
        return _stats_spans(
            sources,
            filters=predicate,
            group_by=group_by,
            bucket_size=bucket_size,
            bucket_label=bucket_label,
            top=top,
            max_groups=max_groups,
            max_buckets=max_buckets,
            max_samples=max_samples,
            order=order,
        )
    return _stats_records(
        sources,
        filters=predicate,
        group_by=group_by,
        bucket_size=bucket_size,
        bucket_label=bucket_label,
        top=top,
        max_groups=max_groups,
        max_buckets=max_buckets,
        order=order,
    )


def _stats_records(
    sources: Source | Sequence[Source],
    *,
    filters: Filters,
    group_by: str | None,
    bucket_size: int | None,
    bucket_label: str | None,
    top: int,
    max_groups: int,
    max_buckets: int,
    order: Order,
) -> dict[str, Any]:
    reader = Reader(sources, order=order)
    levels: Counter[str] = Counter()
    records = 0
    ungrouped = 0
    groups_capped = False
    groups: dict[str, _GroupAcc] = {}
    totals_buckets: dict[str | None, _BucketAcc] = {}

    for record in reader:
        if not filters.matches(record):
            continue
        records += 1
        level = record.get("level")
        if isinstance(level, str):
            levels[level] += 1
        if bucket_size is not None:
            start = _bucket_start(parse_timestamp(record.get("timestamp")), bucket_size)
            if start not in totals_buckets and len(totals_buckets) >= max_buckets:
                pass
            else:
                totals_buckets.setdefault(start, _BucketAcc()).records += 1
        if group_by is None:
            continue
        gv = group_value(record, group_by)
        if gv is None:
            ungrouped += 1
            continue
        type_name, norm = gv
        key = json.dumps([type_name, norm], sort_keys=True, separators=(",", ":"), default=str)
        if key not in groups:
            if len(groups) >= max_groups:
                groups_capped = True
                ungrouped += 1
                continue
            display = norm
            groups[key] = _GroupAcc(value=display, type_name=type_name)
        acc = groups[key]
        acc.records += 1
        if isinstance(level, str):
            acc.levels[level] += 1
        if bucket_size is not None:
            start = _bucket_start(parse_timestamp(record.get("timestamp")), bucket_size)
            if start not in acc.buckets and len(acc.buckets) >= max_buckets:
                continue
            acc.buckets.setdefault(start, _BucketAcc()).records += 1

    group_rows = sorted(
        groups.values(),
        key=lambda g: (-g.records, g.type_name, json.dumps(g.value, sort_keys=True, default=str)),
    )[:top]
    totals: dict[str, Any] = {
        "records": records,
        "levels": dict(sorted(levels.items())),
    }
    if bucket_size is not None:
        totals["buckets"] = _format_buckets(totals_buckets, spans=False)
    return {
        "schema_version": 1,
        "order": order,
        "records": records,
        "skipped_lines": reader.skipped_lines,
        "group_by": group_by,
        "spans": False,
        "bucket": bucket_label,
        "totals": totals,
        "groups": [
            g.to_dict(spans=False, with_buckets=bucket_size is not None) for g in group_rows
        ],
        "groups_capped": groups_capped,
        "ungrouped": ungrouped,
        "warnings": list(reader.warnings),
    }


@dataclass
class _SpanTotals:
    spans: int = 0
    completed: int = 0
    failed: int = 0
    unfinished: int = 0
    missing_start: int = 0
    invalid_durations: int = 0


def _stats_spans(
    sources: Source | Sequence[Source],
    *,
    filters: Filters,
    group_by: str | None,
    bucket_size: int | None,
    bucket_label: str | None,
    top: int,
    max_groups: int,
    max_buckets: int,
    max_samples: int,
    order: Order,
) -> dict[str, Any]:
    select = replace(filters, span=None)
    collector = SpanCollector(keep_logs=False, max_groups=max_groups)
    reader = Reader(sources, order=order)
    ungrouped = 0
    records = 0
    levels: Counter[str] = Counter()
    # For group_by, map collector key -> (type, value); also stash start/end fields.
    group_fields: dict[str, dict[str, Any]] = {}

    for record in reader:
        if select.matches(record):
            records += 1
            level = record.get("level")
            if isinstance(level, str):
                levels[level] += 1
        if group_by is None:
            tid = record.get("trace_id")
            if isinstance(tid, str):
                collector.add(record, tid)
            else:
                if record.get("event") in ("span.start", "span.end") or record.get("span_id"):
                    ungrouped += 1
        else:
            gv = group_value(record, group_by)
            if gv is None:
                ungrouped += 1
                continue
            type_name, norm = gv
            key = json.dumps([type_name, norm], sort_keys=True, separators=(",", ":"), default=str)
            group_fields.setdefault(key, {"type": type_name, "value": norm})
            # Prefer fields from span.start for later group attribution.
            if record.get("event") == "span.start":
                group_fields[key]["start_record"] = dict(record)
            elif record.get("event") == "span.end" and "start_record" not in group_fields[key]:
                group_fields[key]["end_record"] = dict(record)
            collector.add(record, key)

    totals = _SpanTotals()
    totals_duration = _DurationAcc(max_samples=max_samples)
    totals_buckets: dict[str | None, _BucketAcc] = {}
    group_accs: dict[str, _GroupAcc] = {}

    for group_key, tr in collector.finish(predicate=select.matches):
        nodes = _walk(tr.spans)
        if group_by is not None:
            meta = group_fields[group_key]
            if group_key not in group_accs:
                group_accs[group_key] = _GroupAcc(
                    value=meta["value"],
                    type_name=meta["type"],
                    duration=_DurationAcc(max_samples=max_samples),
                )
            gacc = group_accs[group_key]
            for node in nodes:
                _add_node_stats(node, duration_acc=totals_duration, counters=totals)
                _add_node_stats(node, duration_acc=gacc.duration, counters=gacc)
                if bucket_size is not None:
                    start = _bucket_start(_node_anchor(node), bucket_size)
                    if start in totals_buckets or len(totals_buckets) < max_buckets:
                        bacc = totals_buckets.setdefault(
                            start, _BucketAcc(duration=_DurationAcc(max_samples=max_samples))
                        )
                        _add_node_stats(node, duration_acc=bacc.duration, counters=bacc)
                    if start in gacc.buckets or len(gacc.buckets) < max_buckets:
                        bacc = gacc.buckets.setdefault(
                            start, _BucketAcc(duration=_DurationAcc(max_samples=max_samples))
                        )
                        _add_node_stats(node, duration_acc=bacc.duration, counters=bacc)
            continue

        for node in nodes:
            _add_node_stats(node, duration_acc=totals_duration, counters=totals)
            if bucket_size is not None:
                start = _bucket_start(_node_anchor(node), bucket_size)
                if start in totals_buckets or len(totals_buckets) < max_buckets:
                    bacc = totals_buckets.setdefault(
                        start, _BucketAcc(duration=_DurationAcc(max_samples=max_samples))
                    )
                    _add_node_stats(node, duration_acc=bacc.duration, counters=bacc)
            if node.span is None:
                continue
            gkey = json.dumps(["str", node.span], separators=(",", ":"))
            if gkey not in group_accs:
                group_accs[gkey] = _GroupAcc(
                    value=node.span,
                    type_name="str",
                    duration=_DurationAcc(max_samples=max_samples),
                )
            gacc = group_accs[gkey]
            _add_node_stats(node, duration_acc=gacc.duration, counters=gacc)
            if bucket_size is not None:
                start = _bucket_start(_node_anchor(node), bucket_size)
                if start in gacc.buckets or len(gacc.buckets) < max_buckets:
                    bacc = gacc.buckets.setdefault(
                        start, _BucketAcc(duration=_DurationAcc(max_samples=max_samples))
                    )
                    _add_node_stats(node, duration_acc=bacc.duration, counters=bacc)

    # Fix invalid_durations: build_trace drops non-numeric duration_ms, so ends
    # with invalid durations look like duration_ms is None. Count ends where
    # duration_ms is None as invalid only when the node has an end — but valid
    # ends always set a number. Ends with "fast"/-1 leave duration_ms None.
    # Those are exactly invalid_durations. However missing duration on a normal
    # end also None — schema always sends duration_ms on span.end from slogger.
    # Our fixtures set invalid ones explicitly. OK.

    group_rows = sorted(
        group_accs.values(),
        key=lambda g: (
            -g.spans,
            g.type_name,
            json.dumps(g.value, sort_keys=True, default=str),
        ),
    )[:top]

    totals_out: dict[str, Any] = {
        "records": records,
        "levels": dict(sorted(levels.items())),
        "spans": totals.spans,
        "completed": totals.completed,
        "failed": totals.failed,
        "unfinished": totals.unfinished,
        "missing_start": totals.missing_start,
        "invalid_durations": totals.invalid_durations,
        "duration_ms": totals_duration.to_dict(),
    }
    if bucket_size is not None:
        totals_out["buckets"] = _format_buckets(totals_buckets, spans=True)

    return {
        "schema_version": 1,
        "order": order,
        "records": records,
        "skipped_lines": reader.skipped_lines,
        "group_by": group_by,
        "spans": True,
        "bucket": bucket_label,
        "totals": totals_out,
        "groups": [
            {
                **{
                    k: v
                    for k, v in g.to_dict(
                        spans=True, with_buckets=bucket_size is not None
                    ).items()
                    if k != "levels"
                },
            }
            for g in group_rows
        ],
        "groups_capped": collector.groups_capped,
        "ungrouped": ungrouped,
        "warnings": list(reader.warnings),
    }


def summary(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    after: str | None = None,
    group_by: str | None = None,
    top: int = 50,
    order: Order = "concat",
) -> dict[str, Any]:
    predicate = filters if filters is not None else Filters()
    reader = Reader(sources, after=after, order=order)
    matched = 0
    levels: Counter[str] = Counter()
    loggers: Counter[str] = Counter()
    first_id = None
    last_id = None
    first_ts = None
    last_ts = None
    first_moment = None
    last_moment = None
    ungrouped = 0
    groups_capped = False
    groups: dict[str, _GroupAcc] = {}

    for record in reader:
        if not predicate.matches(record):
            continue
        matched += 1
        rid = record.get("_id")
        if first_id is None:
            first_id = rid
        last_id = rid
        level = record.get("level")
        if isinstance(level, str):
            levels[level] += 1
        logger = record.get("logger")
        if isinstance(logger, str):
            loggers[logger] += 1
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
        if group_by is not None:
            gv = group_value(record, group_by)
            if gv is None:
                ungrouped += 1
            else:
                type_name, norm = gv
                key = json.dumps(
                    [type_name, norm], sort_keys=True, separators=(",", ":"), default=str
                )
                if key not in groups:
                    if len(groups) >= 10_000:
                        groups_capped = True
                        ungrouped += 1
                    else:
                        groups[key] = _GroupAcc(value=norm, type_name=type_name)
                if key in groups:
                    groups[key].records += 1
                    if isinstance(level, str):
                        groups[key].levels[level] += 1

    logger_rows = dict(
        sorted(loggers.items(), key=lambda item: (-item[1], item[0]))[:20]
    )
    group_rows = sorted(
        groups.values(),
        key=lambda g: (-g.records, g.type_name, json.dumps(g.value, sort_keys=True, default=str)),
    )[:top]
    return {
        "schema_version": 1,
        "order": order,
        "matched": matched,
        "skipped_lines": reader.skipped_lines,
        "levels": dict(sorted(levels.items())),
        "loggers": logger_rows,
        "first_id": first_id,
        "last_id": last_id,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "group_by": group_by,
        "groups": [
            {
                "value": g.value,
                "type": g.type_name,
                "count": g.records,
                "levels": dict(sorted(g.levels.items())),
            }
            for g in group_rows
        ],
        "groups_capped": groups_capped,
        "ungrouped": ungrouped,
        "warnings": list(reader.warnings),
    }
