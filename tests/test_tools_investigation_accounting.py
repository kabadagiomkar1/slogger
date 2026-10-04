"""Real eager group/tree behavior and durable accounting amortization."""

import json
import sys
import threading

import pytest

from slogger.tools import AggregateResult, GroupBinding, Investigation
from slogger.tools.investigation.cache import CacheStore
from slogger.tools.investigation.tree import TraceTree, TreeJob


def sources(tmp_path):
    paths = (tmp_path / "first.jsonl", tmp_path / "second.jsonl")
    with paths[0].open("w") as first, paths[1].open("w") as second:
        for n in range(64):
            phase = n % 4
            row = {
                "request_id": f"req-{n:03}",
                "value": n / 4,
                "trace_id": f"trace-{n // 4:02}",
                "span_id": "root" if phase in (0, 3) else "child",
                "event": "span.start" if phase in (0, 1) else "span.end",
                "timestamp": f"2026-10-04T00:00:00.{n:03}Z",
            }
            if phase in (1, 2):
                row["parent_span_id"] = "root"
            if phase in (2, 3):
                row["duration_ms"] = 1 if phase == 2 else 3
                row["status"] = "ok"
            (first if n < 33 else second).write(json.dumps(row) + "\n")
    return paths


@pytest.mark.parametrize("operation", ["aggregate", "tree"])
def test_eager_sql_reads_remain_exact_with_amortized_durable_admission(tmp_path, operation):
    paths = sources(tmp_path)
    with Investigation.open(paths, cache_dir=tmp_path / "cache") as session:
        updates = 0
        update_code = CacheStore.update.__code__
        previous, previous_threads = sys.getprofile(), threading.getprofile()

        def profile(frame, event, arg):
            nonlocal updates
            if event == "call" and frame.f_code is update_code:
                updates += 1

        sys.setprofile(profile)
        threading.setprofile(profile)
        try:
            if operation == "aggregate":
                job = session.summarize_values(
                    ("value",), grouping=(GroupBinding(("request_id",), "request"),)
                )
                result = job.wait(10)
                assert result is not None and job.status.phase == "complete"
            else:
                job = session.build_tree(background=False)
                assert job.status.phase == "complete"
                result = job.result()
        finally:
            sys.setprofile(previous)
            threading.setprofile(previous_threads)
        try:
            if operation == "aggregate":
                assert isinstance(result, AggregateResult)
                page = result.page(0, 100)
                assert not page.has_more and result.record_count == 64
                assert page.records == [
                    {
                        "request": f"req-{n:03}",
                        "count": 1,
                        "sum": n / 4,
                        "mean": n / 4,
                        "min": n / 4,
                        "max": n / 4,
                    }
                    for n in range(64)
                ]
            else:
                assert isinstance(result, TraceTree)
                roots = result.children(limit=100).rows
                assert [row.trace_id for row in roots] == [f"trace-{n:02}" for n in range(16)]
                for n, root in enumerate(roots):
                    span = result.children(root.key).rows[0]
                    assert span.span_id == "root" and span.lifecycle == "complete"
                    children = result.children(span.key).rows
                    child = children[1]
                    assert child.span_id == "child" and child.lifecycle == "complete"
                    assert [row.ordinal for row in result.children(child.key).rows] == [
                        n * 4 + 1,
                        n * 4 + 2,
                    ]
                    assert [row.ordinal for row in children if row.kind == "record"] == [
                        n * 4,
                        n * 4 + 3,
                    ]
                assert result.record_count == 64
            # Algorithmic accounting guard only; this is not a latency requirement.
            assert updates <= 160
        finally:
            result.close()
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(32, 1).origins[0].source == str(paths[0])
        assert session.page(33, 1).origins[0].source == str(paths[1])


@pytest.mark.parametrize("operation", ["aggregate", "tree"])
def test_outstanding_engine_grant_keeps_browsing_configuration_and_crossprocess_admission(
    tmp_path, monkeypatch, operation
):
    import subprocess
    from dataclasses import replace

    from slogger.tools import ToolError

    paths = sources(tmp_path)
    cache = tmp_path / "cache"
    with Investigation.open(paths, cache_dir=cache) as session:
        baseline = session.resources.managed_disk_bytes
        read = session.page
        entered, release = threading.Event(), threading.Event()

        def scheduled_page(offset=0, limit=100):
            page = read(offset, limit)
            if offset == 1 and threading.current_thread() is not threading.main_thread():
                entered.set()
                assert release.wait(30)
            return page

        monkeypatch.setattr(session, "page", scheduled_page)
        job = (
            session.count_values(("request_id",))
            if operation == "aggregate"
            else session.build_tree()
        )
        try:
            assert entered.wait(5)
            assert session.resources.reserved_disk_bytes > 0
            assert session.page(0, 1).records[0]["request_id"] == "req-000"
            configured = session.configure_resources(
                limits=replace(session.limits, ram_cache_bytes=1024)
            )
            assert configured.limits.ram_cache_bytes == 1024
            with pytest.raises(ToolError) as failure:
                session.configure_resources(
                    limits=replace(
                        session.limits, disk_bytes=session.resources.managed_disk_bytes - 1
                    )
                )
            assert failure.value.code == "resource_limit"
            script = """
import sys
from slogger.tools import Investigation, ResourceLimits, ToolError
try:
    with Investigation.open(sys.argv[1:3], cache_dir=sys.argv[3],
                            limits=ResourceLimits(disk_bytes=int(sys.argv[4]))):
        raise AssertionError('unadmitted competing owner')
except ToolError as error:
    assert error.code == 'resource_limit', error
    print(error.code)
"""
            other = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    *(str(path) for path in paths),
                    str(cache),
                    str(baseline + 1024**2),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            assert other.stdout.strip() == "resource_limit"
            job.cancel()
            release.set()
            job.wait(10)
            assert job.done and job.status.phase in ("cancelled", "canceled")
            assert session.resources.reserved_disk_bytes == 0
            assert session.page(0, 1).records[0]["request_id"] == "req-000"
        finally:
            release.set()
            job.cancel()
            job.wait(10)
            if isinstance(job, TreeJob):
                job.close()


