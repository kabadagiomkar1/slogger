"""Durable cache behavior at the approved real-file Investigation seam."""

from slogger.tools import Investigation


def test_verified_reopen_preserves_dataset_occurrences_without_recapture(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text('{"n":1}\ninvalid\n{"n":2}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source, source], cache_dir=cache) as original:
        identity = original.dataset_id
        assert original.status.complete
    with Investigation.open([source, source], cache_dir=cache) as reopened:
        assert reopened.dataset_id == identity
        assert reopened.status.cache_state == "reused"
        assert reopened.status.verified_bytes == source.stat().st_size * 2
        assert reopened.page().records == [{"n": 1}, {"n": 2}] * 2
        assert [item.input_occurrence for item in reopened.page().identities] == [0, 0, 1, 1]
        assert len(reopened.diagnostics) == 2


def test_altered_manifest_cannot_fabricate_dataset_identity(tmp_path):
    import json

    source = tmp_path / "input.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache) as original:
        identity = original.dataset_id
    manifest = next((cache / "entries").glob("*/manifest.json"))
    value = json.loads(manifest.read_bytes())
    value["dataset_id"] = "fabricated"
    manifest.write_text(json.dumps(value))
    with Investigation.open([source], cache_dir=cache) as reopened:
        assert reopened.status.complete
        assert reopened.dataset_id not in (identity, "fabricated")
        assert reopened.status.cache_reason
        assert reopened.page().records == [{"n": 1}]


def test_changed_content_extent_order_and_replaced_source_are_recaptured(tmp_path):
    import os

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"n":1}\n')
    second.write_text('{"n":2}\n')
    cache = tmp_path / "cache"
    with Investigation.open([first, second], cache_dir=cache) as original:
        identity = original.dataset_id
    saved = first.stat()
    first.write_text('{"n":9}\n')
    os.utime(first, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    with Investigation.open([first, second], cache_dir=cache) as changed:
        assert changed.dataset_id != identity
        assert changed.page().records == [{"n": 9}, {"n": 2}]
        assert changed.status.cache_reason == "source content changed"
        identity = changed.dataset_id
    with first.open("a") as handle:
        handle.write('{"n":3}\n')
    with Investigation.open([first, second], cache_dir=cache) as appended:
        assert appended.dataset_id != identity
        assert appended.page().records == [{"n": 9}, {"n": 3}, {"n": 2}]
    with Investigation.open([second, first, second], cache_dir=cache) as reordered:
        assert reordered.page().records == [{"n": 2}, {"n": 9}, {"n": 3}, {"n": 2}]
        identity = reordered.dataset_id
    replacement = tmp_path / "replacement"
    replacement.write_bytes(first.read_bytes())
    replacement.replace(first)
    with Investigation.open([second, first, second], cache_dir=cache) as replaced:
        assert replaced.dataset_id != identity
        assert replaced.status.complete


def test_corrupt_index_and_incompatible_manifest_are_rejected(tmp_path):
    import json

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')
    for damage in ("records.index", "records.jsonl", "manifest.json"):
        cache = tmp_path / damage
        with Investigation.open([source], cache_dir=cache) as original:
            identity = original.dataset_id
        root = next((cache / "entries").glob("*/manifest.json")).parent
        if damage == "manifest.json":
            value = json.loads((root / damage).read_bytes())
            value["version"] = -1
            (root / damage).write_text(json.dumps(value))
        elif damage == "records.index":
            (root / damage).write_bytes(b"\0" * 64)
        else:
            (root / damage).write_text('{"n":3}\n{"n":4}\n')
        with Investigation.open([source], cache_dir=cache) as reopened:
            assert reopened.status.complete
            assert reopened.dataset_id != identity
            assert reopened.status.cache_reason
            assert reopened.page().records == [{"n": 1}, {"n": 2}]


def test_reuse_enforces_current_memory_and_browsing_limits(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "source.jsonl"
    source.write_text('{"message":"' + "x" * 200 + '"}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache):
        pass
    for limits in (
        ResourceLimits(max_record_bytes=32),
        ResourceLimits(working_memory_bytes=1024),
        ResourceLimits(page_memory_bytes=32),
    ):
        with Investigation.open([source], cache_dir=cache, limits=limits) as limited:
            assert limited.status.phase == "failed"
            assert limited.page().records == []
            assert limited.diagnostics[-1].code in ("record_too_large", "resource_limit")
    with Investigation.open(
        [source], cache_dir=cache, limits=ResourceLimits(ram_cache_bytes=16)
    ) as limited:
        assert limited.status.cache_state == "reused"
        assert limited.page().records == [{"message": "x" * 200}]
        assert limited.resources.ram_cache_bytes <= 16


def test_clear_and_expiry_protect_active_captures_and_reclaim_closed_entries(tmp_path, monkeypatch):
    import time

    from slogger.tools import CacheStore

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    owner = CacheStore(cache)
    with Investigation.open([source], cache_dir=cache) as active:
        outcome = owner.clear()
        assert outcome.protected_entries == 1
        assert outcome.removed_entries == 0
        assert active.page().records == [{"n": 1}]
    baseline = owner.usage.managed_disk_bytes
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 8 * 24 * 60 * 60)
    outcome = owner.clear(expired_only=True)
    assert outcome.removed_entries == 1
    assert outcome.reclaimed_bytes > 0
    assert owner.usage.managed_disk_bytes < baseline


def test_active_captured_and_reused_sessions_have_independent_job_storage(tmp_path):
    from slogger.tools import CacheStore

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache) as first:
        with Investigation.open([source], cache_dir=cache) as second:
            assert first.dataset_id == second.dataset_id
            one = first.storage.create_file("job.result")
            two = second.storage.create_file("job.result")
            first.storage.append(one, b"a")
            second.storage.append(two, b"b")
            assert one != two
            assert CacheStore(cache).clear().protected_entries == 2
        assert first.page().records == [{"n": 1}]
    with Investigation.open([source], cache_dir=cache) as third:
        assert third.status.cache_state == "reused"
        assert third.page().records == [{"n": 1}]


def test_competing_process_lease_and_abandoned_staging_are_safe(tmp_path):
    import subprocess
    import sys

    from slogger.tools import CacheStore

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    script = """
import sys
from slogger.tools import Investigation
session = Investigation.open([sys.argv[1]], cache_dir=sys.argv[2])
job = session.storage.create_file('abandoned.job')
session.storage.append(job, b'x' * 8192)
print('ready', flush=True)
sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(source), str(cache)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        owner = CacheStore(cache)
        assert owner.clear().protected_entries == 1
        with Investigation.open([source], cache_dir=cache) as other:
            assert other.status.cache_state == "reused"
            assert other.page().records == [{"n": 1}]
        allocated = owner.usage.disk_bytes
        process.kill()
        process.wait(timeout=5)
        recovered = CacheStore(cache)
        assert recovered.usage.disk_bytes <= allocated - 8192
        with Investigation.open([source], cache_dir=cache) as reopened:
            assert reopened.status.cache_state == "reused"
        result = owner.clear()
        assert result.removed_entries == 1
        assert result.protected_entries == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()


def test_failed_replacement_cannot_spend_active_capture_budget(tmp_path):
    from slogger.tools import CacheStore, ResourceLimits

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"n":1}\n')
    second.write_text("".join('{"message":"' + "x" * 1000 + '"}\n' for _ in range(80)))
    cache = tmp_path / "cache"
    with Investigation.open([first], cache_dir=cache) as active:
        budget = CacheStore(cache).usage.managed_disk_bytes + 32 * 1024
        with Investigation.open(
            [second], cache_dir=cache, limits=ResourceLimits(disk_bytes=budget)
        ) as replacement:
            assert replacement.status.phase == "failed"
            assert replacement.diagnostics[-1].code == "resource_limit"
            assert CacheStore(cache).usage.managed_disk_bytes <= budget
            assert active.page().records == [{"n": 1}]
            assert active.status.complete
        assert active.page().records == [{"n": 1}]


def test_sqlite_external_growth_counts_allocated_pages_and_cleans_owned_files(tmp_path):
    import sqlite3

    from slogger.tools import CacheStore

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache) as session:
        before = CacheStore(cache).usage.managed_disk_bytes
        database = session.storage.create_file("tree.sqlite")
        with session.storage.external_growth(database, byte_count=96 * 1024):
            connection = sqlite3.connect(database)
            try:
                connection.execute("PRAGMA max_page_count=24")
                connection.execute("CREATE TABLE values_(value BLOB)")
                connection.execute("INSERT INTO values_ VALUES (?)", (b"x" * 32 * 1024,))
                connection.commit()
            finally:
                connection.close()
        grown = CacheStore(cache).usage.managed_disk_bytes
        assert grown >= before + 32 * 1024
        assert session.resources.reserved_disk_bytes == 0
        session.storage.remove_file(database)
        assert CacheStore(cache).usage.managed_disk_bytes < grown


def test_recovery_reclaims_workspace_interrupted_before_catalog_registration(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest

    from slogger.tools import CacheStore

    owner = CacheStore(tmp_path / "cache")
    real_mkdir = Path.mkdir

    def interrupted_mkdir(path, *args, **kwargs):
        real_mkdir(path, *args, **kwargs)
        if path.parent == owner.entries:
            raise SystemExit("simulated process interruption after directory allocation")

    monkeypatch.setattr(Path, "mkdir", interrupted_mkdir)
    with pytest.raises(SystemExit):
        owner.new_workspace()
    result = owner.clear(expired_only=True)
    assert result.removed_entries == 1
    assert result.protected_entries == 0


def test_competing_process_reservation_blocks_growth_without_leaking_admission(tmp_path):
    import subprocess
    import sys

    import pytest

    from slogger.tools import CacheStore, ResourceLimits, ToolError

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    script = """
import sys
from slogger.tools import Investigation
with Investigation.open([sys.argv[1]], cache_dir=sys.argv[2]) as session:
    with session.storage.reserve(65536):
        print('reserved', flush=True)
        sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(source), str(cache)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "reserved"
        owner = CacheStore(cache)
        assert owner.usage.reserved_disk_bytes == 65536
        budget = owner.usage.managed_disk_bytes + 16 * 1024
        with Investigation.open(
            [source], cache_dir=cache, limits=ResourceLimits(disk_bytes=budget)
        ) as other:
            with pytest.raises(ToolError) as rejected:
                with other.storage.reserve(32 * 1024):
                    raise AssertionError("unadmitted external growth")
            assert rejected.value.code == "resource_limit"
            assert other.resources.reserved_disk_bytes == 65536
            assert other.page().records == [{"n": 1}]
        assert process.stdin is not None
        process.stdin.write("release\n")
        process.stdin.flush()
        assert process.wait(timeout=5) == 0
        assert owner.usage.reserved_disk_bytes == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()


def test_reservation_release_survives_another_opener_budget_increase(tmp_path):
    from slogger.tools import CacheStore, ResourceLimits

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"n":1}\n')
    second.write_text("".join('{"n":' + str(n) + "}\n" for n in range(12000)))
    cache = tmp_path / "cache"
    with Investigation.open([first], cache_dir=cache):
        pass
    budget = CacheStore(cache).usage.managed_disk_bytes + 16 * 1024
    with Investigation.open(
        [first], cache_dir=cache, limits=ResourceLimits(disk_bytes=budget)
    ) as lower:
        path = lower.storage.create_file("pending.job")
        writer = lower.storage.writer(path)
        try:
            with Investigation.open([second], cache_dir=cache) as higher:
                assert higher.status.complete
                assert higher.resources.managed_disk_bytes > budget
            writer.close()
            assert lower.page().records == [{"n": 1}]
        finally:
            writer.close()


def test_filter_views_close_before_durable_capture_lease_is_released(tmp_path):
    from slogger.tools import CacheStore, Field

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n{"n":2}\n')
    cache = tmp_path / "cache"
    owner = CacheStore(cache)
    for reuse in (False, True):
        session = Investigation.open([source, source], cache_dir=cache)
        try:
            if reuse:
                assert session.status.cache_state == "reused"
            view = session.filter(Field("n").eq(2)).wait(5)
            assert view is not None
            assert view.page().records == [{"n": 2}] * 4
            assert [identity.ordinal for identity in view.page().identities] == [1, 2, 4, 5]
            before = owner.usage.disk_bytes
        finally:
            session.close()
        assert owner.usage.disk_bytes <= before - 4096
        with Investigation.open([source, source], cache_dir=cache) as reopened:
            assert reopened.status.cache_state == "reused"
            assert reopened.page().records == [{"n": 1}, {"n": 2}, {"n": 2}] * 2


def test_cache_usage_exposes_catalog_journal_growth_headroom(tmp_path):
    from slogger.tools import CacheStore

    usage = CacheStore(tmp_path / "cache").usage
    assert usage.catalog_reserve_bytes >= 64 * 1024
    assert usage.managed_disk_bytes == (
        usage.disk_bytes + usage.reserved_disk_bytes + usage.catalog_reserve_bytes
    )


def test_corrupt_catalog_reports_actionable_cache_failure(tmp_path):
    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache):
        pass
    (cache / "catalog.sqlite").write_bytes(b"broken sqlite catalog")
    with pytest.raises(ToolError) as failed:
        Investigation.open([source], cache_dir=cache)
    assert failed.value.code == "cache_corrupt"
    with Investigation.open([source]) as temporary:
        assert temporary.page().records == [{"n": 1}]


def test_usage_consumes_visible_external_growth_without_double_charging_reservation(tmp_path):
    from slogger.tools import CacheStore

    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    owner = CacheStore(cache)
    with Investigation.open([source], cache_dir=cache) as session:
        path = session.storage.create_file("external.db")
        before = owner.usage.managed_disk_bytes
        with session.storage.external_growth(path, byte_count=64 * 1024):
            path.write_bytes(b"x" * 32 * 1024)
            assert owner.usage.managed_disk_bytes <= before + 64 * 1024
