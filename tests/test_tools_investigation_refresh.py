"""Atomic staged replacement and raw source-occurrence restoration."""

import json

from slogger.tools import Investigation, parse_filter


def write_records(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_refresh_stages_appends_and_restores_occurrences_after_ordinal_shift(tmp_path):
    first = write_records(tmp_path / "first.jsonl", [{"n": 0}])
    second = write_records(tmp_path / "second.jsonl", [{"n": 1}, {"n": True}])
    with Investigation.open([first, second, second]) as previous:
        selected = previous.page(3, 1).identities[0]
        view = previous.filter(parse_filter("n == 1")).wait(5)
        assert view is not None
        first.write_text('{"n":0}\n{"n":9}\n')
        refresh = previous.refresh(background=False, request_generation=4)
        replacement = refresh.wait(5)
        assert replacement is not None and refresh.status.phase == "ready"
        assert refresh.scope.owner_id == previous.owner_id
        assert refresh.scope.request_generation == 4
        assert previous.page().records == [{"n": 0}, {"n": 1}, {"n": True}, {"n": 1}, {"n": True}]
        assert view is not None
        assert view.page().records == [{"n": 1}, {"n": 1}]
        restored = replacement.restore_record(previous, selected)
        assert restored.identity is not None and restored.identity.ordinal == 4
        assert restored.identity.input_occurrence == 2
        assert restored.origin is not None and restored.origin.position == 1
        assert restored.diagnostic is None
        assert refresh.commit() is replacement
        assert replacement.page().records == [
            {"n": 0},
            {"n": 9},
            {"n": 1},
            {"n": True},
            {"n": 1},
            {"n": True},
        ]
        refresh.close()
        assert replacement.status.complete
        replacement.close()


def test_temporary_refresh_admits_old_and_replacement_together(tmp_path):
    from dataclasses import replace

    from slogger.tools import ResourceLimits

    source = write_records(
        tmp_path / "budget.jsonl", [{"message": "x" * 10000, "n": n} for n in range(20)]
    )
    with Investigation.open([source], limits=ResourceLimits(disk_bytes=512 * 1024)) as previous:
        before = previous.resources.managed_disk_bytes
        previous.configure_resources(limits=replace(previous.limits, disk_bytes=before + 64 * 1024))
        with source.open("a") as handle:
            handle.write(json.dumps({"message": "x" * 10000, "n": 20}) + "\n")
        refresh = previous.refresh(background=False)
        assert refresh.wait(5) is None
        assert refresh.status.phase == "failed"
        assert (
            refresh.status.diagnostic is not None
            and refresh.status.diagnostic.code == "resource_limit"
        )
        assert previous.status.complete and previous.page(19, 1).records[0]["n"] == 19
        assert previous.resources.managed_disk_bytes <= before + 4096


def test_settings_apply_coherently_to_live_and_staged_owners(tmp_path, monkeypatch):
    import builtins
    import threading
    from dataclasses import replace

    import pytest

    from slogger.tools import ToolError

    source = write_records(tmp_path / "settings.jsonl", [{"n": 1}])
    real_open = builtins.open
    entered, release = threading.Event(), threading.Event()

    class DelayedRead:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, *args):
            entered.set()
            assert release.wait(5)
            return self.handle.read(*args)

    def scheduled_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if str(path) == str(source) and threading.current_thread().name.startswith(
            "slogger-capture-"
        ):
            return DelayedRead(handle)
        return handle

    with Investigation.open([source]) as previous:
        monkeypatch.setattr(builtins, "open", scheduled_open)
        refresh = previous.refresh()
        try:
            assert entered.wait(5)
            while refresh.replacement is None:
                threading.Event().wait(0.001)
            replacement = refresh.replacement
            configured = replace(
                previous.limits, ram_cache_bytes=1024, disk_bytes=previous.limits.disk_bytes + 4096
            )
            previous.configure_resources(limits=configured)
            assert previous.limits == replacement.limits == configured
            with pytest.raises(ToolError) as error:
                previous.configure_resources(limits=replace(configured, working_memory_bytes=1024))
            assert error.value.code == "configuration_busy"
            assert previous.limits == replacement.limits == configured
        finally:
            release.set()
        assert refresh.wait(5) is replacement
        refresh.close()
        assert previous.status.complete