@pytest.mark.parametrize("operation", ["aggregate", "tree"])
@pytest.mark.parametrize("durable", [False, True])
def test_prewrite_window_downshift_admits_complete_results_under_tight_budget(
    tmp_path, operation, durable
):
    from dataclasses import replace

    options = {"cache_dir": tmp_path / "cache"} if durable else {"storage_dir": tmp_path}
    with Investigation.open(sources(tmp_path), **options) as session:
        headroom = (1 if operation == "aggregate" else 8) * 1024**2
        session.configure_resources(
            limits=replace(
                session.limits, disk_bytes=session.resources.managed_disk_bytes + headroom
            )
        )
        if operation == "aggregate":
            job = session.summarize_values(
                ("value",), grouping=(GroupBinding(("request_id",), "request"),)
            )
            result = job.wait(10)
            assert result is not None, job.diagnostics
            assert result.record_count == 64
            assert [row["sum"] for row in result.page().records] == [n / 4 for n in range(64)]
            result.close()
        else:
            job = session.build_tree(background=False)
            assert job.status.phase == "complete"
            assert job.result().record_count == 64
            assert len(job.result().children().rows) == 16
            job.close()
        assert session.resources.reserved_disk_bytes == 0
        assert session.resources.managed_disk_bytes <= session.limits.disk_bytes
        assert session.page(63, 1).records[0]["request_id"] == "req-063"


def test_numeric_spool_unchanged_grants_do_not_republish_each_contribution(tmp_path):
    with Investigation.open(sources(tmp_path), cache_dir=tmp_path / "cache") as session:
        updates = 0
        update_code = CacheStore.update.__code__
        previous = threading.getprofile()

        def profile(frame, event, arg):
            nonlocal updates
            if event == "call" and frame.f_code is update_code:
                updates += 1

        threading.setprofile(profile)
        try:
            result = session.summarize_values(("value",)).wait(10)
        finally:
            threading.setprofile(previous)
        assert result is not None
        try:
            assert result.page().records == [
                {"count": 64, "sum": 504.0, "mean": 7.875, "min": 0.0, "max": 15.75}
            ]
            assert updates <= 32  # unchanged grants, not a wall-clock target
        finally:
            result.close()
        assert session.resources.reserved_disk_bytes == 0


@pytest.mark.parametrize("durable", [False, True])
def test_real_sqlite_full_protects_active_paths_and_reconciles_owned_sidecars(tmp_path, durable):
    import sqlite3
    from pathlib import Path

    from slogger.tools import ToolError

    options = {"cache_dir": tmp_path / "cache"} if durable else {"storage_dir": tmp_path}
    with Investigation.open(sources(tmp_path), **options) as session:
        storage = session.storage
        database = storage.create_file("ceiling.sqlite")
        sidecar = Path(str(database) + "-journal")
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA page_size=4096")
            connection.execute("PRAGMA journal_mode=OFF")
            with storage.sqlite_growth(database, 96 * 1024):
                connection.execute("PRAGMA max_page_count=22")
                connection.execute("CREATE TABLE payload(value BLOB)")
                with pytest.raises(ToolError) as protected:
                    storage.remove_file(database)
                assert protected.value.code == "storage_busy"
                with pytest.raises(ToolError) as protected:
                    storage.close()
                assert protected.value.code == "storage_busy"
                with pytest.raises(ValueError):
                    storage.writer(database)
                with pytest.raises(sqlite3.DatabaseError) as full:
                    for _ in range(20):
                        connection.execute("INSERT INTO payload VALUES(zeroblob(32768))")
                assert "full" in str(full.value)
                assert database.stat().st_size <= 22 * 4096
                connection.close()
                # A retained owned sidecar is reconciled after engine settlement.
                # Its allocation plus the main-file ceiling fits the admitted grant.
                sidecar.write_bytes(b"e" * 8192)
        finally:
            connection.close()
        usage = session.resources
        assert usage.reserved_disk_bytes == 0
        assert usage.disk_bytes >= sum(
            max(path.stat().st_size, path.stat().st_blocks * 512) for path in (database, sidecar)
        )
        assert session.status.complete and session.page(0, 1).records[0]["request_id"] == "req-000"
        storage.remove_file(database)
        storage.remove_file(sidecar)
