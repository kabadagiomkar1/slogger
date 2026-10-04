#!/usr/bin/env python3
"""Reproducible native investigation qualification; self-test imports no slogger.

Actual use requires --measure, a pinned clean checkout and integrated ticket 22.
Full operation execution and full result verification are separate timed phases.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, is_dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from .investigation_oracles import (
    field_occurrences,
    filtered_tree_rows,
    scoped_search_ordinals,
    span_values,
    trace_values,
    write_decoded_probe,
    write_encoded_probe,
)

GIB = 1024**3
MIB = 1024**2
DEFAULT_MANIFEST = Path("/private/tmp/slogger-tui-implementation/scale-fixtures/manifest.json")
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
TERMINAL = {"complete", "ready", "committed", "failed", "canceled", "cancelled", "closed"}


def plain(value):
    if is_dataclass(value):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb", buffering=MIB) as stream:
        while chunk := stream.read(MIB):
            h.update(chunk)
    return h.hexdigest()


def allocated(root):
    """Task-owned tree, no symlink following or population file-list retention."""
    total = 0
    for parent, _, names in os.walk(root, followlinks=False):
        for name in names:
            try:
                total += (Path(parent) / name).lstat().st_blocks * 512
            except FileNotFoundError:
                pass  # Concurrently removed staging file; next sample reconciles.
    return total


def cpu_seconds(text):
    days, clock = text.split("-", 1) if "-" in text else ("0", text)
    parts = [float(piece) for piece in clock.split(":")]
    result = 0.0
    for piece in parts:
        result = result * 60 + piece
    return float(days) * 86400 + result


def descendants(rows, root_pid):
    """PS rows contain only PID, PPID, RSS and CPU; no command/credential text."""
    parents = {}
    for pid, parent, _rss, _cpu in rows:
        parents.setdefault(parent, []).append(pid)
    selected = {root_pid}
    queue = [root_pid]
    while queue:
        for child in parents.get(queue.pop(), ()):
            if child not in selected:
                selected.add(child)
                queue.append(child)
    return {pid: (rss * 1024, cpu) for pid, _, rss, cpu in rows if pid in selected}


def process_snapshot(root_pid):
    proc = subprocess.Popen(
        ["ps", "-axo", "pid=,ppid=,rss=,time="], stdout=subprocess.PIPE, text=True
    )
    output, _ = proc.communicate()
    if proc.returncode:
        raise RuntimeError("ps process sampling unavailable")
    rows = []
    for line in output.splitlines():
        pid, parent, rss, cpu = line.split()
        if int(pid) != proc.pid:  # Exclude the sampler's transient PS process.
            rows.append((int(pid), int(parent), int(rss), cpu_seconds(cpu)))
    return descendants(rows, root_pid)


def rusage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    factor = 1 if sys.platform == "darwin" else 1024
    return {
        "self_cpu_seconds": own.ru_utime + own.ru_stime,
        "waited_child_cpu_seconds": children.ru_utime + children.ru_stime,
        "self_ru_maxrss_bytes": own.ru_maxrss * factor,
        "waited_child_ru_maxrss_bytes": children.ru_maxrss * factor,
        "ru_maxrss_units": (
            "Darwin bytes; Linux KiB converted to bytes; self/child maxima are"
            " not simultaneous group RSS"
        ),
    }


class Evidence:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.stream = (root / "events.jsonl").open("x", buffering=1)
        self.failed_operations = []

    def emit(self, event, **data):
        with self.lock:
            self.stream.write(
                json.dumps(
                    {"event": event, "monotonic": time.monotonic(), **plain(data)}, allow_nan=False
                )
                + "\n"
            )

    def close(self):
        self.stream.close()


class Sampler:
    """Sample process subtree and allocated managed disk with bounded state.

    Sampled RSS/disk peaks are lower bounds between samples. Waited-child CPU
    rusage complements snapshot deltas; short-lived unreaped children can escape
    samples. CPU is one-core-normalized and may exceed 100 percent.
    """

    def __init__(self, evidence, managed_root, interval=0.5, snapshot=process_snapshot):
        self.evidence, self.root, self.interval = evidence, managed_root, interval
        self.snapshot = snapshot
        self.session = None
        self.job = None
        self.phase = "setup"
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.last = {}
        self.error = None
        self.peak_rss = self.peak_disk = self.max_processes = 0
        self.phase_peaks = {}
        self.sampler_cpu = 0.0
        self.sample_count = 0

    def sample(self):
        now = time.monotonic()
        cpu_start = time.thread_time()
        processes = self.snapshot(os.getpid())
        cpu_delta = (
            sum(max(0, cpu - self.last.get(pid, (0, 0))[1]) for pid, (_, cpu) in processes.items())
            if self.last
            else 0
        )
        self.last = processes
        rss = sum(value[0] for value in processes.values())
        disk = allocated(self.root)
        self.peak_rss, self.peak_disk = max(self.peak_rss, rss), max(self.peak_disk, disk)
        self.max_processes = max(self.max_processes, len(processes))
        peak = self.phase_peaks.setdefault(
            self.phase, {"rss_bytes": 0, "allocated_managed_bytes": 0, "processes": 0}
        )
        peak["rss_bytes"] = max(peak["rss_bytes"], rss)
        peak["allocated_managed_bytes"] = max(peak["allocated_managed_bytes"], disk)
        peak["processes"] = max(peak["processes"], len(processes))
        self.sample_count += 1
        self.sampler_cpu += time.thread_time() - cpu_start
        usage = self.session.resources if self.session is not None else None
        self.evidence.emit(
            "sample",
            phase=self.phase,
            process_count=len(processes),
            process_rss_bytes=rss,
            snapshot_cpu_delta_seconds=cpu_delta,
            allocated_managed_bytes=disk,
            resources=usage,
            status=getattr(self.session, "status", None),
            job_status=getattr(self.job, "status", None),
            process_pids=list(processes),
            sampler_monotonic=now,
        )

    def run(self):
        while not self.stop.is_set():
            try:
                self.sample()
            except Exception as error:
                self.error = repr(error)
                self.evidence.emit("sampler_error", error=self.error)
            self.stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join()


class Phase:
    def __init__(self, evidence, sampler, name):
        self.evidence, self.sampler, self.name = evidence, sampler, name

    def __enter__(self):
        self.sampler.phase = self.name
        self.start, self.before = time.perf_counter(), rusage()
        self.evidence.emit("phase_started", name=self.name, rusage=self.before)
        return self

    def __exit__(self, kind, error, traceback):
        after = rusage()
        self.evidence.emit(
            "phase_finished",
            name=self.name,
            seconds=time.perf_counter() - self.start,
            success=error is None,
            error=repr(error) if error else None,
            self_cpu_seconds=after["self_cpu_seconds"] - self.before["self_cpu_seconds"],
            waited_child_cpu_seconds=after["waited_child_cpu_seconds"]
            - self.before["waited_child_cpu_seconds"],
            rusage=after,
            resources=self.sampler.session.resources if self.sampler.session else None,
            sampled_phase_peaks=self.sampler.phase_peaks.get(self.name),
        )


def pages(handle, member="records", limit=256):
    offset = 0
    count = getattr(handle, "record_count", None)
    if count is None:
        count = handle.status.record_count
    while offset < count:
        page = handle.page(offset, limit)
        rows = getattr(page, member)
        if not rows or page.next_offset <= offset:
            raise AssertionError("Complete result paging stalled before expected exhaustion")
        yield page
        offset = page.next_offset
    assert offset == count


def cost(n):
    lane = n % 10
    return "missing" if lane < 2 else None if lane == 2 else 0 if lane == 3 else n % 997 - 498


def latency(n):
    lane = n % 12
    return (
        "missing" if lane == 0 else None if lane == 1 else 0.0 if lane == 2 else (n * 17 % 2048) / 4
    )


def expected_ordinals(count, predicate=lambda n: True):
    return (n for n in range(count) if predicate(n))


def check_membership(handle, expected, files, source_paths):
    """Compare every row, identity and physical origin; never retain the view."""
    starts = [item["ordinal_start"] for item in files]  # At most forty boundaries.
    checked = 0
    for page in pages(handle):
        for record, identity, origin in zip(
            page.records, page.identities, page.origins, strict=True
        ):
            n = next(expected)
            occurrence = bisect.bisect_right(starts, n) - 1
            assert record["fixture_ordinal"] == identity.ordinal == n
            assert identity.input_occurrence == occurrence
            assert origin.source == source_paths[occurrence]
            assert origin.position == n - starts[occurrence] + 1
            checked += 1
    assert next(expected, None) is None
    return checked


def typed(value, present=True):
    if not present:
        return "missing"
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return f"integer:{value}"
    return f"string:{value}"


def check_summary(row, expected):
    assert row["count"] == expected["selected_presence_count"]
    exact = Fraction(expected["sum_numerator"], expected["sum_denominator"])
    assert Fraction(row["sum"]) == exact
    assert row["mean"] == expected["mean"]
    assert row["min"] == expected["min"] and row["max"] == expected["max"]


def check_small_groups(handle, expected):
    known = {(item["service"], item["typed_group"]): item for item in expected}
    seen = set()  # Exactly 64 fixture-defined combinations, independent of population.
    last_first = -1
    first = {}
    for n in range(640):
        if cost(n) != "missing":
            first.setdefault(
                (
                    SERVICES[n % 8],
                    typed(
                        (None, None, False, True, 0, 1, "blue", "green")[(n // 8) % 8],
                        (n // 8) % 8 != 0,
                    ),
                ),
                n,
            )
    for page in pages(handle):
        assert all(origin is None for origin in page.origins)
        for row in page.records:
            key = (row["service"], typed(row.get("bucket"), "bucket" in row))
            assert key not in seen and first[key] > last_first
            seen.add(key)
            last_first = first[key]
            check_summary(row, known[key])
    assert seen == set(known)


def check_high_cardinality(handle, count, seed, field="cost_units"):
    value_formula = cost if field == "cost_units" else latency
    expected = (n for n in range(count) if value_formula(n) != "missing")
    checked = 0
    for page in pages(handle):
        assert all(origin is None for origin in page.origins)
        for row in page.records:
            n = next(expected)
            value = value_formula(n)
            assert row["request"] == f"req-{seed:08x}-{n:012d}" and row["count"] == 1
            assert row["sum"] == (0 if value is None else value)
            assert row["mean"] == row["min"] == row["max"] == value
            checked += 1
    assert next(expected, None) is None
    return checked


class DiskBitmap:
    """Exact tree leaf coverage on disk; eight fixed 16 KiB cache blocks."""

    BLOCK = 16384

    def __init__(self, path, count):
        self.count, self.cache = count, OrderedDict()
        self.fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.ftruncate(self.fd, (count + 7) // 8)
        self.marked = 0

    def mark(self, n):
        assert 0 <= n < self.count
        byte, bit = divmod(n, 8)
        block, offset = divmod(byte, self.BLOCK)
        if block not in self.cache:
            if len(self.cache) == 8:
                old, payload = self.cache.popitem(last=False)
                os.pwrite(self.fd, payload, old * self.BLOCK)
            raw = os.pread(self.fd, self.BLOCK, block * self.BLOCK)
            self.cache[block] = bytearray(raw)
        payload = self.cache[block]
        self.cache.move_to_end(block)
        assert not payload[offset] & (1 << bit), "Duplicate tree record leaf"
        payload[offset] |= 1 << bit
        self.marked += 1

    def close(self):
        for block, payload in self.cache.items():
            os.pwrite(self.fd, payload, block * self.BLOCK)
        os.close(self.fd)


def tree_rows(tree, parent=None, depth=0):
    assert depth <= 6, "Fixture tree has no cycles and at most four levels"
    offset, previous = 0, -1
    while True:
        page = tree.children(parent, offset, 256)
        for row in page.rows:
            assert row.first_ordinal >= previous
            previous = row.first_ordinal
            yield row
            if row.kind != "record":
                yield from tree_rows(tree, row.key, depth + 1)
        if not page.has_more:
            break
        assert page.next_offset > offset
        offset = page.next_offset


def check_tree(tree, dataset, oracle_path):
    expected = dataset["trace_expectations"]
    counters = dict.fromkeys(
        ("trace", "span", "record", "complete", "incomplete", "failed", "starts", "ends"), 0
    )
    coverage = DiskBitmap(oracle_path, dataset["expected"]["records"])
    try:
        for row in tree_rows(tree):
            assert not row.context_only and not row.name_conflict
            counters[row.kind] += 1
            if row.kind == "record":
                coverage.mark(row.ordinal)
            elif row.kind == "span":
                counters[row.lifecycle] += 1
                counters["failed"] += row.status == "error"
                counters["starts"] += row.start_count
                counters["ends"] += row.end_count
        assert coverage.marked == dataset["expected"]["records"]
        assert (
            counters["trace"]
            == expected["ordinary_traces"] + expected["complete_cross_file_boundary_traces"] + 2
        )
        assert counters["span"] == expected["ordinary_span_nodes"] + expected["boundary_span_nodes"]
        assert (
            counters["complete"]
            == expected["ordinary_completed_span_nodes"] + expected["boundary_completed_span_nodes"]
        )
        assert counters["incomplete"] == expected["boundary_unfinished_span_nodes"]
        assert (
            counters["failed"]
            == expected["ordinary_failed_span_nodes"] + expected["boundary_failed_span_nodes"]
        )
        assert counters["starts"] == expected["canonical_span_start_records"]
        assert counters["ends"] == expected["canonical_span_end_records"]
        return counters
    finally:
        coverage.close()


def settle(job):
    while True:
        try:
            value = job.wait(0.1)
        except TimeoutError:
            continue
        if job.done:
            break
    assert job.status.phase in ("complete", "ready", "committed"), plain(job.status)
    if callable(getattr(job, "result", None)):
        return job.result()
    return value


def measure_job(evidence, sampler, name, create, verify):
    result = job = None
    try:
        with Phase(evidence, sampler, name + ":execute"):
            job = create()
            sampler.job = job
            result = settle(job)
        with Phase(evidence, sampler, name + ":verify_all_pages"):
            checked = verify(result)
        evidence.emit("operation_verified", name=name, checked=checked, status=job.status)
        return True
    except Exception as error:
        evidence.emit(
            "operation_failed",
            name=name,
            error=repr(error),
            status=getattr(job, "status", None),
            diagnostics=getattr(job, "diagnostics", None),
        )
        evidence.failed_operations.append({"name": name, "error": repr(error)})
        return False  # Failure remains evidence; later independent operations may proceed.
    finally:
        if result is not None:
            result.close()
        if job is not None and callable(getattr(job, "close", None)):
            job.close()
        sampler.job = None


def check_discovery(index, dataset, files, seed):
    known, seen, field_offset = field_occurrences(files), set(), 0
    while True:
        page = index.fields(offset=field_offset, limit=256)
        for choice in page.choices:
            assert choice.path not in seen and choice.occurrences == known[choice.path]
            seen.add(choice.path)
        if not page.has_more:
            break
        assert page.next_offset > field_offset
        field_offset = page.next_offset
    assert seen == set(known)
    count = dataset["expected"]["records"]
    # Complete bounded prefix partitions avoid population-sized SQL OFFSET scans.
    offset = 0
    for base in range(0, count, 1000):
        local = 0
        while True:
            prefix = f'"req-{seed:08x}-{base // 1000:09d}'
            page = index.values(("request_id",), prefix=prefix, offset=local, limit=256)
            for choice in page.choices:
                assert (
                    choice.value == f"req-{seed:08x}-{base + local:012d}"
                    and choice.occurrences == 1
                )
                local += 1
            if not page.has_more:
                break
            assert page.next_offset == local
        assert local == min(1000, count - base)
        offset += local
    assert offset == count
    expected_traces = trace_values(files, seed)
    trace_count = 0
    for i, item in enumerate(files):
        for block in range(0, item["ordinary_blocks"], 256):
            prefix = f'"{seed:08x}{i:08x}{block // 256:014x}'
            expected_partition = itertools.islice(
                expected_traces, min(256, item["ordinary_blocks"] - block)
            )
            trace_count += check_scalar_values(
                index, ("trace_id",), expected_partition, prefix=prefix
            )
    trace_count += check_scalar_values(index, ("trace_id",), expected_traces, prefix='"f17e')
    span_ids, span_labels = span_values(files)
    check_scalar_values(index, ("span_id",), iter(sorted(span_ids.items())))
    check_scalar_values(index, ("span",), iter(sorted(span_labels.items())))
    for item in files:
        field = item["late_field_name"]
        page = index.fields(prefix=field, limit=256)
        assert len(page.choices) == 1 and page.choices[0].path == (field,)
        value_page = index.values((field,), limit=256)
        assert len(value_page.choices) == 1 and value_page.choices[0].value == (
            f"late-file-{int(item['name'][5:7]):02d}-ordinal-"
            f"{item['ordinal_end_exclusive'] - 1:012d}"
        )
    # Exact nested and literal paths must both survive discovery.
    for path, prefix in (
        (("http.status_code",), '["http.status_code"]'),
        (("http", "status_code"), "http.status_code"),
    ):
        assert any(choice.path == path for choice in index.fields(prefix=prefix, limit=256).choices)
    return {
        "complete_field_paths": len(known),
        "complete_unique_request_values": count,
        "complete_trace_scalar_values": trace_count,
        "all_span_ids_and_labels": True,
        "all_late_keys": len(files),
    }


def check_scalar_values(index, path, expected, *, prefix='"'):
    offset = 0
    while True:
        page = index.values(path, prefix=prefix, offset=offset, limit=256)
        for choice in page.choices:
            value, occurrences = next(expected)
            assert choice.value == value and choice.occurrences == occurrences
            offset += 1
        if not page.has_more:
            break
        assert page.next_offset == offset
    assert next(expected, None) is None
    return offset


def check_filtered_tree(tree, files, seed):
    expected = filtered_tree_rows(files, seed)
    nodes = leaves = contexts = 0
    for row in tree_rows(tree):
        specification = next(expected)
        for name in ("kind", "trace_id", "span_id", "ordinal", "context_only", "match_count"):
            assert getattr(row, name) == specification[name], (name, row, specification)
        if row.kind == "span":
            assert row.lifecycle == specification["lifecycle"]
        nodes += 1
        leaves += row.kind == "record"
        contexts += row.context_only
    assert next(expected, None) is None
    return {
        "complete_nodes": nodes,
        "matching_record_leaves": leaves,
        "ancestor_context_nodes": contexts,
    }


def source_aliases(root, files):
    """Hardlinks preserve baseline storage; atomic replacement of one alias is safe."""
    root.mkdir()
    paths = []
    for item in files:
        alias = root / item["name"]
        os.link(item["path"], alias)
        paths.append(str(alias))
    return paths


def appended_refresh_source(alias, n, seed):
    """Copy only final source, then atomically replace alias; never write a hardlink."""
    path = Path(alias)
    replacement = path.with_suffix(".replacement")
    with path.open("rb", buffering=MIB) as src, replacement.open("xb", buffering=MIB) as dst:
        shutil.copyfileobj(src, dst, MIB)
        row = {
            "fixture_ordinal": n,
            "service": SERVICES[n % 8],
            "request_id": f"req-{seed:08x}-{n:012d}",
            "message": "Ticket24 explicit refresh appended record",
        }
        if cost(n) != "missing":
            row["cost_units"] = cost(n)
        dst.write((json.dumps(row, allow_nan=False) + "\n").encode("ascii"))
        dst.flush()
        os.fsync(dst.fileno())
    replacement.replace(path)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "appended_ordinal": n,
    }


def refresh_phase(session, successful_view, evidence, sampler, dataset, files, paths, seed):
    n = dataset["expected"]["records"]
    previous = session.page(0, 1)
    with Phase(evidence, sampler, "refresh:source_change_preparation"):
        changed = appended_refresh_source(paths[-1], n, seed)
    evidence.emit("refresh_source_changed", **changed, fixture_sources_preserved=True)
    job = staged = replacement = None
    committed = False
    try:
        with Phase(evidence, sampler, "refresh:capture_staging"):
            job = session.refresh(background=True, request_generation=24)
            sampler.job = job
            while not job.done:
                # Keep original owner and prior applied membership demonstrably usable.
                assert session.page(0, 1).identities[0] == previous.identities[0]
                if successful_view:
                    successful_view.page(0, 1)
                try:
                    job.wait(0.1)
                except TimeoutError:
                    pass
            replacement = job.wait()
        if replacement is None:
            assert (
                session.status.complete
                and session.page(0, 1).identities[0] == previous.identities[0]
            )
            if successful_view:
                successful_view.page(0, 1)
            evidence.emit(
                "refresh_refused_or_failed_old_owner_usable",
                status=job.status,
                resources=session.resources,
            )
            return None
        sampler.session = replacement
        with Phase(evidence, sampler, "refresh:stage_latest_explicit_filter"):
            from slogger.tools import parse_filter

            staged = settle(
                replacement.filter(parse_filter('service == "checkout" and cost_units > 0'))
            )
        with Phase(evidence, sampler, "refresh:verify_all_staged_membership"):
            check_membership(
                staged,
                expected_ordinals(
                    n + 1, lambda i: i % 8 == 0 and type(cost(i)) is int and cost(i) > 0
                ),
                files,
                paths,
            )
            restored = replacement.restore_record(session, previous.identities[0])
            assert (
                restored.identity is not None and restored.identity.owner_id == replacement.owner_id
            )
            assert replacement.page(n, 1).records[0]["fixture_ordinal"] == n
        with Phase(evidence, sampler, "refresh:atomic_owner_transfer"):
            assert job.commit() is replacement
            committed = True
            staged.close()
            staged = None
            if successful_view:
                successful_view.close()
            session.close()
        evidence.emit("refresh_committed", status=job.status, owner_id=replacement.owner_id)
        return replacement
    finally:
        if staged:
            staged.close()
        if job:
            job.close()
        sampler.session = replacement if committed else session
        sampler.job = None


async def native_phase(session, evidence, sampler, *, idle_seconds=5, navigation_keys=None):
    """Native headless interaction evidence only; no emulator/SSH assertions."""
    from slogger.tools import parse_filter
    from slogger.tools.tui.app import InvestigationApp

    app = InvestigationApp(session, preferences_path=evidence.root / "native-preferences.json")
    async with app.run_test(size=(150, 38)) as pilot:
        with Phase(evidence, sampler, "native:complete_discovery"):
            while app.discovery_job is None or not app.discovery_job.done:
                sampler.job = app.discovery_job
                await pilot.pause(0.1)
            sampler.job = None
        with Phase(evidence, sampler, "native:idle_settled"):
            await pilot.pause(idle_seconds)
        job = session.filter(parse_filter('service == "checkout" and cost_units > 0'))
        sampler.job = job
        try:
            with Phase(evidence, sampler, "native:active_navigation"):
                for key in (
                    navigation_keys
                    or ("down", "pagedown", "end", "home", "f2", "f3", "tab", "shift+tab") * 4
                ):
                    start = time.perf_counter()
                    await pilot.press(key)
                    evidence.emit(
                        "native_navigation",
                        key=key,
                        seconds=time.perf_counter() - start,
                        selected_ordinal=app.selected_ordinal,
                        job_status=job.status,
                        evidence_kind="Textual headless event-loop interaction",
                    )
                while not job.done:
                    await pilot.pause(0.1)
        finally:
            job.cancel()
            result = job.wait()
            if result:
                result.close()
            sampler.job = None


def run(args):
    import slogger
    from slogger.tools import (
        GroupBinding,
        Investigation,
        ResourceLimits,
        SearchOptions,
        SearchProjection,
        parse_filter,
    )

    checkout = args.checkout.resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain"], text=True
    ).strip()
    assert revision == args.expected_revision and not dirty, (
        "Measured checkout must be clean and pinned"
    )
    assert Path(slogger.__file__).resolve().is_relative_to(checkout), (
        "Use this checkout's installed environment; never repoint here"
    )
    assert hasattr(Investigation, "refresh") and hasattr(Investigation, "restore_record"), (
        "Integrate final ticket 22 before measuring"
    )
    process_snapshot(os.getpid())  # Refuse an actual run if worker-aware metrics are unavailable.
    manifest = json.loads(args.manifest.read_text())
    dataset = manifest["datasets"][args.dataset]
    files = manifest["files"][: dataset["source_file_count"]]
    for item in files:
        assert (
            Path(item["path"]).stat().st_size == item["bytes"]
            and digest(item["path"]) == item["sha256"]
        )
    evidence = Evidence(args.run_dir)
    managed = args.run_dir / "managed-cache"
    managed.mkdir()
    aliases = source_aliases(args.run_dir / "source-aliases", files)
    sampler = Sampler(evidence, managed)
    limits = ResourceLimits(
        disk_bytes=args.disk_gib * GIB,
        ram_cache_bytes=args.ram_mib * MIB,
        max_record_bytes=args.max_record_mib * MIB,
        working_memory_bytes=args.working_mib * MIB,
        page_memory_bytes=args.page_mib * MIB,
    )
    assert args.disk_gib == 10 or args.characterization, (
        "Non-default budgets require a separately labeled characterization run"
    )
    count, session, kept = dataset["expected"]["records"], None, None
    sampler.start()
    try:
        versions = {}
        for name in ("textual", "rich", "polars", "pytest"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "unavailable"
        evidence.emit(
            "run_identity",
            revision=revision,
            imported_package=str(slogger.__file__),
            python=sys.version,
            dependencies=versions,
            platform=platform.platform(),
            machine=platform.machine(),
            fixture_manifest_sha256=digest(args.manifest),
            fixture_identity=dataset["ordered_identity_sha256"],
            fixture_bytes=dataset["bytes"],
            fixture_records=count,
            generator_sha256=manifest["generator_sha256"],
            free_disk_bytes=shutil.disk_usage(args.run_dir).free,
            limits=limits,
            cache_condition=(
                "OS caches uncontrolled/generated warm; source hash verification w"
                "arms inputs; empty application cache only"
            ),
            characterization=args.characterization,
            runner_sha256=digest(__file__),
            machine_preparation=json.loads(
                Path(
                    "/private/tmp/slogger-tui-implementation/qualification-machine.json"
                ).read_text()
            ),
            source_aliases=aliases,
            rusage=rusage(),
        )
        with Phase(evidence, sampler, "capture:empty_application_cache"):
            started = time.perf_counter()
            session = Investigation.open(aliases, cache_dir=managed, limits=limits, background=True)
            sampler.session = session
            first = False
            while session.status.phase not in TERMINAL:
                if not first and session.status.record_count:
                    page = session.page(0, 1)
                    if page.records:
                        first = True
                        evidence.emit(
                            "first_browseable",
                            seconds=time.perf_counter() - started,
                            origin=page.origins[0],
                            status=session.status,
                        )
                session.wait(0.05)
            if not first and session.status.record_count:
                session.page(0, 1)
                evidence.emit(
                    "first_browseable", seconds=time.perf_counter() - started, status=session.status
                )
            if not session.status.complete:
                evidence.emit(
                    "capture_failure",
                    status=session.status,
                    diagnostics=session.diagnostic_page(),
                    resources=session.resources,
                )
                return
        with Phase(evidence, sampler, "capture:verify_all_records_and_origins"):
            assert session.status.record_count == count and session.status.skipped_lines == 0
            check_membership(session, expected_ordinals(count), files, aliases)
        session.close()
        sampler.session = None
        with Phase(evidence, sampler, "capture:verified_reuse"):
            session = Investigation.open(aliases, cache_dir=managed, limits=limits, background=True)
            sampler.session = session
            while not session.wait(0.1).complete and session.status.phase not in TERMINAL:
                pass
            assert session.status.complete and session.status.cache_state == "reused"
            assert session.status.record_count == count
        with Phase(evidence, sampler, "headless:idle_settled_5_seconds"):
            time.sleep(5)
        expression = parse_filter('service == "checkout" and cost_units > 0')
        with Phase(evidence, sampler, "filter:positive_checkout_execute"):
            kept = settle(session.filter(expression))
        with Phase(evidence, sampler, "filter:positive_checkout_verify_all"):
            assert (
                kept.record_count
                == dataset["expected"]["numeric_expectations"]["cost_units"][
                    "positive_checkout_scope"
                ]["selected_presence_count"]
            )
            check_membership(
                kept,
                expected_ordinals(
                    count, lambda n: n % 8 == 0 and type(cost(n)) is int and cost(n) > 0
                ),
                files,
                aliases,
            )
        for name, text, predicate in (
            ("nested_http", "http.status_code >= 500", lambda n: n % 5 == 4),
            ("literal_http", '["http.status_code"] == 503', lambda n: n % 4 == 3),
            ("missing_cost", "missing(cost_units)", lambda n: n % 10 < 2),
            ("typed_false", "mixed_value == false", lambda n: n % 8 == 3),
        ):
            measure_job(
                evidence,
                sampler,
                "filter:" + name,
                lambda text=text: session.filter(parse_filter(text)),
                lambda view, predicate=predicate: check_membership(
                    view, expected_ordinals(count, predicate), files, aliases
                ),
            )
        projection = SearchProjection(
            ("timestamp", "level", "logger", "message", "span"),
            (
                "file",
                "func",
                "line",
                "trace_id",
                "span_id",
                "parent_span_id",
                "event",
                "duration_ms",
                "error",
                "error_type",
            ),
        )
        for scope in ("full", "console"):
            options = SearchOptions(
                "LONG-MESSAGE-END-MARKER",
                scope=scope,
                case_sensitive=True,
                projection=projection if scope == "console" else None,
            )
            measure_job(
                evidence,
                sampler,
                "search:" + scope,
                lambda options=options: session.search(options),
                lambda result: check_membership(
                    result, expected_ordinals(count, lambda n: n % 4096 == 0), files, aliases
                ),
            )
        for case, text, scope in (
            ("long_marker", "LONG-MESSAGE-END-MARKER", "full"),
            ("long_marker", "LONG-MESSAGE-END-MARKER", "console"),
            ("hidden_file_full", "services/checkout/handler.py", "full"),
            ("hidden_file_console", "services/checkout/handler.py", "console"),
        ):
            options = SearchOptions(
                text,
                scope=scope,
                case_sensitive=True,
                projection=projection if scope == "console" else None,
            )
            measure_job(
                evidence,
                sampler,
                f"search:applied_scope:{case}:{scope}",
                lambda options=options: session.search(options, input_view=kept),
                lambda result, case=case: check_membership(
                    result, scoped_search_ordinals(count, case), files, aliases
                ),
            )
        measure_job(
            evidence,
            sampler,
            "discovery:complete",
            lambda: session.discover(),
            lambda index: check_discovery(index, dataset, files, manifest["seed"]),
        )
        for field in ("cost_units", "latency_ms"):
            expected = dataset["expected"]["numeric_expectations"][field]["overall"]
            measure_job(
                evidence,
                sampler,
                "numeric:" + field,
                lambda field=field: session.summarize_values((field,)),
                lambda result, expected=expected: check_single_summary(result, expected),
            )
        measure_job(
            evidence,
            sampler,
            "numeric:64_typed_groups",
            lambda: session.summarize_values(
                ("cost_units",),
                grouping=(
                    GroupBinding(("service",), "service"),
                    GroupBinding(("group_bucket",), "bucket"),
                ),
            ),
            lambda result: check_small_groups(
                result,
                dataset["expected"]["numeric_expectations"]["cost_units"][
                    "by_service_and_group_bucket"
                ],
            ),
        )
        measure_job(
            evidence,
            sampler,
            "numeric:all_unique_request_groups",
            lambda: session.summarize_values(
                ("cost_units",), grouping=(GroupBinding(("request_id",), "request"),)
            ),
            lambda result: check_high_cardinality(result, count, manifest["seed"]),
        )
        measure_job(
            evidence,
            sampler,
            "tree:complete",
            lambda: session.build_tree(),
            lambda result: check_tree(result, dataset, args.run_dir / "tree-oracle.bitmap"),
        )
        measure_job(
            evidence,
            sampler,
            "tree:applied_scope_and_ancestor_context",
            lambda: session.build_tree(input_view=kept),
            lambda result: check_filtered_tree(result, files, manifest["seed"]),
        )
        with Phase(evidence, sampler, "filter:cancellation_preserves_successful_view"):
            canceled = session.filter(parse_filter("exists(request_id)"), request_generation=25)
            while not canceled.done and canceled.status.processed_records == 0:
                time.sleep(0.02)
            canceled.cancel()
            abandoned = canceled.wait()
            if abandoned:
                abandoned.close()
            kept.page(0, 1)
            assert session.status.complete
            evidence.emit(
                "cancellation",
                status=canceled.status,
                resources=session.resources,
                completed_before_cancel=canceled.status.phase == "complete",
            )
        with Phase(evidence, sampler, "refresh:cancellation_preserves_successful_owner"):
            owner = session.owner_id
            canceled_refresh = session.refresh(background=True, request_generation=26)
            canceled_refresh.cancel()
            try:
                canceled_refresh.wait()
                assert session.status.complete and session.owner_id == owner
                kept.page(0, 1)
                evidence.emit(
                    "refresh_cancellation",
                    status=canceled_refresh.status,
                    resources=session.resources,
                )
            finally:
                canceled_refresh.close()
        if args.native:
            asyncio.run(native_phase(session, evidence, sampler))
        replacement = refresh_phase(
            session, kept, evidence, sampler, dataset, files, aliases, manifest["seed"]
        )
        if replacement is not None:
            session, kept = replacement, None
        evidence.emit(
            "run_finished",
            status=session.status,
            resources=session.resources,
            sampled_peak_process_group_rss_bytes=sampler.peak_rss,
            sampled_peak_allocated_managed_bytes=sampler.peak_disk,
            sampled_max_processes=sampler.max_processes,
            sampler_error=sampler.error,
            failed_operations=evidence.failed_operations,
            instrumentation={
                "sample_count": sampler.sample_count,
                "sampler_thread_cpu_seconds": sampler.sampler_cpu,
                "limitations": (
                    "Self/child CPU includes verification and profiling; waited-child "
                    "CPU includes repeated ps subprocesses. Sampled concurrent RSS/dis"
                    "k peaks are lower bounds."
                ),
            },
            conclusion="Measurements only; no latency threshold or RAM-default acceptance inferred",
        )
    finally:
        if kept is not None:
            kept.close()
        if session is not None:
            session.close()
        sampler.session = None
        sampler.close()
        evidence.emit(
            "cleanup_settled",
            allocated_managed_bytes=allocated(managed),
            free_disk_bytes=shutil.disk_usage(args.run_dir).free,
        )
        evidence.close()


def check_single_summary(result, expected):
    assert result.record_count == 1
    page = result.page(0, 1)
    assert page.origins == [None]
    check_summary(page.records[0], expected)
    return 1


def self_test(root):
    assert cpu_seconds("1-03:04:05.50") == 97445.5
    sample = descendants([(1, 0, 100, 2), (2, 1, 50, 1), (3, 2, 25, 0.5), (9, 0, 1000, 90)], 1)
    assert set(sample) == {1, 2, 3} and sum(item[0] for item in sample.values()) == 175 * 1024
    evidence = Evidence(root)
    managed = root / "managed"
    managed.mkdir()
    (managed / "probe").write_bytes(b"x" * 1024)
    assert allocated(managed) == (managed / "probe").stat().st_blocks * 512
    try:
        process_snapshot(os.getpid())
        availability = "available"
        snapshot = process_snapshot
    except (OSError, RuntimeError) as error:
        availability = f"unavailable in current sandbox: {error!r}"

        # Validate the sampler's mechanics against controlled process metrics.
        # This is explicitly not an actual process/RSS/CPU measurement.
        def snapshot(pid):
            return {pid: (15000000, 1.0), pid + 1: (1048576, 0.01)}

    sampler = Sampler(evidence, managed, interval=0.05, snapshot=snapshot)
    sampler.start()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; probe=bytearray(1048576); time.sleep(0.5)"]
    )
    child.wait()
    sampler.close()
    assert sampler.error is None and sampler.max_processes >= 2 and sampler.peak_rss > 0
    bitmap = DiskBitmap(root / "coverage.bitmap", 100)
    for n in range(99, -1, -1):
        bitmap.mark(n)
    assert bitmap.marked == 100
    try:
        bitmap.mark(3)
        raise AssertionError("duplicate accepted")
    except AssertionError as error:
        assert str(error) == "Duplicate tree record leaf"
    bitmap.close()

    class FakeResult:
        def __init__(self):
            self.record_count = sum(cost(n) != "missing" for n in range(96))

        def page(self, offset, limit):
            from types import SimpleNamespace

            # Tiny oracle only: no application import and no production population.
            ids = [n for n in range(96) if cost(n) != "missing"]
            records = []
            for n in ids[offset : offset + min(limit, 7)]:
                value = cost(n)
                records.append(
                    {
                        "request": f"req-{20261004:08x}-{n:012d}",
                        "count": 1,
                        "sum": 0 if value is None else value,
                        "mean": value,
                        "min": value,
                        "max": value,
                    }
                )
            return SimpleNamespace(
                records=records, origins=[None] * len(records), next_offset=offset + len(records)
            )

    fake = FakeResult()
    assert check_high_cardinality(fake, 96, 20261004) == fake.record_count
    evidence.emit(
        "self_test_passed",
        scope=(
            "stdlib sampler/allocated-disk/bitmap/tiny formula oracle only; no"
            " slogger import or benchmark"
        ),
        process_sampling_availability=availability,
        sampler_metrics="actual tiny process subtree"
        if availability == "available"
        else "controlled synthetic subtree",
    )
    evidence.close()
    return {
        "passed": True,
        "root": str(root),
        "process_sampling_availability": availability,
        "checks": [
            "CPU formats",
            "process descendants",
            "bounded sampler mechanics",
            "allocated blocks",
            "exact disk bitmap duplicate/coverage",
            "tiny streamed high-cardinality formula oracle",
        ],
    }


def qualify_admission_case(
    root,
    *,
    name,
    target_line_bytes=None,
    decoded_items=None,
    max_record_bytes=8 * MIB,
    working_memory_bytes=64 * MIB,
    page_memory_bytes=16 * MIB,
    managed_root=None,
    sampler=None,
):
    """Observe real encoded/decoded admission without silently skipping a record."""
    from slogger.tools import Investigation, ResourceLimits, SearchOptions, ToolError, parse_filter

    root = Path(root)
    source = root / (name + ".jsonl")
    candidate = root / (name + ".candidate")
    if target_line_bytes is not None:
        candidate_identity = write_encoded_probe(candidate, target_line_bytes)
    else:
        candidate_identity = write_decoded_probe(candidate, decoded_items)
    with source.open("xb") as output, candidate.open("rb") as payload:
        output.write(b'{"message":"admitted prefix"}\n')
        shutil.copyfileobj(payload, output, MIB)
        output.write(b'{"message":"after candidate"}\n')
    limits = ResourceLimits(
        max_record_bytes=max_record_bytes,
        working_memory_bytes=working_memory_bytes,
        page_memory_bytes=page_memory_bytes,
    )
    managed = Path(managed_root) if managed_root is not None else root / (name + "-managed")
    session = Investigation.open([source], storage_dir=managed, limits=limits, background=True)
    if sampler is not None:
        sampler.session = session
    session.wait()
    try:
        report: dict[str, Any] = {
            "name": name,
            "candidate": candidate_identity,
            "capture_status": plain(session.status),
            "resources": plain(session.resources),
            "limits": plain(limits),
            "diagnostic": None,
            "global_operation_error": None,
            "retained_messages": [],
            "operations_verified": [],
            "operation_refusals": [],
        }
        diagnostics = session.diagnostic_page()
        if diagnostics:
            report["diagnostic"] = plain(diagnostics[-1])
        if session.status.complete:
            report["record_count"] = session.status.record_count
            row = session.page(1, 1).records[0]
            report["candidate_message_bytes"] = len(row["message"].encode("ascii"))
            report["candidate_items"] = len(row.get("items", ()))
            assert session.page(2, 1).records[0]["message"] == "after candidate"
            del row
            cases = (
                ("filter", lambda: session.filter(parse_filter("exists(message)")), 3),
                (
                    "search",
                    lambda: session.search(
                        SearchOptions(
                            "aaaaa" if target_line_bytes is not None else "word",
                            case_sensitive=True,
                        )
                    ),
                    1,
                ),
                ("numeric", lambda: session.summarize_values(("missing_numeric_probe",)), 1),
                ("discovery", lambda: session.discover(), None),
                ("tree", lambda: session.build_tree(), None),
            )
            for label, create, expected_count in cases:
                job = create()
                if sampler is not None:
                    sampler.job = job
                result = None
                try:
                    result = settle(job)
                    if label == "discovery":
                        known = {("message",): 3}
                        if decoded_items is not None:
                            known[("items",)] = 1
                        assert {
                            item.path: item.occurrences for item in result.fields(limit=256).choices
                        } == known
                    elif label == "tree":
                        assert [
                            item.ordinal for item in tree_rows(result) if item.kind == "record"
                        ] == [0, 1, 2]
                    elif label == "numeric":
                        assert result.record_count == 1
                        assert result.page(0, 1).records[0] == {
                            "count": 0,
                            "sum": 0,
                            "mean": None,
                            "min": None,
                            "max": None,
                        }
                    else:
                        assert result.record_count == expected_count
                        assert result.page(0, 1).identities[0].ordinal == (
                            0 if label == "filter" else 1
                        )
                    report["operations_verified"].append(label)
                except (AssertionError, ToolError) as error:
                    diagnostic = getattr(job.status, "diagnostic", None)
                    if (
                        job.status.phase != "failed"
                        or diagnostic is None
                        or diagnostic.code not in {"resource_limit", "record_too_large"}
                    ):
                        raise
                    report["operation_refusals"].append(
                        {"name": label, "status": plain(job.status), "error": repr(error)}
                    )
                    assert (
                        session.status.complete
                        and session.page(0, 1).records[0]["message"] == "admitted prefix"
                    )
                    report["old_record_count_after_refusal"] = session.status.record_count
                finally:
                    if result is not None:
                        result.close()
                    if callable(getattr(job, "close", None)):
                        job.close()
                    if sampler is not None:
                        sampler.job = None

        else:
            report["retained_messages"] = [row["message"] for row in session.page(0, 1).records]
            try:
                session.filter(parse_filter("exists(message)"))
            except ToolError as error:
                report["global_operation_error"] = error.code
    finally:
        session.close()
        if sampler is not None:
            sampler.session = None
    report["closed_allocated_bytes"] = allocated(managed)
    return report


def qualify_disk_refusal(root, *, durable=False, managed_root=None, sampler=None):
    """Refuse combined replacement storage while proving the old view usable."""
    from slogger.tools import Investigation, parse_filter

    root = Path(root)
    source = root / "refusal.jsonl"
    candidate = root / "refusal.candidate"
    write_encoded_probe(candidate, 2 * MIB)
    with source.open("xb") as output, candidate.open("rb") as payload:
        output.write(b'{"message":"admitted prefix"}\n')
        shutil.copyfileobj(payload, output, MIB)
    managed = Path(managed_root) if managed_root is not None else root / "refusal-managed"
    session = Investigation.open(
        [source], **({"cache_dir": managed} if durable else {"storage_dir": managed})
    )
    view = job = None
    if sampler is not None:
        sampler.session = session
    try:
        assert session.status.complete
        view = session.filter(parse_filter("exists(message)")).wait()
        assert view is not None
        original = view.page(0, 1)
        usage = session.resources.managed_disk_bytes
        session.configure_resources(
            limits=replace(session.limits, disk_bytes=usage + max(65536, usage // 2))
        )
        with source.open("ab") as stream:
            stream.write(b'{"message":"refresh addition"}\n')
        job = session.refresh(background=True)
        if sampler is not None:
            sampler.job = job
        assert job.wait() is None
        report = {
            "durable": durable,
            "refresh_status": plain(job.status),
            "resources": plain(session.resources),
            "limits": plain(session.limits),
            "old_owner_complete": session.status.complete,
            "old_view_count": view.record_count,
            "old_first_message": view.page(0, 1).records[0]["message"],
            "old_identity_unchanged": view.page(0, 1).identities == original.identities,
        }
        job.close()
        report["reserved_after_close"] = session.resources.reserved_disk_bytes
    finally:
        if job is not None:
            job.close()
        if view is not None:
            view.close()
        session.close()
        if sampler is not None:
            sampler.session = sampler.job = None
    report["closed_allocated_bytes"] = allocated(managed)
    return report


def control_cases(root, *, revision):
    """Measure explicit real admission/refusal cases, separate from scale timings."""
    process_snapshot(os.getpid())
    evidence = Evidence(root)
    evidence.emit(
        "control_identity",
        revision=revision,
        runner_sha256=digest(__file__),
        python=sys.version,
        cache_condition="OS caches uncontrolled; newly generated task-owned control inputs",
        platform=platform.platform(),
    )
    managed = root / "managed"
    managed.mkdir()
    inputs = root / "inputs"
    inputs.mkdir()
    sampler = Sampler(evidence, managed)
    sampler.start()
    reports = []
    try:
        for name, options in (
            *(
                (f"encoded-{8 * MIB + delta}", {"target_line_bytes": 8 * MIB + delta})
                for delta in (-1, 0, 1)
            ),
            *(
                (f"decoded-{items}", {"decoded_items": items})
                for items in (150000, 200000, 300000, 1000000)
            ),
        ):
            case = inputs / name
            case.mkdir()
            with Phase(evidence, sampler, "admission:" + name):
                report = qualify_admission_case(
                    case, name=name, managed_root=managed / name, sampler=sampler, **options
                )
                evidence.emit("admission_report", **report)
                reports.append(report)
        for durable in (False, True):
            name = "refusal-durable" if durable else "refusal-temporary"
            case = inputs / name
            case.mkdir()
            with Phase(evidence, sampler, name):
                report = qualify_disk_refusal(
                    case, durable=durable, managed_root=managed / name, sampler=sampler
                )
                evidence.emit("refusal_report", **report)
                reports.append(report)
        (root / "reports.json").write_text(json.dumps(plain(reports), indent=2) + "\n")
    finally:
        sampler.close()
        evidence.emit(
            "controls_settled",
            sampled_peak_process_group_rss_bytes=sampler.peak_rss,
            sampler_error=sampler.error,
            limitations=(
                "Control phases include source generation, profiling, and full verification "
                "overhead; sampled peaks are lower bounds."
            ),
        )
        evidence.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--controls", action="store_true")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset", choices=("smoke", "1GB", "5GB"), default="1GB")
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--expected-revision")
    parser.add_argument("--disk-gib", type=int, default=10)
    parser.add_argument("--ram-mib", type=int, default=256)
    parser.add_argument("--max-record-mib", type=int, default=8)
    parser.add_argument("--working-mib", type=int, default=64)
    parser.add_argument("--page-mib", type=int, default=16)
    parser.add_argument("--characterization", default="")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if sum((args.self_test, args.measure, args.controls)) != 1:
        parser.error("Choose exactly one of --self-test / --measure / --controls")
    if args.self_test:
        print(json.dumps(self_test(args.run_dir), indent=2))
    elif args.controls:
        import slogger

        if not args.checkout or not args.expected_revision:
            parser.error("Controls require a pinned --checkout and --expected-revision")
        revision = subprocess.check_output(
            ["git", "-C", str(args.checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(args.checkout), "status", "--porcelain"], text=True
        ).strip()
        assert revision == args.expected_revision and not dirty
        assert Path(slogger.__file__).resolve().is_relative_to(args.checkout.resolve())
        control_cases(args.run_dir, revision=revision)
    else:
        if not args.checkout or not args.expected_revision:
            parser.error("Measurement requires a pinned --checkout and --expected-revision")
        run(args)


if __name__ == "__main__":
    main()