def test_refresh_cleanup_failure_is_diagnosed_and_remains_accounted(tmp_path, monkeypatch):
    import shutil

    import pytest

    from slogger.tools import ToolError

    source = write_records(tmp_path / "cleanup.jsonl", [{"message": "x" * 10000}])
    with Investigation.open([source]) as previous:
        before = previous.resources.managed_disk_bytes
        refresh = previous.refresh(background=False)
        replacement = refresh.result()
        original_rmtree = shutil.rmtree

        def deny_staging(path, *args, **kwargs):
            if path == replacement.storage.root:
                raise OSError("controlled staging deletion failure")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", deny_staging)
        with pytest.raises(ToolError) as error:
            refresh.close()
        assert error.value.code == "cleanup_failed"
        assert refresh.status.diagnostic is not None
        assert refresh.status.diagnostic.code == "cleanup_failed"
        assert previous.resources.managed_disk_bytes > before
        assert previous.page().records == [{"message": "x" * 10000}]
        monkeypatch.setattr(shutil, "rmtree", original_rmtree)
        refresh.close()
        assert previous.resources.managed_disk_bytes == before


def test_restoration_requires_raw_bytes_opening_identity_and_physical_occurrence(tmp_path):
    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "proof.jsonl"
    for change, diagnostic in (
        ("whitespace", "record_changed"),
        ("removed", "record_disappeared"),
        ("replaced", "record_changed"),
    ):
        source.write_bytes(b'{"n":1}\n')
        with Investigation.open([source]) as previous:
            identity = previous.page().identities[0]
            if change == "whitespace":
                source.write_bytes(b'{ "n": 1 }\n')  # identical decoded mapping is insufficient
            elif change == "removed":
                source.write_bytes(b"bad JSON\n")
            else:
                other = tmp_path / "other.jsonl"
                other.write_bytes(b'{"n":1}\n')
                other.replace(source)
            refresh = previous.refresh(background=False)
            replacement = refresh.result()
            restored = replacement.restore_record(previous, identity)
            assert restored.identity is None
            assert restored.diagnostic is not None
            assert restored.diagnostic.code == diagnostic
            assert restored.diagnostic.input_occurrence == 0
            assert restored.diagnostic.origin is not None
            assert restored.diagnostic.origin.position == 1
            with pytest.raises(ToolError) as error:
                replacement.restore_record(replacement, identity)
            assert error.value.code == "scope_mismatch"
            refresh.close()


def test_verified_cache_refresh_preserves_dataset_but_has_a_new_actual_owner(tmp_path):
    source = write_records(tmp_path / "cache.jsonl", [{"n": 1}])
    with Investigation.open([source], cache_dir=tmp_path / "cache") as previous:
        identity = previous.page().identities[0]
        refresh = previous.refresh(background=False)
        replacement = refresh.result()
        assert replacement.dataset_id == previous.dataset_id
        assert replacement.owner_id != previous.owner_id
        assert replacement.cache_store is previous.cache_store
        assert replacement.status.cache_state == "reused"
        restored = replacement.restore_record(previous, identity)
        assert restored.identity is not None
        assert restored.identity.owner_id == replacement.owner_id
        assert previous.cache_store is not None
        assert previous.cache_store.clear().protected_entries >= 1
        refresh.close()
        assert previous.page().records == [{"n": 1}]


