"""Compare aggregate stats between two source sets."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Source, resolve_sources
from slogger.tools.stats import stats

_SPAN_METRICS = (
    "spans",
    "completed",
    "failed",
    "unfinished",
)
_DURATION_METRICS = ("count", "min", "max", "mean", "p50", "p95", "p99")


def _delta(before: Any, after: Any) -> dict[str, Any]:
    if before is None or after is None:
        return {"before": before, "after": after, "abs": None, "pct": None}
    abs_v = after - before
    pct = None if before == 0 else (abs_v / before) * 100
    return {"before": before, "after": after, "abs": abs_v, "pct": pct}


def _group_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("type")),
        json.dumps(row.get("value"), sort_keys=True, default=str),
    )


def diff(
    before: Source | Sequence[Source],
    after: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    group_by: str | None = None,
    spans: bool = False,
    top: int = 50,
    order: Order = "concat",
) -> dict[str, Any]:
    before_stats = stats(
        before,
        filters=filters,
        group_by=group_by,
        spans=spans,
        order=order,
        top=10_000,
    )
    after_stats = stats(
        after,
        filters=filters,
        group_by=group_by,
        spans=spans,
        order=order,
        top=10_000,
    )

    totals: dict[str, Any] = {
        "records": _delta(before_stats["totals"]["records"], after_stats["totals"]["records"])
    }
    if spans:
        for name in _SPAN_METRICS:
            totals[name] = _delta(
                before_stats["totals"].get(name), after_stats["totals"].get(name)
            )
        b_dur = before_stats["totals"].get("duration_ms", {})
        a_dur = after_stats["totals"].get("duration_ms", {})
        for name in _DURATION_METRICS:
            key = f"duration_ms.{name}"
            cell = _delta(b_dur.get(name), a_dur.get(name))
            if b_dur.get("percentiles_capped") or a_dur.get("percentiles_capped"):
                if name in ("p50", "p95", "p99"):
                    cell["approximate"] = True
            totals[key] = cell

    before_groups = {_group_key(g): g for g in before_stats["groups"]}
    after_groups = {_group_key(g): g for g in after_stats["groups"]}
    shared = sorted(set(before_groups) & set(after_groups))
    only_after = sorted(set(after_groups) - set(before_groups))
    only_before = sorted(set(before_groups) - set(after_groups))

    def metric_row(b: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = {
            "value": a.get("value", b.get("value")),
            "type": a.get("type", b.get("type")),
            "records": _delta(b.get("records", 0), a.get("records", 0)),
        }
        if spans:
            for name in _SPAN_METRICS:
                row[name] = _delta(b.get(name), a.get(name))
            b_dur = b.get("duration_ms", {})
            a_dur = a.get("duration_ms", {})
            for name in _DURATION_METRICS:
                cell = _delta(b_dur.get(name), a_dur.get(name))
                if b_dur.get("percentiles_capped") or a_dur.get("percentiles_capped"):
                    if name in ("p50", "p95", "p99"):
                        cell["approximate"] = True
                row[f"duration_ms.{name}"] = cell
        return row

    group_rows = [
        metric_row(before_groups[k], after_groups[k]) for k in shared
    ][:top]
    added = [
        {
            "value": after_groups[k]["value"],
            "type": after_groups[k]["type"],
            **{
                key: after_groups[k].get(key)
                for key in ("records", "spans", "completed", "failed", "unfinished")
                if key in after_groups[k]
            },
        }
        for k in only_after
    ][:top]
    removed = [
        {
            "value": before_groups[k]["value"],
            "type": before_groups[k]["type"],
            **{
                key: before_groups[k].get(key)
                for key in ("records", "spans", "completed", "failed", "unfinished")
                if key in before_groups[k]
            },
        }
        for k in only_before
    ][:top]

    truncated = (
        len(shared) > top or len(only_after) > top or len(only_before) > top
    )
    before_paths = [
        s if isinstance(s, str) else "mem" for s in resolve_sources(before)
    ]
    after_paths = [
        s if isinstance(s, str) else "mem" for s in resolve_sources(after)
    ]
    return {
        "schema_version": 1,
        "order": order,
        "group_by": group_by,
        "spans": spans,
        "before": {
            "sources": before_paths,
            "records": before_stats["totals"]["records"],
        },
        "after": {
            "sources": after_paths,
            "records": after_stats["totals"]["records"],
        },
        "totals": totals,
        "groups": group_rows,
        "added": added,
        "removed": removed,
        "truncated": truncated,
        "warnings": list(
            dict.fromkeys(before_stats["warnings"] + after_stats["warnings"])
        ),
    }
