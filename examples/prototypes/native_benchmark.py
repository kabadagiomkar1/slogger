"""THROWAWAY reproducible fixture generator for the native storage experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate(root, gb):
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    # 200 MB files, 1024-byte JSONL objects. Approximately 1 / 5 decimal GB.
    records_per_file = 200_000_000 // 1024
    for source in range(gb * 5):
        path = root / f"source-{source:02}.jsonl"
        paths.append(str(path))
        with path.open("wb", buffering=4 * 1024 * 1024) as output:
            for i in range(records_per_file):
                ordinal = source * records_per_file + i
                record = {
                    "timestamp": "2026-10-04T10:00:00.123Z",
                    "level": "ERROR" if ordinal % 20 == 0 else "INFO",
                    "logger": f"shop.service{source % 3}",
                    "message": "Payment gateway timeout"
                    if ordinal % 20 == 0
                    else "Checkout handled",
                    "duration_ms": ordinal % 1000,
                    "trace_id": f"trace-{ordinal // 12}",
                    "span_id": f"span-{ordinal % 3}",
                    "parent_span_id": "",
                    "span_name": "checkout",
                    "request": {"method": "POST", "customer_id": f"customer-{ordinal}"},
                    "filename": "checkout.py",
                    "lineno": 42,
                    "payload": "",
                }
                line = json.dumps(record, separators=(",", ":")).encode()
                # Inserting plain ASCII into payload preserves valid JSON and exact width.
                marker = b'"payload":""'
                padded = line.replace(marker, b'"payload":"' + b"x" * (1023 - len(line)) + b'"')
                output.write(padded + b"\n")
        print(f"Generated {path.name}: {path.stat().st_size:,} bytes", flush=True)
    (root / "files.json").write_text(json.dumps(paths, indent=2))
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--gb", type=int, choices=(1, 5), default=1)
    args = parser.parse_args()
    generate(args.directory, args.gb)