def test_durable_refresh_budget_failure_preserves_prior_complete_view(tmp_path):
    from dataclasses import replace

    source = write_records(
        tmp_path / "durable.jsonl", [{"message": "x" * 10000, "n": n} for n in range(20)]
    )
    with Investigation.open([source], cache_dir=tmp_path / "cache") as previous:
        view = previous.filter(parse_filter("n == 19")).wait(5)
        before = previous.resources.managed_disk_bytes
        previous.configure_resources(limits=replace(previous.limits, disk_bytes=before + 64 * 1024))
        with source.open("a") as handle:
            handle.write('{"message":"new"}\n')
        refresh = previous.refresh(background=False)
        assert refresh.wait(5) is None
        assert refresh.status.diagnostic is not None
        assert refresh.status.diagnostic.code == "resource_limit"
        assert previous.status.complete
        assert view is not None
        assert view.page().records[0]["n"] == 19
        refresh.close()


def test_identity_lookup_is_scoped_to_actual_owner_and_view_position(tmp_path):
    source = write_records(tmp_path / "identity.jsonl", [{"n": 0}, {"n": 1}, {"n": 2}])
    with Investigation.open([source, source]) as session:
        view = session.filter(parse_filter("n == 2")).wait(5)
        assert session.identity_at(5) == session.page(5, 1).identities[0]
        assert view is not None
        assert view.identity_at(1) == session.page(5, 1).identities[0]
        assert view is not None
        assert view.identity_at(0).ordinal == 2


def test_semantic_fold_lookup_preserves_excluded_evidence_without_widening_tree(tmp_path):
    source = write_records(
        tmp_path / "fold.jsonl",
        [{"n": 1, "trace_id": "a", "span_id": "a"}, {"n": 2, "trace_id": "b", "span_id": "b"}],
    )
    with Investigation.open([source]) as previous:
        tree = previous.build_tree(background=False).result()
        trace = next(row for row in tree.children().rows if row.trace_id == "b")
        span = next(row for row in tree.children(trace.key).rows if row.kind == "span")
        identity = tree.node_identity(span.key)
        refresh = previous.refresh(background=False)
        replacement = refresh.result()
        view = replacement.filter(parse_filter("n == 1")).wait(5)
        delivered = replacement.build_tree(background=False, input_view=view).result()
        assert delivered.record_count == 1
        assert delivered.node_for_identity(identity) is None
        assert delivered.node_for_identity(identity, delivered_only=False) is not None
        assert all(row.trace_id != "b" for row in delivered.children().rows)
        refresh.close()


def test_partial_failed_cleanup_reports_remaining_observed_allocations(tmp_path, monkeypatch):
    import shutil

    import pytest

    from slogger.tools import ToolError

    source = write_records(tmp_path / "partial.jsonl", [{"message": "x" * 10000}])
    with Investigation.open([source]) as previous:
        refresh = previous.refresh(background=False)
        replacement = refresh.result()
        real_rmtree = shutil.rmtree

        def interrupted_rmtree(path, *args, **kwargs):
            if path == replacement.storage.root:
                files = [item for item in path.iterdir() if item.is_file()]
                max(files, key=lambda item: item.stat().st_size).unlink()
                raise OSError("controlled partial deletion")
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", interrupted_rmtree)
        try:
            with pytest.raises(ToolError):
                refresh.close()
            observed = 0
            for root in (previous.storage.root, replacement.storage.root):
                for path in (root, *root.rglob("*")):
                    info = path.stat()
                    observed += max(info.st_size, info.st_blocks * 512)
            assert previous.resources.managed_disk_bytes == observed
            assert previous.page().records == [{"message": "x" * 10000}]
        finally:
            monkeypatch.setattr(shutil, "rmtree", real_rmtree)
            refresh.close()


def test_original_close_owns_unpublished_refresh_even_after_caller_drops_job(tmp_path):
    import gc
    import threading

    source = write_records(tmp_path / "ownership.jsonl", [{"n": 1}])
    previous = Investigation.open([source], storage_dir=tmp_path)
    operation = previous.refresh(background=False)
    replacement = operation.result()
    worker_name = "slogger-refresh-" + operation.scope.request_id
    del operation
    for worker in threading.enumerate():
        if worker.name == worker_name:
            worker.join(5)
    gc.collect()
    try:
        previous.close()
        assert replacement.status.phase == "closed"
        assert not replacement.storage.root.exists()
    finally:
        replacement.close()
        previous.close()
