#!/usr/bin/env python3
"""Create deterministic ASCII JSONL and append a refresh marker; stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def records():
    messages = (
        "Checkout accepted",
        "Inventory reserved",
        "Payment authorization requested",
        "Payment authorized",
        "Shipping rate selected",
        "Order confirmation queued",
        "Payment gateway retry",
        "Refund scheduled",
    )
    spans = ("checkout", "inventory", "payment", "shipping")
    items = ("book", "tea", "desk", "notebook")
    start = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
    for n in range(64):
        trace = n // 16
        span = spans[(n % 16) // 4]
        phase = n % 4
        message = messages[n % len(messages)]
        if n == 21:
            message = "Carrier quote received: " + (
                "priority delivery window and insurance details; " * 25
            )
        level = "DEBUG" if phase == 1 else "INFO"
        if n % 16 == 6:
            level = "WARNING"
        elif n % 16 == 10:
            level = "ERROR"
        row = {
            "timestamp": (start + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%S.123Z"),
            "level": level,
            "logger": "shop." + span,
            "message": message,
            "trace_id": f"trace-{trace:02d}",
            "span_id": f"{trace}-{span}",
            "span": span,
            "request_id": f"req-{trace:02d}",
            "tenant": "north" if trace % 2 == 0 else "south",
            "customer": {
                "id": f"customer-{n % 7:02d}",
                "tier": ("standard", "plus", "business")[n % 3],
            },
            "order.total": (n % 9) * 12.5,
            "cache_hit": n % 3 == 0,
        }
        if span != "checkout":
            row["parent_span_id"] = f"{trace}-checkout"
        if phase == 0:
            row["event"] = "span.start"
        elif phase == 3:
            row.update(
                event="span.end",
                duration_ms=(n * 37) % 407,
                status="error" if span == "payment" else "ok",
            )
        if n % 3 == 0:
            row["response_ms"] = (n * 17) % 900
        if n % 5 == 0:
            row["coupon"] = "WELCOME" if n % 2 == 0 else None
        if n % 4 == 0:
            row["items"] = list(items[(n // 4) % 3 :])
        yield row


REFRESH_MARKER = {
    "timestamp": "2026-10-04T08:02:00.123Z",
    "level": "INFO",
    "logger": "shop.refresh",
    "message": "Manual refresh marker",
    "tenant": "north",
    "response_ms": 100,
    "manual_marker": "append-once",
}


def append_marker(directory: Path, parser: argparse.ArgumentParser):
    """Append only to the exact untouched task fixture, once."""
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="ascii"))
        for name in ("application.jsonl", "worker.jsonl"):
            digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if digest != manifest["sha256"][name]:
                parser.error("demo changed or marker already appended; generate a fresh directory")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"cannot verify demo: {error}")
    with (directory / "worker.jsonl").open("a", encoding="ascii", newline="\n") as stream:
        stream.write(json.dumps(REFRESH_MARKER) + "\n")
    print("Appended once: refresh => 65 records; response_ms count 23 / sum 8281")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="task-owned output directory")
    parser.add_argument("--append", action="store_true", help="append one verified refresh marker")
    args = parser.parse_args()
    if args.append:
        append_marker(args.directory, parser)
        return
    names = ("application.jsonl", "worker.jsonl", "manifest.json")
    if any((args.directory / name).exists() for name in names):
        parser.error("demo output already exists; choose another directory")
    args.directory.mkdir(parents=True, exist_ok=True)
    rows = list(records())
    hashes = {}
    for name, batch in zip(names[:2], (rows[:27], rows[27:]), strict=True):
        payload = "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in batch)
        with (args.directory / name).open("x", encoding="ascii", newline="\n") as stream:
            stream.write(payload)
        hashes[name] = hashlib.sha256(payload.encode("ascii")).hexdigest()
    manifest = {
        "purpose": "manual exercise preparation, not validation evidence",
        "generator": "examples/investigation_demo.py; deterministic fixture version 1",
        "records": 64,
        "source_records": {"application.jsonl": 27, "worker.jsonl": 37},
        "response_ms_present": 22,
        "response_ms_sum": 8181,
        "response_ms_by_tenant": {
            "north": {"count": 11, "sum": 4080},
            "south": {"count": 11, "sum": 4101},
        },
        "coupon_present": 13,
        "coupon_values": {"WELCOME": 7, "null": 6},
        "retry_records": 8,
        "source_order": list(names[:2]),
        "cross_file_trace": "trace-01",
        "wide_record": {"input": "application.jsonl", "physical_line": 22},
        "sha256": hashes,
    }
    with (args.directory / names[2]).open("x", encoding="ascii") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
