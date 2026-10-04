"""Runtime preferences through real-file Investigation operations."""

from dataclasses import replace

import pytest

from slogger.tools import Investigation, ResourceLimits, ToolError


def test_runtime_limits_update_active_storage_and_evict_encoded_cache_atomically(tmp_path):
    source = tmp_path / "records.jsonl"
    source.write_text("".join('{"message":"' + "x" * 1000 + '"}\n' for _ in range(8)))
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        before = session.page().records
        assert session.resources.ram_cache_bytes > 500
        limits = replace(session.limits, ram_cache_bytes=500, disk_bytes=20 * 1024**3)
        configuration = session.configure_resources(limits=limits, cache_expiry_seconds=2)
        assert configuration.limits == session.limits == session.storage.limits == limits
        assert session.cache_store is not None
        assert session.cache_store.limits == limits
        assert session.cache_store.expiry_seconds == configuration.cache_expiry_seconds == 2
        assert configuration.usage.ram_cache_bytes <= 500
        assert session.page().records == before
        with pytest.raises(ToolError, match="disk"):
            session.configure_resources(
                limits=replace(limits, disk_bytes=1), cache_expiry_seconds=3
            )
        assert session.limits == limits
        assert session.cache_store.expiry_seconds == 2
        for field, value in (
            ("max_record_bytes", 1),
            ("working_memory_bytes", 1),
            ("page_memory_bytes", 1),
        ):
            with pytest.raises(ToolError, match="captured"):
                session.configure_resources(limits=replace(limits, **{field: value}))
            assert session.limits == limits
        for invalid in (float("nan"), float("inf"), -1):
            with pytest.raises(ValueError, match="expiry"):
                session.configure_resources(cache_expiry_seconds=invalid)
        assert session.page().records == before
    with pytest.raises(ToolError, match="closed"):
        session.configure_resources(limits=ResourceLimits())


def test_memory_decrease_is_rejected_during_capture_but_ram_change_is_live(tmp_path, monkeypatch):
    import builtins
    import threading

    source = tmp_path / "records.jsonl"
    source.write_text('{"message":"capture"}\n')
    reading = threading.Event()
    release = threading.Event()
    real_open = builtins.open

    class PausedInput:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            reading.set()
            assert release.wait(5)
            return self.stream.read(size)

    def pause_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return PausedInput(handle) if str(file) == str(source) and mode == "rb" else handle

    monkeypatch.setattr(builtins, "open", pause_open)
    with Investigation.open([source], background=True) as session:
        try:
            assert reading.wait(5)
            previous = session.limits
            with pytest.raises(ToolError, match="settled"):
                session.configure_resources(limits=replace(previous, working_memory_bytes=1024))
            assert session.limits == previous
            effective = replace(previous, ram_cache_bytes=1024)
            assert session.configure_resources(limits=effective).limits == effective
        finally:
            release.set()
        assert session.wait(5).complete
        assert session.page().records == [{"message": "capture"}]
        assert (
            session.configure_resources(
                limits=replace(effective, working_memory_bytes=10000)
            ).limits.working_memory_bytes
            == 10000
        )


def test_completed_result_handles_protect_execution_memory_until_closed(tmp_path):
    from slogger.tools import Field

    source = tmp_path / "records.jsonl"
    source.write_text('{"value":1}\n{"value":2}')
    with Investigation.open([source]) as session:
        view = session.filter(Field("value").ge(1)).wait(5)
        assert view is not None and view.page().records == [{"value": 1}, {"value": 2}]
        new = replace(session.limits, working_memory_bytes=1024 * 1024)
        with pytest.raises(ToolError, match="result handles"):
            session.configure_resources(limits=new)
        assert view.page().records == [{"value": 1}, {"value": 2}]
        view.close()
        assert session.configure_resources(limits=new).limits == new
        updated = session.filter(Field("value").eq(2)).wait(5)
        assert updated is not None
        assert updated.page().records == [{"value": 2}]
