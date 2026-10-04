"""Independent, bounded formula oracles for generated qualification fixtures.

No slogger import. Production callers stream values/rows; only fixture-defined
field paths and at most forty file boundaries are retained.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE_PATHS = tuple(
    (name,)
    for name in (
        "timestamp",
        "level",
        "logger",
        "message",
        "file",
        "func",
        "line",
        "fixture_ordinal",
        "fixture_file",
        "fixture_kind",
        "service",
        "region",
        "request_id",
        "tenant_id",
        "order_id",
        "http.status_code",
        "http",
        "custom.labels.environment",
        "custom",
        "tags",
        "attempt",
        "payload_bytes",
    )
) + (
    ("http", "status_code"),
    ("http", "method"),
    ("http", "route"),
    ("custom", "labels"),
    ("custom", "labels", "environment"),
    ("custom", "worker"),
    ("custom", "worker", "partition"),
    ("custom", "worker", "zone"),
)


def residues(start, end, residue, period):
    return (end + period - 1 - residue) // period - (start + period - 1 - residue) // period


def positive_checkout(n):
    return n % 8 == 0 and n % 10 >= 4 and n % 997 > 498


def field_occurrences(files):
    """All paths, including containers, sparse leaves and literal dotted keys."""
    n = files[-1]["ordinal_end_exclusive"]
    k = len(files)
    blocks = sum(item["ordinary_blocks"] for item in files)
    paths = {path: n for path in BASE_PATHS}
    paths.update(
        {
            ("cost_units",): n - sum(residues(0, n, lane, 10) for lane in (0, 1)),
            ("latency_ms",): n - residues(0, n, 0, 12),
            ("optional_flag",): n - residues(0, n, 0, 7),
            ("mixed_value",): n - residues(0, n, 0, 8),
            ("group_bucket",): n - sum(residues(0, n, lane, 64) for lane in range(8)),
            ("sparse_metric",): sum(residues(0, n, lane, 11) for lane in range(3)),
            ("key with spaces",): residues(0, n, 0, 211),
            ('quoted"key',): residues(0, n, 0, 211),
            ("boundary_transition",): 16 * k,
            ("trace_id",): 15 * blocks + 16 * k - 2,
            ("span_id",): 14 * blocks + 16 * k - 2,
            ("span",): 14 * blocks + 16 * k - 2,
            ("parent_span_id",): 12 * blocks + 11 * k - 2,
            ("event",): 6 * blocks + 8 * k,
            ("status",): 3 * blocks + 4 * k - 1,
            ("duration_ms",): 3 * blocks + 4 * k - 1,
            ("error",): 2 * sum((item["ordinary_blocks"] + 10) // 11 for item in files),
            ("error_type",): 2 * sum((item["ordinary_blocks"] + 10) // 11 for item in files),
        }
    )
    for path in (
        ("custom", "receipt"),
        ("custom", "receipt", "sequence"),
        ("custom", "receipt", "confirmed"),
        ("custom", "receipt", "comment"),
    ):
        paths[path] = residues(0, n, 0, 13)
    for item in files:
        paths[(item["late_field_name"],)] = 1
    return paths


def trace_values(files, seed):
    """Every trace scalar in lexical discovery order, with exact occurrences."""
    for i, item in enumerate(files):
        for block in range(item["ordinary_blocks"]):
            yield f"{seed:08x}{i:08x}{block:016x}", 15
    yield f"f17e{seed:08x}{0:020x}", 6
    for boundary in range(1, len(files) + 1):
        yield f"f17e{seed:08x}{boundary:020x}", 8 if boundary == len(files) else 16


def span_values(files):
    blocks = sum(item["ordinary_blocks"] for item in files)
    k = len(files)
    ids = {
        "0000000000000001": 2 * blocks + 5 * k,
        "0000000000000002": 6 * blocks + 4 * k + 3,
        "0000000000000003": 6 * blocks + 4 * k - 2,
        "0000000000000004": 3 * (k - 1),
    }
    labels = {
        "checkout_request": 2 * blocks,
        "reserve_inventory": 6 * blocks,
        "authorize_payment": 6 * blocks,
        "cross_file_checkout": 5 * k,
        "fetch_inventory": 4 * k + 3,
        "confirm_payment": 4 * k - 2,
        "reconcile_invoice": 3 * (k - 1),
    }
    return ids, labels


def scoped_search_ordinals(count, case):
    """Known literal probes over the positive-checkout applied scope."""
    if case == "long_marker":
        return (n for n in range(0, count, 4096) if positive_checkout(n))
    if case == "hidden_file_full":
        return (n for n in range(0, count, 8) if positive_checkout(n))
    if case == "hidden_file_console":
        return iter(())  # Exact file string occurs only in hidden attribution.
    raise ValueError(case)


def filtered_tree_rows(files, seed):
    """Full expected DFS stream for service=checkout and cost_units>0.

    Each trace/block retains at most two candidates. Trace-level events never
    match this scope; every visible trace is context. Direct-match roots and
    child spans retain original first appearance, even across physical files.
    """

    def row(kind, trace, span=None, ordinal=None, direct=0, lifecycle=None):
        return {
            "kind": kind,
            "trace_id": trace,
            "span_id": span,
            "ordinal": ordinal,
            "context_only": kind != "record" and direct == 0,
            "match_count": 1 if kind == "record" else direct,
            "lifecycle": lifecycle,
        }

    for i, item in enumerate(files):
        for block in range(item["ordinary_blocks"]):
            base = item["ordinal_start"] + 8 + block * 16
            root_match, child_match = positive_checkout(base), positive_checkout(base + 8)
            if root_match or child_match:
                trace = f"{seed:08x}{i:08x}{block:016x}"
                yield row("trace", trace)
                yield row(
                    "span", trace, "0000000000000001", direct=int(root_match), lifecycle="complete"
                )
                if root_match:
                    yield row("record", None, ordinal=base)
                if child_match:
                    yield row("span", trace, "0000000000000003", direct=1, lifecycle="complete")
                    yield row("record", None, ordinal=base + 8)
        tail = item["ordinal_end_exclusive"] - 8
        head = files[i + 1]["ordinal_start"] if i + 1 < len(files) else None
        root_match = positive_checkout(tail)
        child_match = head is not None and positive_checkout(head)
        if root_match or child_match:
            trace = f"f17e{seed:08x}{i + 1:020x}"
            yield row("trace", trace)
            yield row(
                "span",
                trace,
                "0000000000000001",
                direct=int(root_match),
                lifecycle="complete" if head is not None else "incomplete",
            )
            if root_match:
                yield row("record", None, ordinal=tail)
            if child_match:
                yield row("span", trace, "0000000000000003", direct=1, lifecycle="complete")
                yield row("record", None, ordinal=head)


def envelope_spec(raw_limit=8 * 1024**2, working=64 * 1024**2, page=16 * 1024**2):
    """Fixture specifications, not an application admission assertion."""
    return {
        "budgets": {
            "max_record_bytes": raw_limit,
            "working_memory_bytes": working,
            "page_memory_bytes": page,
        },
        "encoded_cases": [
            {
                "name": f"encoded_limit_{delta:+d}",
                "target_line_bytes": raw_limit + delta,
                "shape": '{"message":"<ASCII payload>"}\\n',
                "planned_result": (
                    "raw admission should pass; test decoded/operation admission independently"
                )
                if delta <= 0
                else "explicit record_too_large failure with admitted prefix retained",
            }
            for delta in (-1, 0, 1)
        ],
        "decoded_cases": [
            {
                "name": "decoded_below_page",
                "items": 200000,
                "word": "word",
                "planned_result": "candidate admitted under defaults; verify on both interpreters",
            },
            {
                "name": "decoded_above_page",
                "items": 300000,
                "word": "word",
                "planned_result": (
                    "candidate decoded page admission failure; verify actual size/diagnostic"
                ),
            },
            {
                "name": "decoded_large_working",
                "items": 1000000,
                "word": "word",
                "planned_result": (
                    "raw below 8 MiB, decoded/pretty working admission should fail explicitly"
                ),
            },
        ],
        "decoded_shape": '{"message":"decoded budget probe","items":["word",...]}\\n',
        "measurement_requirements": [
            "prefix / candidate / trailing valid record",
            "strict raw bytes and hashes",
            "decoded and pretty allocations per interpreter",
            "capture status, diagnostic, retained prefix and complete-operation gate",
            "single-record console/JSON/search/discovery admission and full content",
            "resource-decrease rejection and prior effective settings unchanged",
        ],
        "limitations": (
            "Count-derived decoded sizes are candidates, not exact platform-in"
            "dependent byte thresholds. Measure actual size and operation work"
            "ing allocations at ticket 24; no preview/skip passes."
        ),
    }


def write_encoded_probe(path, target_bytes):
    """Bounded writer for a complete ASCII JSON object at exact encoded length."""
    prefix, suffix = b'{"message":"', b'"}\n'
    remaining = target_bytes - len(prefix) - len(suffix)
    assert remaining >= 0
    h = hashlib.sha256()
    with Path(path).open("xb", buffering=65536) as stream:
        stream.write(prefix)
        h.update(prefix)
        while remaining:
            chunk = b"a" * min(remaining, 65536)
            stream.write(chunk)
            h.update(chunk)
            remaining -= len(chunk)
        stream.write(suffix)
        h.update(suffix)
    return {"bytes": target_bytes, "sha256": h.hexdigest()}


def write_decoded_probe(path, items):
    prefix, element, suffix = b'{"message":"decoded budget probe","items":[', b'"word"', b"]}\n"
    h = hashlib.sha256()
    size = 0
    with Path(path).open("xb", buffering=65536) as stream:

        def append(data):
            nonlocal size
            stream.write(data)
            h.update(data)
            size += len(data)

        append(prefix)
        for i in range(items):
            append(element if i == 0 else b"," + element)
        append(suffix)
    return {"bytes": size, "items": items, "sha256": h.hexdigest()}


def walk_paths(record, parent=()):
    for key, value in record.items():
        path = parent + (key,)
        yield path
        if isinstance(value, dict):
            yield from walk_paths(value, path)


def self_test(root, fixture_root):
    """Decode only the existing 624-row representative sample, plus tiny probes."""
    paths = [fixture_root / "small-verification" / f"repeat-0-part-{i:02d}.jsonl" for i in range(3)]
    files, field_counts, observed_trace_records, selected = [], {}, 0, 0
    observed_ids, observed_labels = {}, {}
    ordinal = 0
    for i, path in enumerate(paths):
        start = ordinal
        with path.open("rb") as stream:
            file_rows = sum(1 for _ in stream)
        with path.open("rb") as stream:
            for raw in stream:
                record = json.loads(raw)
                assert record["fixture_ordinal"] == ordinal
                local = ordinal - start
                if local < 8:
                    expected_trace = (
                        None if i == 0 and local >= 6 else f"f17e{20261004:08x}{i:020x}"
                    )
                elif local >= file_rows - 8:
                    expected_trace = f"f17e{20261004:08x}{i + 1:020x}"
                else:
                    phase = (local - 8) % 16
                    expected_trace = (
                        None if phase == 15 else f"{20261004:08x}{i:08x}{(local - 8) // 16:016x}"
                    )
                assert record.get("trace_id") == expected_trace
                if "span_id" in record:
                    observed_ids[record["span_id"]] = observed_ids.get(record["span_id"], 0) + 1
                    observed_labels[record["span"]] = observed_labels.get(record["span"], 0) + 1
                for field in walk_paths(record):
                    field_counts[field] = field_counts.get(field, 0) + 1
                observed_trace_records += "trace_id" in record
                selected += positive_checkout(ordinal)
                ordinal += 1
        files.append(
            {
                "ordinal_start": start,
                "ordinal_end_exclusive": ordinal,
                "ordinary_blocks": (ordinal - start - 16) // 16,
                "late_field_name": f"late_only_key_{i:02d}",
            }
        )
    assert field_counts == field_occurrences(files)
    assert sum(count for _, count in trace_values(files, 20261004)) == observed_trace_records
    ids, labels = span_values(files)
    assert sum(ids.values()) == sum(labels.values()) == field_counts[("span",)]
    assert observed_ids == ids and observed_labels == labels
    leaves, trace_context, context_spans = 0, 0, 0
    for row in filtered_tree_rows(files, 20261004):
        if row["kind"] == "record":
            assert positive_checkout(row["ordinal"])
            leaves += 1
        elif row["kind"] == "trace":
            assert row["context_only"] and row["match_count"] == 0
            trace_context += 1
        else:
            context_spans += row["context_only"]
    assert leaves == selected
    assert list(scoped_search_ordinals(ordinal, "hidden_file_console")) == []
    assert sum(1 for _ in scoped_search_ordinals(ordinal, "hidden_file_full")) == selected
    root.mkdir(parents=True, exist_ok=False)
    probe_ids = []
    for target in (1023, 1024, 1025):
        path = root / f"encoded-{target}.jsonl"
        identity = write_encoded_probe(path, target)
        assert (
            path.stat().st_size == target
            and len(json.loads(path.read_bytes())["message"]) == target - 15
        )
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
        probe_ids.append(identity)
    decoded = root / "decoded-1000.jsonl"
    identity = write_decoded_probe(decoded, 1000)
    assert len(json.loads(decoded.read_bytes())["items"]) == 1000
    assert hashlib.sha256(decoded.read_bytes()).hexdigest() == identity["sha256"]
    result = {
        "passed": True,
        "scope": "stdlib/tiny sources only, no slogger import or application measurement",
        "decoded_representative_records": ordinal,
        "complete_field_paths": len(field_counts),
        "trace_value_occurrences": observed_trace_records,
        "positive_checkout_leaves": leaves,
        "trace_context_nodes": trace_context,
        "context_span_nodes": context_spans,
        "tiny_encoded_probes": probe_ids,
        "tiny_decoded_probe": identity,
        "checks": [
            "complete path occurrence formulas",
            "streamed trace/span scalar totals",
            "filtered ancestor/leaf formulas",
            "scoped hidden-field search",
            "exact encoded-byte writer",
            "decoded-growth writer",
        ],
    }
    (root / "self-test.json").write_text(json.dumps(result, indent=2) + "\n")
    (root / "record-envelope-specs.json").write_text(json.dumps(envelope_spec(), indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test-dir", type=Path, required=True)
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("/private/tmp/slogger-tui-implementation/scale-fixtures"),
    )
    args = parser.parse_args()
    print(json.dumps(self_test(args.self_test_dir, args.fixture_root), indent=2))
