"""Inspect IXR, query records and group logs; optionally use native Polars."""

from __future__ import annotations

import argparse
import json

from slogger.tools import Field, count_rows, mean_of, scan, sum_of


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("python", "polars"), default="python")
    args = parser.parse_args()
    records = [
        {"logger": "api", "message": "slow", "duration_ms": 800},
        {"logger": "api", "message": "fast", "duration_ms": 100},
        {"logger": "worker", "message": "job", "duration_ms": 600},
    ]
    predicate = Field("duration_ms").ge(500)
    print(predicate.explain())
    result = (
        scan(records)
        .filter(predicate)
        .sort_by("duration_ms", descending=True)
        .select("message", "duration_ms")
        .limit(2)
        .execute(backend=args.backend)
    )
    assert [row["message"] for row in result.records] == ["slow", "job"]
    assert [origin.position for origin in result.origins if origin is not None] == [0, 2]
    assert all(origin is not None and origin.kind == "iterable" for origin in result.origins)
    grouped = (
        scan(records)
        .group_by("logger")
        .aggregate(
            rows=count_rows(),
            total_ms=sum_of(Field("duration_ms")),
            mean_ms=mean_of(Field("duration_ms")),
        )
        .execute(backend=args.backend)
    )
    assert [row["rows"] for row in grouped.records] == [2, 1]
    assert grouped.origins == [None, None]
    for record, origin in zip(result.records, result.origins, strict=True):
        print(f"{origin}: {record}")
    print(json.dumps({"records": result.records, "groups": grouped.records}, indent=2))


if __name__ == "__main__":
    main()
