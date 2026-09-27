"""Discover keys and value distributions in log sources."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Reader, Source

_DISTINCT_CAP = 10_000
_SAMPLE_CAP = 5


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _stable_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return value


def fields(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    scan: int = 100_000,
    key: str | None = None,
    top: int = 10,
    order: Order = "concat",
) -> dict[str, Any]:
    predicate = filters if filters is not None else Filters()
    reader = Reader(sources, order=order)
    limit = None if scan == 0 else scan

    if key is not None:
        counts: Counter[object] = Counter()
        scanned = 0
        for record in reader:
            if not predicate.matches(record):
                continue
            scanned += 1
            if key in record:
                counts[_stable_value(record[key])] += 1
            if limit is not None and scanned >= limit:
                break
        ranking = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))[:top]
        return {
            "schema_version": 1,
            "key": key,
            "scanned": scanned,
            "top": [{"value": value, "count": count} for value, count in ranking],
        }

    key_types: dict[str, Counter[str]] = {}
    key_counts: Counter[str] = Counter()
    key_distinct: dict[str, set[object]] = {}
    key_distinct_capped: dict[str, bool] = {}
    key_samples: dict[str, list[object]] = {}
    scanned = 0
    for record in reader:
        if not predicate.matches(record):
            continue
        scanned += 1
        for name, value in record.items():
            if name == "_id":
                continue
            key_counts[name] += 1
            type_counter = key_types.setdefault(name, Counter())
            type_counter[_type_name(value)] += 1
            distinct = key_distinct.setdefault(name, set())
            stable = _stable_value(value)
            if stable not in distinct:
                if len(distinct) < _DISTINCT_CAP:
                    distinct.add(stable)
                    samples = key_samples.setdefault(name, [])
                    if len(samples) < _SAMPLE_CAP:
                        samples.append(value if not isinstance(value, (dict, list)) else stable)
                else:
                    key_distinct_capped[name] = True
        if limit is not None and scanned >= limit:
            break

    keys_out: dict[str, Any] = {}
    for name, count in sorted(key_counts.items()):
        type_counter = key_types[name]
        most_common_type = type_counter.most_common(1)[0][0]
        keys_out[name] = {
            "type": most_common_type,
            "types": sorted(type_counter),
            "count": count,
            "present_pct": round(100.0 * count / scanned, 1) if scanned else 0.0,
            "distinct": len(key_distinct.get(name, ())),
            "distinct_capped": key_distinct_capped.get(name, False),
            "samples": key_samples.get(name, []),
        }

    return {
        "schema_version": 1,
        "scanned": scanned,
        "scan_capped": limit is not None and scanned >= limit,
        "keys": keys_out,
    }
