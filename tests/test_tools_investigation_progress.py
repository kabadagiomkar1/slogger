"""Progressive capture behavior through real files and Investigation operations."""

import pytest

from slogger.tools import Investigation, ToolError


def test_background_capture_browses_prefix_and_gates_complete_operations(blocked_source):
    source, entered, release = blocked_source
    with Investigation.open([source], background=True) as session:
        try:
            assert entered.wait(5)
            assert session.status.phase == "capturing"
            assert 0 < session.status.record_count < 1000
            page = session.page(0, 2)
            assert [record["n"] for record in page.records] == [0, 1]
            assert page.complete is False
            with pytest.raises(ToolError) as failed:
                session.require_ready("future completion index")
            assert failed.value.code == "dataset_incomplete"
        finally:
            release.set()
        assert session.wait(5).complete
        assert session.status.record_count == 1000
        assert session.status.captured_bytes == source.stat().st_size
        assert session.page(999, 1).records[0]["n"] == 999
        session.require_ready("future aggregate")


def test_cancel_retains_incomplete_prefix_without_affecting_a_new_session(blocked_source, tmp_path):
    source, entered, release = blocked_source
    session = Investigation.open([source], background=True, storage_dir=tmp_path / "managed")
    try:
        assert entered.wait(5)
        prefix = session.page(0, 3)
        session.cancel()
        release.set()
        assert session.wait(5).phase == "canceled"
        assert session.page(0, 3).records == prefix.records
        assert session.page().complete is False
        assert session.diagnostics[-1].code == "capture_canceled"
        with pytest.raises(ToolError):
            session.require_ready("search")
        newer = tmp_path / "new.jsonl"
        newer.write_text('{"new":true}\n')
        with Investigation.open([newer], background=True) as replacement:
            assert replacement.wait(5).complete
            assert replacement.page().records == [{"new": True}]
            assert replacement.dataset_id != session.dataset_id
            session.close()
            assert replacement.status.complete
            assert replacement.page().records == [{"new": True}]
    finally:
        release.set()
        session.close()
    assert list((tmp_path / "managed").iterdir()) == []
    assert session.resources.managed_disk_bytes == 0


def test_partial_index_write_rolls_back_whole_unpublished_batch(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "source.jsonl"
    source.write_text("".join('{"n":' + str(n) + "}\n" for n in range(1000)))
    real_open = Path.open
    writes = 0

    class FailingIndex:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, data):
            nonlocal writes
            writes += 1
            if writes == 2:
                self.stream.write(data[:8])
                raise OSError("disk write failed after partial index growth")
            return self.stream.write(data)

    def failing_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        return FailingIndex(stream) if path.name == "records.index" and mode == "r+b" else stream

    monkeypatch.setattr(Path, "open", failing_open)
    storage = tmp_path / "managed"
    with Investigation.open([source], storage_dir=storage) as session:
        assert session.status.phase == "failed"
        assert session.status.record_count == 1
        assert session.page().records == [{"n": 0}]
        assert session.diagnostics[-1].code == "capture_failed"
        assert "partial index" in session.diagnostics[-1].message
        assert session.resources.reserved_disk_bytes == 0
    assert list(storage.iterdir()) == []


@pytest.mark.parametrize("blocked_source", ["verification"], indirect=True)
def test_all_records_remain_incomplete_until_opening_bytes_are_verified(blocked_source):
    source, entered, release = blocked_source
    with Investigation.open([source], background=True) as session:
        try:
            assert entered.wait(5)
            assert session.status.phase == "verifying"
            assert session.status.record_count == 1000
            assert session.status.verified_bytes == 0
            assert session.page(999, 1).records[0]["n"] == 999
            assert session.page(999, 1).complete is False
            with pytest.raises(ToolError):
                session.require_ready("filter")
        finally:
            release.set()
        assert session.wait(5).complete
        assert session.status.verified_bytes == source.stat().st_size


@pytest.mark.parametrize("change", ["truncate", "replace", "mutate"])
def test_observed_source_changes_fail_without_losing_captured_records(blocked_source, change):
    source, entered, release = blocked_source
    with Investigation.open([source], background=True) as session:
        try:
            assert entered.wait(5)
            if change == "truncate":
                source.write_bytes(b"")
            elif change == "replace":
                replacement = source.with_suffix(".replacement")
                replacement.write_text('{"replacement":true}\n')
                replacement.replace(source)
            else:
                with source.open("r+b") as stream:
                    stream.write(b'{"n":9')
        finally:
            release.set()
        assert session.wait(5).phase == "failed"
        assert session.page(0, 1).records[0]["n"] == 0
        assert session.diagnostics[-1].code == "source_changed"
        with pytest.raises(ToolError):
            session.require_ready("complete search")


def test_close_cancels_active_capture_and_removes_storage(blocked_source, tmp_path):
    import threading

    source, entered, release = blocked_source
    storage = tmp_path / "managed"
    session = Investigation.open([source], background=True, storage_dir=storage)
    assert entered.wait(5)
    closer = threading.Thread(target=session.close)
    closer.start()
    release.set()
    closer.join(5)
    assert not closer.is_alive()
    assert session.status.phase == "closed"
    assert list(storage.iterdir()) == []
    with pytest.raises(ToolError) as failed:
        session.page()
    assert failed.value.code == "session_closed"


def test_background_open_establishes_all_source_boundaries_before_return(tmp_path):
    source = tmp_path / "records.jsonl"
    source.write_text('{"n":1}\n')
    with Investigation.open([source] * 32, background=True) as session:
        assert len(session.sources) == 32
        assert [boundary.byte_length for boundary in session.sources] == [8] * 32
        with source.open("a") as stream:
            stream.write('{"n":2}\n')
        assert session.wait(5).complete
        assert session.status.record_count == 32
        assert session.page().records == [{"n": 1}] * 32
