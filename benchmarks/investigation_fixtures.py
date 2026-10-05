#!/usr/bin/env python3
"""Task-owned deterministic qualification inputs. No slogger import or benchmark.

Run self-test before generation. Generation is streaming, and expected metrics
come from fixed periodic formulas, never from an IXR executor or stored rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from collections import deque
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

VERSION = "slogger-scale-fixtures-v1"
DEFAULT_SEED = 20261004
DEFAULT_FILES = 40
DEFAULT_TARGET_BYTES = 125_000_000
BLOCK_ROWS = 16
FILE_EDGE_ROWS = 8
TAIL_RESERVE_BYTES = 100_000
SERVICES = (
    "checkout",
    "inventory",
    "payments",
    "shipping",
    "catalog",
    "gateway",
    "orders",
    "notifications",
)
REGIONS = ("us-east-1", "eu-west-1", "ap-south-1", "us-west-2")
LEVELS = ("DEBUG", "INFO", "INFO", "WARNING", "ERROR")
GROUPS = (
    "missing",
    "null",
    "false",
    "true",
    "integer:0",
    "integer:1",
    "string:blue",
    "string:green",
)
BUCKET_VALUES = (None, None, False, True, 0, 1, "blue", "green")
TEMPLATES = (
    (
        "Accepted {method} {path}; queued request {request} for tenant {te"
        "nant} with retry budget {retry}."
    ),
    (
        "Resolved inventory reservation for order {order}; warehouse {ware"
        "house} returned {items} available items."
    ),
    (
        "Payment authorization {request} reached provider {provider}; resp"
        "onse code {code}, attempt {retry}."
    ),
    (
        "Published order {order} to shipment queue; region {region}, parti"
        "tion {partition}, acknowledgement received."
    ),
    "Cache lookup for {path} finished with {cache}; key {request}, TTL {ttl} seconds.",
    (
        "Dependency {provider} exceeded warning threshold while serving {r"
        "equest}; continuing retry attempt {retry}."
    ),
    (
        "Reconciled invoice for tenant {tenant} and order {order}; applied"
        " {items} line items in region {region}."
    ),
    (
        "Completed scheduled catalogue refresh; shard {partition}, revisio"
        "n {request}, {items} products updated."
    ),
    (
        "Webhook delivery for order {order} received HTTP {code}; endpoint"
        " {path}, transport {provider}."
    ),
    (
        "Validated request {request}; principal tenant {tenant}, route {pa"
        "th}, method {method}, policy version {ttl}."
    ),
    (
        "Worker inspected queue partition {partition}; order {order}, leas"
        "e owner {warehouse}, retry count {retry}."
    ),
    (
        "Stored audit entry {request} for tenant {tenant}; provider {provi"
        "der}, cache state {cache}, code {code}."
    ),
)
DETAILS = (
    "observed connection reuse; TLS session valid; upstream headers accepted",
    "checked retry window; jitter bounded; circuit state closed; deadline retained",
    "validated payload schema; optional address absent; inventory snapshot consistent",
    "recorded trace context; parent request active; routing rule matched region",
    "compared ledger revision; reconciliation marker present; idempotency key accepted",
    "received queue acknowledgement; offset committed; delivery attempt accounted",
    "inspected cache entry; expiry scheduled; namespace version current",
    "checked authorization policy; tenant scope valid; audit event emitted",
)


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("ascii")


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def mix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
    return value ^ (value >> 31)


def timestamp(n: int) -> str:
    # Fixed logical sequence within a 14-day interval, independent of wall clock.
    milliseconds = n % (14 * 86_400_000)
    day, rest = divmod(milliseconds, 86_400_000)
    hour, rest = divmod(rest, 3_600_000)
    minute, rest = divmod(rest, 60_000)
    second, millisecond = divmod(rest, 1000)
    return f"2026-09-{15 + day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}Z"


def base_record(n: int, seed: int, file_index: int) -> dict[str, object]:
    mixed = mix64(n ^ seed)
    service = SERVICES[n % 8]
    request = f"req-{seed:08x}-{n:012d}"
    region = REGIONS[(n // 8) % 4]
    args = {
        "method": ("GET", "POST", "PUT", "DELETE")[mixed % 4],
        "path": (
            "/v1/orders",
            "/v1/inventory/reservations",
            "/v1/payments/authorize",
            "/health/ready",
        )[mixed % 4],
        "request": request,
        "tenant": f"tenant-{n % 257:03d}",
        "retry": mixed % 4,
        "order": f"ord-{n // 3:012d}",
        "warehouse": f"warehouse-{mixed % 19:02d}",
        "items": mixed % 48,
        "provider": ("ledger-primary", "bank-west", "inventory-edge", "delivery-router")[mixed % 4],
        "code": (200, 201, 429, 503)[n % 4],
        "region": region,
        "partition": n % 64,
        "cache": ("hit", "miss", "stale")[mixed % 3],
        "ttl": 30 + mixed % 600,
    }
    message = TEMPLATES[mixed % len(TEMPLATES)].format(**args)
    message += f" Correlation {request}; deployment release-{n % 23:02d}; route shard-{n % 64:02d}."
    if n % 4096 == 0:
        # Long messages contain readable varying ASCII observations, not fill bytes.
        details = " | ".join(
            f"step={j:03d} {DETAILS[(mixed + j) % len(DETAILS)]}; token={mixed ^ j:016x}"
            for j in range(520)
        )
        message += " Extended incident diagnostics: " + details + " LONG-MESSAGE-END-MARKER"
    elif n % 97 == 0:
        message += " Request diagnostics: " + " | ".join(
            f"phase={j:02d} {DETAILS[(mixed + j) % len(DETAILS)]}" for j in range(48)
        )
    record: dict[str, object] = {
        "timestamp": timestamp(n),
        "level": LEVELS[n % 5],
        "logger": f"shop.{service}.worker",
        "message": message,
        "file": f"services/{service}/handler.py",
        "func": "process_request",
        "line": 41 + n % 83,
        "fixture_ordinal": n,
        "fixture_file": file_index,
        "service": service,
        "region": region,
        "request_id": request,
        "tenant_id": f"tenant-{n % 257:03d}",
        "order_id": f"ord-{n // 3:012d}",
        "http.status_code": (200, 201, 429, 503)[n % 4],
        "http": {
            "status_code": (200, 204, 400, 404, 503)[n % 5],
            "method": args["method"],
            "route": args["path"],
        },
        "custom.labels.environment": ("canary-literal", "stable-literal")[n % 2],
        "custom": {
            "labels": {"environment": ("production", "staging", "development")[n % 3]},
            "worker": {"partition": n % 64, "zone": f"zone-{n % 7}"},
        },
        "tags": [service, region, ("interactive", "batch", "scheduled")[n % 3]],
        "attempt": n % 4,
        "payload_bytes": (n * 37) % 65536,
    }
    lane = n % 10
    if lane >= 2:
        record["cost_units"] = None if lane == 2 else 0 if lane == 3 else (n % 997) - 498
    lane = n % 12
    if lane >= 1:
        record["latency_ms"] = None if lane == 1 else 0.0 if lane == 2 else ((n * 17) % 2048) / 4
    lane = n % 7
    if lane >= 1:
        record["optional_flag"] = (None, False, True, False, True, False)[lane - 1]
    lane = n % 8
    if lane >= 1:
        record["mixed_value"] = (None, 0, False, True, "not-numeric", -3, 0.25)[lane - 1]
    bucket = (n // 8) % 8
    if bucket:
        record["group_bucket"] = BUCKET_VALUES[bucket]
    if n % 11 == 0:
        record["sparse_metric"] = 0
    elif n % 11 == 1:
        record["sparse_metric"] = None
    elif n % 11 == 2:
        record["sparse_metric"] = (n % 101) / 8
    if n % 13 == 0:
        record["custom"]["receipt"] = {"sequence": n, "confirmed": False, "comment": None}  # type: ignore[index]
    if n % 211 == 0:
        record["key with spaces"] = f"space-key-{n:012d}"
        record['quoted"key'] = 'decoded quote " and backslash \\ and newline\ncontent'
    return record


def regular_record(n: int, seed: int, file_index: int, block: int, phase: int) -> dict[str, object]:
    record = base_record(n, seed, file_index)
    record["fixture_kind"] = "ordinary"
    if phase == 15:
        record["message"] = str(record["message"]) + " Untraced queue maintenance event."
        return record
    record["trace_id"] = f"{seed:08x}{file_index:08x}{block:016x}"
    if phase == 14:
        record["message"] = str(record["message"]) + " Trace-level routing audit."
        return record
    child = 0 if phase in (0, 13) else 1 if phase <= 6 else 2
    record["span_id"] = f"{child + 1:016x}"
    record["span"] = ("checkout_request", "reserve_inventory", "authorize_payment")[child]
    if child:
        record["parent_span_id"] = "0000000000000001"
    if phase in (0, 1, 7):
        record["event"] = "span.start"
        record["message"] = f"Started {record['span']}; " + str(record["message"])
    elif phase in (6, 12, 13):
        record["event"] = "span.end"
        failed = phase in (12, 13) and block % 11 == 0
        record["status"] = "error" if failed else "ok"
        record["duration_ms"] = (
            (10 + (block % 128) / 4)
            if phase == 13
            else (block % 16) + 0.25
            if phase == 6
            else (block % 32) + 0.5
        )
        record["message"] = f"Finished {record['span']} with status {record['status']}; " + str(
            record["message"]
        )
        if failed:
            record["error_type"] = "ProviderTimeout"
            record["error"] = "provider response exceeded request deadline"
    return record


def edge_record(n: int, seed: int, file_index: int, side: str, phase: int) -> dict[str, object]:
    record = base_record(n, seed, file_index)
    record["fixture_kind"] = f"boundary_{side}"
    bootstrap = file_index == 0 and side == "head"
    boundary = file_index - 1 if side == "head" else file_index
    record["trace_id"] = f"f17e{seed:08x}{boundary + 1:020x}"
    record["boundary_transition"] = boundary
    if bootstrap:
        if phase >= 6:
            del record["trace_id"]
            record["message"] = "Bootstrap observer registered without a trace; " + str(
                record["message"]
            )
            return record
        span = 1 if phase in (1, 2, 3) else 0
        event = "span.start" if phase in (0, 1) else "span.end" if phase in (3, 5) else None
    elif side == "tail":
        span = 0 if phase in (0, 1) else 1 if phase <= 5 else 2
        event = "span.start" if phase in (0, 2, 6) else "span.end" if phase == 5 else None
    else:
        span = 2 if phase in (0, 1) else 3 if phase in (3, 4, 5) else 0
        event = "span.start" if phase == 3 else "span.end" if phase in (1, 5, 7) else None
    record["span_id"] = f"{span + 1:016x}"
    record["span"] = (
        "cross_file_checkout",
        "fetch_inventory",
        "confirm_payment",
        "reconcile_invoice",
    )[span]
    if span:
        record["parent_span_id"] = "0000000000000001"
    if event:
        record["event"] = event
    if event == "span.end":
        record["status"] = "error" if not bootstrap and span == 0 and boundary % 3 == 0 else "ok"
        record["duration_ms"] = (16.5, 2.25, 4.5, 3.75)[span]
    record["message"] = f"Cross-file lifecycle {side} phase={phase} span={record['span']}; " + str(
        record["message"]
    )
    if side == "tail" and phase == 7:
        # Each source has a late key and scalar value beyond ordinary preview caps.
        record[f"late_only_key_{file_index:02d}"] = f"late-file-{file_index:02d}-ordinal-{n:012d}"
    return record


def residue_count(start: int, end: int, residue: int, period: int) -> int:
    """Number of start <= n < end with n % period == residue."""
    return (end + period - 1 - residue) // period - (start + period - 1 - residue) // period


def lane_counts(start: int, end: int, period: int) -> list[int]:
    return [residue_count(start, end, lane, period) for lane in range(period)]


def expected_metrics(start: int, end: int, field: str) -> dict[str, object]:
    """Independent formula evaluation; fixed-size 8/64-group accumulators only.

    cost_units repeats every lcm(997, 10, 64)=319040 rows;
    latency_ms repeats every lcm(2048, 12, 64)=6144 rows.
    Work depends on those periods, never on population size.
    """
    denominator = 1 if field == "cost_units" else 4
    period = 319040 if field == "cost_units" else 6144
    overall = [0, 0, 0, None, None, 0, 0, 0]
    by_service = [[0, 0, 0, None, None, 0, 0, 0] for _ in SERVICES]
    by_bucket = [[0, 0, 0, None, None, 0, 0, 0] for _ in GROUPS]
    by_pair = [[0, 0, 0, None, None, 0, 0, 0] for _ in range(64)]
    positive_checkout = [0, 0, 0, None, None, 0, 0, 0]
    for residue in range(period):
        repetitions = residue_count(start, end, residue, period)
        if repetitions == 0:
            continue
        if field == "cost_units":
            lane = residue % 10
            present = lane >= 2
            numeric = lane >= 3
            numerator = 0 if lane == 3 else (residue % 997) - 498
        else:
            lane = residue % 12
            present = lane >= 1
            numeric = lane >= 2
            numerator = 0 if lane == 2 else (residue * 17) % 2048
        if not present:
            continue
        service = residue % 8
        bucket = (residue // 8) % 8
        accumulators = (
            overall,
            by_service[service],
            by_bucket[bucket],
            by_pair[service * 8 + bucket],
        )
        if field == "cost_units" and numeric and numerator > 0 and service == 0:
            accumulators = (*accumulators, positive_checkout)
        for accumulator in accumulators:
            accumulator[0] += repetitions
            if not numeric:
                accumulator[1] += repetitions
                continue
            accumulator[2] += repetitions * numerator
            accumulator[3] = numerator if accumulator[3] is None else min(accumulator[3], numerator)
            accumulator[4] = numerator if accumulator[4] is None else max(accumulator[4], numerator)
            accumulator[5 if numerator == 0 else 6 if numerator > 0 else 7] += repetitions

    def finish(accumulator: list) -> dict[str, object]:
        present, nulls, numerator_sum, minimum, maximum, zeros, positives, negatives = accumulator
        numeric_count = present - nulls
        mean = Fraction(numerator_sum, denominator * numeric_count) if numeric_count else None
        return {
            "selected_presence_count": present,
            "explicit_null_count": nulls,
            "numeric_count": numeric_count,
            "sum_numerator": numerator_sum,
            "numeric_zero_count": zeros,
            "positive_numeric_count": positives,
            "negative_numeric_count": negatives,
            "sum_denominator": denominator,
            "sum": numerator_sum / denominator if denominator > 1 else numerator_sum,
            "mean_exact": str(mean) if mean is not None else None,
            "mean": float(mean) if mean is not None else None,
            "min": minimum / denominator if minimum is not None else None,
            "max": maximum / denominator if maximum is not None else None,
        }

    summary = {
        "field": field,
        "scope": "all records intersect exists(selected field)",
        "overall": finish(overall),
        "by_service": [
            {"service": service, **finish(by_service[i])} for i, service in enumerate(SERVICES)
        ],
        "by_group_bucket": [
            {"typed_group": group, **finish(by_bucket[i])} for i, group in enumerate(GROUPS)
        ],
        "by_service_and_group_bucket": [
            {"service": service, "typed_group": group, **finish(by_pair[i * 8 + j])}
            for i, service in enumerate(SERVICES)
            for j, group in enumerate(GROUPS)
        ],
        "complete_group_counts": {
            "service": sum(row[0] > 0 for row in by_service),
            "group_bucket": sum(row[0] > 0 for row in by_bucket),
            "service_and_group_bucket": sum(row[0] > 0 for row in by_pair),
        },
        "high_cardinality_request_id": {
            "complete_group_count": overall[0],
            "all_group_counts": 1,
            "unique_value_formula": "req-{seed:08x}-{fixture_ordinal:012d}",
            "group_order": "ascending fixture_ordinal restricted to selected-field presence",
            "per_group_numeric_value_formula": "see field formula; explicit null is present",
        },
    }
    if field == "cost_units":
        summary["positive_checkout_scope"] = {
            "filter": 'service == "checkout" and cost_units > 0',
            **finish(positive_checkout),
        }
    return summary


def expected_distribution(start: int, end: int) -> dict[str, object]:
    cost = lane_counts(start, end, 10)
    latency = lane_counts(start, end, 12)
    flag = lane_counts(start, end, 7)
    mixed = lane_counts(start, end, 8)
    sparse = lane_counts(start, end, 11)
    bucket = [
        sum(residue_count(start, end, i, 64) for i in range(group * 8, group * 8 + 8))
        for group in range(8)
    ]
    return {
        "cost_units": {
            "missing": sum(cost[:2]),
            "null": cost[2],
            "formula_zero_lane": cost[3],
            "integer_formula_lanes": sum(cost[4:]),
            "lanes_n_mod_10": cost,
            "formula": "n%10 <2 missing; ==2 null; ==3 zero; >=4 integer (n%997)-498",
        },
        "latency_ms": {
            "missing": latency[0],
            "null": latency[1],
            "formula_zero_lane": latency[2],
            "quarter_float_formula_lanes": sum(latency[3:]),
            "lanes_n_mod_12": latency,
            "formula": "n%12 ==0 missing; ==1 null; ==2 zero; >=3 ((n*17)%2048)/4",
        },
        "optional_flag": {
            "missing": flag[0],
            "null": flag[1],
            "false": flag[2] + flag[4] + flag[6],
            "true": flag[3] + flag[5],
        },
        "mixed_value": dict(
            zip(
                (
                    "missing",
                    "null",
                    "zero",
                    "false",
                    "true",
                    "string",
                    "negative_integer",
                    "quarter_float",
                ),
                mixed,
                strict=True,
            )
        ),
        "sparse_metric": {
            "missing": sum(sparse[3:]),
            "zero_lane": sparse[0],
            "null": sparse[1],
            "fractional_formula_lane": sparse[2],
        },
        "group_bucket": dict(zip(GROUPS, bucket, strict=True)),
        "services": dict(zip(SERVICES, lane_counts(start, end, 8), strict=True)),
        "regions": {
            region: sum(residue_count(start, end, i, 32) for i in range(j * 8, j * 8 + 8))
            for j, region in enumerate(REGIONS)
        },
        "levels": {
            "DEBUG": residue_count(start, end, 0, 5),
            "INFO": residue_count(start, end, 1, 5) + residue_count(start, end, 2, 5),
            "WARNING": residue_count(start, end, 3, 5),
            "ERROR": residue_count(start, end, 4, 5),
        },
        "literal_http_status_code": dict(
            zip((200, 201, 429, 503), lane_counts(start, end, 4), strict=True)
        ),
        "nested_http_status_code": dict(
            zip((200, 204, 400, 404, 503), lane_counts(start, end, 5), strict=True)
        ),
        "long_message_records": residue_count(start, end, 0, 4096),
        "medium_message_records": sum(
            residue_count(start, end, i, math.lcm(97, 4096))
            for i in range(0, math.lcm(97, 4096), 97)
            if i % 4096 != 0
        ),
        "receipt_records": residue_count(start, end, 0, 13),
        "quoted_space_key_records": residue_count(start, end, 0, 211),
        "unique_request_ids": end - start,
    }


def expected_range(start: int, end: int) -> dict[str, object]:
    return {
        "ordinal_start": start,
        "ordinal_end_exclusive": end,
        "records": end - start,
        "distributions": expected_distribution(start, end),
        "numeric_expectations": {
            field: expected_metrics(start, end, field) for field in ("cost_units", "latency_ms")
        },
    }


def sha256_file(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    size = lines = 0
    with path.open("rb", buffering=1024 * 1024) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    return digest.hexdigest(), size, lines


def small_observed(path: Path) -> dict[str, object]:
    """Bounded decoder verification, independent of formula expected values."""
    metrics = {
        field: {
            "presence": 0,
            "nulls": 0,
            "numeric": 0,
            "sum": Fraction(0),
            "min": None,
            "max": None,
            "by_service": [[0, 0, Fraction(0)] for _ in SERVICES],
            "by_pair": [[0, 0, Fraction(0)] for _ in range(64)],
        }
        for field in ("cost_units", "latency_ms")
    }
    records = 0
    with path.open("rb") as stream:
        for line in stream:
            assert line.endswith(b"\n") and line.isascii()
            record = json.loads(line)
            assert isinstance(record, dict) and record["message"].isascii()
            n = record["fixture_ordinal"]
            assert record["service"] == SERVICES[n % 8]
            assert record["request_id"].endswith(f"{n:012d}")
            assert record["http.status_code"] != record["http"]["status_code"] or n % 20 in (0, 19)
            records += 1
            for field, stats in metrics.items():
                if field not in record:
                    continue
                stats["presence"] += 1
                value = record[field]
                targets = (stats["by_service"][n % 8], stats["by_pair"][(n % 8) * 8 + (n // 8) % 8])
                for target in targets:
                    target[0] += 1
                if value is None:
                    stats["nulls"] += 1
                    for target in targets:
                        target[1] += 1
                else:
                    assert type(value) in (int, float) and math.isfinite(value)
                    exact = Fraction(value)
                    stats["numeric"] += 1
                    stats["sum"] += exact
                    stats["min"] = value if stats["min"] is None else min(stats["min"], value)
                    stats["max"] = value if stats["max"] is None else max(stats["max"], value)
                    for target in targets:
                        target[2] += exact
    return {"records": records, "metrics": metrics}


def check_observed(observed: dict[str, object], expected: dict[str, object]) -> None:
    assert observed["records"] == expected["records"]
    for field in ("cost_units", "latency_ms"):
        actual = observed["metrics"][field]
        formula = expected["numeric_expectations"][field]
        totals = formula["overall"]
        assert actual["presence"] == totals["selected_presence_count"]
        assert actual["nulls"] == totals["explicit_null_count"]
        assert actual["numeric"] == totals["numeric_count"]
        assert actual["sum"] == Fraction(totals["sum_numerator"], totals["sum_denominator"])
        assert actual["min"] == totals["min"] and actual["max"] == totals["max"]
        for rows, names in (
            (actual["by_service"], formula["by_service"]),
            (actual["by_pair"], formula["by_service_and_group_bucket"]),
        ):
            for row, named in zip(rows, names, strict=True):
                assert row[0] == named["selected_presence_count"]
                assert row[1] == named["explicit_null_count"]
                assert row[2] == Fraction(named["sum_numerator"], named["sum_denominator"])


def generate_file(
    path: Path, seed: int, file_index: int, ordinal_start: int, target_bytes: int
) -> dict[str, object]:
    if path.exists() or path.with_suffix(path.suffix + ".part").exists():
        raise FileExistsError(f"Refusing to overwrite task-owned fixture {path}")
    partial = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    n = ordinal_start
    size = 0
    minimum_line = sys.maxsize
    maximum_line = 0
    maximum_message = 0
    blocks = 0

    def append(stream, record):
        nonlocal n, size, minimum_line, maximum_line, maximum_message
        line = json_bytes(record)
        stream.write(line)
        digest.update(line)
        size += len(line)
        minimum_line = min(minimum_line, len(line))
        maximum_line = max(maximum_line, len(line))
        maximum_message = max(maximum_message, len(record["message"]))
        n += 1

    with partial.open("xb", buffering=1024 * 1024) as stream:
        for phase in range(8):
            append(stream, edge_record(n, seed, file_index, "head", phase))
        while size < max(0, target_bytes - TAIL_RESERVE_BYTES):
            for phase in range(16):
                append(stream, regular_record(n, seed, file_index, blocks, phase))
            blocks += 1
        for phase in range(8):
            append(stream, edge_record(n, seed, file_index, "tail", phase))
        stream.flush()
        os.fsync(stream.fileno())
    partial.replace(path)
    return {
        "name": path.name,
        "path": str(path),
        "bytes": size,
        "allocated_bytes": path.stat().st_blocks * 512,
        "sha256": digest.hexdigest(),
        "physical_lines": n - ordinal_start,
        "records": n - ordinal_start,
        "ordinal_start": ordinal_start,
        "ordinal_end_exclusive": n,
        "ordinary_blocks": blocks,
        "ordinary_records": blocks * 16,
        "boundary_records": 16,
        "minimum_record_bytes_including_newline": minimum_line,
        "maximum_record_bytes_including_newline": maximum_line,
        "maximum_decoded_message_ascii_bytes": maximum_message,
        "late_field_name": f"late_only_key_{file_index:02d}",
        "expected": expected_range(ordinal_start, n),
    }


def self_test(root: Path, seed: int) -> dict[str, object]:
    directory = root / "small-verification"
    directory.mkdir(parents=True, exist_ok=False)
    runs = []
    for run in range(2):
        files = []
        ordinal = 0
        for index in range(3):
            path = directory / f"repeat-{run}-part-{index:02d}.jsonl"
            entry = generate_file(path, seed, index, ordinal, 350_000)
            check_observed(small_observed(path), entry["expected"])
            disk_hash, disk_bytes, disk_lines = sha256_file(path)
            assert (disk_hash, disk_bytes, disk_lines) == (
                entry["sha256"],
                entry["bytes"],
                entry["records"],
            )
            ordinal = entry["ordinal_end_exclusive"]
            files.append(entry)
        runs.append(files)
    for first, repeated in zip(*runs, strict=True):
        assert first["sha256"] == repeated["sha256"]
        assert first["bytes"] == repeated["bytes"] and first["records"] == repeated["records"]
    # Boundary IDs and canonical parent/lifecycle survive the physical split.
    for index in range(2):
        left = runs[0][index]
        right = runs[0][index + 1]
        with Path(left["path"]).open("rb") as stream:
            tail_lines = deque(stream, maxlen=8)
        with Path(right["path"]).open("rb") as stream:
            head_lines = [next(stream) for _ in range(8)]
        tail = json.loads(tail_lines[0])
        head = json.loads(head_lines[7])
        assert tail["trace_id"] == head["trace_id"] and tail["span_id"] == head["span_id"]
        assert tail["event"] == "span.start" and head["event"] == "span.end"
    # Independently decode a full period plus a partial offset; no row list.
    period_path = directory / "formula-period.jsonl"
    period_start = 319017
    period_end = period_start + 319077
    with period_path.open("xb", buffering=1024 * 1024) as stream:
        for n in range(period_start, period_end):
            # Compact analytic validation source avoids an unnecessary large sample.
            record = {
                "fixture_ordinal": n,
                "service": SERVICES[n % 8],
                "request_id": f"req-{seed:08x}-{n:012d}",
                "message": "formula validation",
                "http.status_code": 1,
                "http": {"status_code": 2},
            }
            lane = n % 10
            if lane >= 2:
                record["cost_units"] = None if lane == 2 else 0 if lane == 3 else n % 997 - 498
            lane = n % 12
            if lane >= 1:
                record["latency_ms"] = (
                    None if lane == 1 else 0.0 if lane == 2 else (n * 17 % 2048) / 4
                )
            stream.write(json_bytes(record))
    check_observed(small_observed(period_path), expected_range(period_start, period_end))
    period_identity = sha256_file(period_path)
    period_path.unlink()  # Small synthetic verifier input only; representative samples remain.
    result = {
        "passed": True,
        "generator_version": VERSION,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seed": seed,
        "representative_repeat_files": [
            {"sha256": entry["sha256"], "bytes": entry["bytes"], "records": entry["records"]}
            for entry in runs[0]
        ],
        "period_formula_verification": {
            "ordinal_start": period_start,
            "ordinal_end_exclusive": period_end,
            "sha256": period_identity[0],
            "bytes": period_identity[1],
            "records": period_identity[2],
            "deleted_after_verification": True,
        },
        "checks": [
            "strict ASCII JSONL and ASCII messages",
            "decoded selected presence/null/numeric count/sum/min/max",
            "all 8 service groups and all 64 typed secondary groups",
            "period plus offset",
            "second generation content hashes equal",
            "streaming disk hash/size/physical-line count",
            "canonical root start/end across file boundary",
        ],
    }
    write_json(root / "small-verification.json", result)
    return result


def trace_expectation(files: list[dict[str, object]]) -> dict[str, object]:
    count = len(files)
    blocks = sum(entry["ordinary_blocks"] for entry in files)
    return {
        "ordinary_traces": blocks,
        "ordinary_span_nodes": blocks * 3,
        "ordinary_completed_span_nodes": blocks * 3,
        "ordinary_failed_span_nodes": sum(
            ((entry["ordinary_blocks"] + 10) // 11) * 2 for entry in files
        ),
        "complete_cross_file_boundary_traces": max(0, count - 1),
        "bootstrap_traces": 1 if count else 0,
        "pending_outgoing_boundary_traces": 1 if count else 0,
        "boundary_span_nodes": count * 4 + 1 if count else 0,
        "boundary_completed_span_nodes": count * 4 - 1 if count else 0,
        "boundary_unfinished_span_nodes": 2 if count else 0,
        "boundary_failed_span_nodes": (count + 1) // 3 if count > 1 else 0,
        "canonical_span_start_records": blocks * 3 + count * 4 + 1 if count else 0,
        "canonical_span_end_records": blocks * 3 + count * 4 - 1 if count else 0,
        "untraced_records": blocks + 2 if count else 0,
        "traced_records_without_span": blocks,
        "ordering": (
            "source supplied order then first appearance; timestamp is a fixed"
            " increasing logical clock"
        ),
        "note": (
            "Each ordinary 16-record block is complete. Eight tail records joi"
            "n eight next-file head records. Final supplied-file tail intentio"
            "nally has root and confirm_payment starts without ends. Span IDs/"
            "names repeat in different traces and are never identities alone."
        ),
    }


def generate(root: Path, seed: int, count: int, target: int) -> dict[str, object]:
    verification_path = root / "small-verification.json"
    if not verification_path.exists():
        raise RuntimeError("Run --self-test successfully before --generate")
    verification = json.loads(verification_path.read_text())
    if (
        not verification["passed"]
        or verification["seed"] != seed
        or verification["generator_sha256"]
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise RuntimeError("Self-test must pass for the exact generator content and seed")
    if (root / "manifest.json").exists():
        raise FileExistsError("Refusing to replace completed manifest or fixture sources")
    free_before = shutil.disk_usage(root).free
    required = count * target + 20_000_000_000
    if free_before < required:
        raise OSError(f"Need {required} free bytes including 20 GB margin; found {free_before}")
    source_dir = root / "sources"
    source_dir.mkdir(parents=True, exist_ok=False)
    files = []  # At most 40 fixed manifest entries; no row or unique-value population.
    ordinal = 0
    print(
        json.dumps(
            {
                "phase": "generation_started",
                "free_bytes": free_before,
                "file_count": count,
                "target_file_bytes": target,
            }
        ),
        flush=True,
    )
    for index in range(count):
        path = source_dir / f"part-{index:02d}.jsonl"
        entry = generate_file(path, seed, index, ordinal, target)
        if not 100_000_000 <= entry["bytes"] <= 200_000_000:
            raise AssertionError(f"File outside approved scale size: {entry['bytes']}")
        disk_hash, disk_bytes, disk_lines = sha256_file(path)
        if (disk_hash, disk_bytes, disk_lines) != (
            entry["sha256"],
            entry["bytes"],
            entry["records"],
        ):
            raise AssertionError(f"Disk verification differs for {path}")
        entry["disk_hash_size_linecount_verified"] = True
        ordinal = entry["ordinal_end_exclusive"]
        files.append(entry)
        write_json(
            root / "generation-progress.json",
            {
                "completed_files": index + 1,
                "bytes": sum(file["bytes"] for file in files),
                "records": ordinal,
                "latest_file": entry["name"],
            },
        )
        print(
            json.dumps(
                {
                    "phase": "file_verified",
                    "index": index,
                    "bytes": entry["bytes"],
                    "records": entry["records"],
                    "cumulative_records": ordinal,
                }
            ),
            flush=True,
        )
    datasets = {}
    for label, selected in (("1GB", files[:8]), ("5GB", files)):
        paths = [entry["path"] for entry in selected]
        (root / f"files-{label.lower()}.txt").write_text("\n".join(paths) + "\n", encoding="ascii")
        identity = hashlib.sha256()
        for entry in selected:
            identity.update(
                json_bytes(
                    {
                        "name": entry["name"],
                        "sha256": entry["sha256"],
                        "bytes": entry["bytes"],
                        "records": entry["records"],
                    }
                )
            )
        datasets[label] = {
            "ordered_source_paths": paths,
            "source_file_count": len(selected),
            "bytes": sum(entry["bytes"] for entry in selected),
            "allocated_source_bytes": sum(entry["allocated_bytes"] for entry in selected),
            "ordered_identity_sha256": identity.hexdigest(),
            "expected": expected_range(0, selected[-1]["ordinal_end_exclusive"]),
            "trace_expectations": trace_expectation(selected),
            "late_fields": [entry["late_field_name"] for entry in selected],
        }
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest = {
        "generator_version": VERSION,
        "generator_sha256": script_hash,
        "seed": seed,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "generation_python": sys.version,
        "target_file_bytes": target,
        "units": "decimal GB/MB; 1 GB=1,000,000,000 bytes, 125 MB=125,000,000 bytes",
        "whole_record_boundary_strategy": (
            "eight head rows, whole sixteen-row ordinary blocks until target m"
            "inus 100,000 bytes, eight tail rows; no record splitting"
        ),
        "disk_free_bytes_before": free_before,
        "disk_free_bytes_after": shutil.disk_usage(root).free,
        "total_source_bytes": sum(entry["bytes"] for entry in files),
        "total_source_allocated_bytes": sum(entry["allocated_bytes"] for entry in files),
        "files": files,
        "datasets": datasets,
        "integrity": (
            "generation SHA-256 and independent streaming disk SHA-256/size/ne"
            "wline count match for every source; decoded formula checks and re"
            "peated content hashes passed on small samples"
        ),
        "bounded_memory": (
            "one decoded record/encoded line; 1 MiB buffered I/O; fixed formul"
            "a periods; 8/64-group counters; at most 40 manifest entries; no p"
            "opulation-sized lists/dicts or unique-ID sets"
        ),
        "cache_conditions": (
            "OS cache uncontrolled/generated warm. Generation and integrity re"
            "ads warm source data; no cache drop and no cold-storage claim."
        ),
        "qualification_status": (
            "fixture preparation only; no application latency, RSS, CPU, manag"
            "ed-cache disk or ticket-24 acceptance measurements"
        ),
        "preservation": (
            "Keep sources until ticket-24 complete measurements and concise ev"
            "idence/hashes are recorded. Ticket-24 implementer owns benchmark "
            "integration and cleanup."
        ),
    }
    write_json(root / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "phase": "generation_complete",
                "total_source_bytes": manifest["total_source_bytes"],
                "records": ordinal,
                "manifest": str(root / "manifest.json"),
            }
        ),
        flush=True,
    )
    return manifest


def smoke_fixture(root: Path, seed: int = DEFAULT_SEED) -> dict[str, object]:
    """Build a complete small formula fixture for application harness validation."""
    root.mkdir(parents=True, exist_ok=False)
    source_dir = root / "sources"
    source_dir.mkdir()
    files = []
    ordinal = 0
    for index in range(3):
        entry = generate_file(source_dir / f"part-{index:02d}.jsonl", seed, index, ordinal, 350_000)
        check_observed(small_observed(Path(entry["path"])), entry["expected"])
        ordinal = entry["ordinal_end_exclusive"]
        files.append(entry)
    identity = hashlib.sha256()
    for entry in files:
        identity.update(
            json_bytes({key: entry[key] for key in ("name", "sha256", "bytes", "records")})
        )
    dataset = {
        "source_file_count": len(files),
        "bytes": sum(entry["bytes"] for entry in files),
        "ordered_identity_sha256": identity.hexdigest(),
        "expected": expected_range(0, ordinal),
        "trace_expectations": trace_expectation(files),
    }
    manifest = {
        "seed": seed,
        "generator_version": VERSION,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": files,
        "datasets": {"smoke": dataset},
        "qualification_status": "tiny harness verification only",
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--files", type=int, default=DEFAULT_FILES)
    parser.add_argument("--target-bytes", type=int, default=DEFAULT_TARGET_BYTES)
    args = parser.parse_args()
    if args.smoke:
        print(json.dumps(smoke_fixture(args.root, args.seed)))
        return
    args.root.mkdir(parents=True, exist_ok=True)
    if args.self_test:
        print(
            json.dumps({"phase": "self_test_complete", **self_test(args.root, args.seed)}),
            flush=True,
        )
    if args.generate:
        generate(args.root, args.seed, args.files, args.target_bytes)
    if not args.self_test and not args.generate:
        parser.error("Choose --self-test and/or --generate, or --smoke")


if __name__ == "__main__":
    main()
