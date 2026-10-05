"""Investigation behavior through real finite inputs and paged session operations."""

from slogger.tools import Investigation, SourceOrigin


def test_ordered_occurrences_keep_original_records_and_physical_origins(tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"_id":"application", "message":"café"}\ninvalid\n\n[]\n{"n":2}')
    second.write_text('{"n":3}\n')
    with Investigation.open([second, first, first], storage_dir=tmp_path / "storage") as session:
        assert session.status.complete
        assert session.status.record_count == 5
        assert [boundary.byte_length for boundary in session.sources] == [
            second.stat().st_size,
            first.stat().st_size,
            first.stat().st_size,
        ]
        page = session.page(1, 3)
        assert page.records == [
            {"_id": "application", "message": "café"},
            {"n": 2},
            {"_id": "application", "message": "café"},
        ]
        assert page.origins == [
            SourceOrigin(str(first), 1, "file"),
            SourceOrigin(str(first), 5, "file"),
            SourceOrigin(str(first), 1, "file"),
        ]
        assert [identity.input_occurrence for identity in page.identities] == [1, 1, 2]
        assert [identity.ordinal for identity in page.identities] == [1, 2, 3]
        assert session.status.skipped_lines == 4
        assert [(d.code, d.origin.position) for d in session.diagnostics if d.origin] == [
            ("malformed_json", 2),
            ("non_object", 4),
            ("malformed_json", 2),
            ("non_object", 4),
        ]
        with first.open("a") as handle:
            handle.write('\n{"n":99}\n')
        assert session.page(4, 3).records == [{"n": 2}]
        assert session.page(5, 3).records == []
        session.require_ready("filter")
    assert session.status.phase == "closed"
    assert list((tmp_path / "storage").iterdir()) == []


def test_memory_admission_fails_explicitly_and_pages_respect_their_budget(tmp_path):
    import pytest

    from slogger.tools import ResourceLimits, ToolError

    source = tmp_path / "records.jsonl"
    source.write_text('{"values":[' + ",".join("0" for _ in range(200)) + "]}\n")
    limits = ResourceLimits(max_record_bytes=1024, working_memory_bytes=512, page_memory_bytes=512)
    with Investigation.open([source], storage_dir=tmp_path / "storage", limits=limits) as session:
        assert session.status.phase == "failed"
        assert session.status.record_count == 0
        assert session.diagnostics[-1].code == "record_too_large"
        with pytest.raises(ToolError, match="complete"):
            session.require_ready("aggregate")

    source.write_text("".join('{"message":"' + "x" * 300 + '"}\n' for _ in range(4)))
    limits = ResourceLimits(page_memory_bytes=1000, ram_cache_bytes=500)
    with Investigation.open([source], limits=limits) as session:
        page = session.page(0, 4)
        assert page.next_offset == 1
        assert page.records == [{"message": "x" * 300}]
        assert session.page(page.next_offset, 4).next_offset == 2
        assert session.resources.ram_cache_bytes <= 500


def test_capture_uses_shared_utf8_universal_newline_decoding(tmp_path):
    from slogger.tools import scan

    source = tmp_path / "mixed.jsonl"
    source.write_bytes(b'{"n":1}\rinvalid\r\n[]\n\r{"n":2}\r{"n":3}')
    reference = scan(source).execute()
    with Investigation.open([source]) as session:
        assert session.status.complete
        assert session.page().records == reference.records == [{"n": 1}, {"n": 2}, {"n": 3}]
        assert session.page().origins == reference.origins
        assert session.status.skipped_lines == reference.metadata["skipped_lines"] == 2
    source.write_bytes(b'{"message":"\xff"}\n')
    with Investigation.open([source]) as session:
        assert session.status.phase == "failed"
        assert session.status.record_count == 0
        assert session.diagnostics[-1].code == "capture_failed"


def test_disk_exhaustion_retains_prefix_and_all_diagnostics_are_paged(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "records.jsonl"
    source.write_text("".join('{"message":"' + "x" * 1000 + '"}\n' for _ in range(50)))
    storage = tmp_path / "storage"
    with Investigation.open(
        [source], storage_dir=storage, limits=ResourceLimits(disk_bytes=16 * 1024)
    ) as session:
        assert session.status.phase == "failed"
        assert 0 < session.status.record_count < 50
        assert len(session.page().records) == session.status.record_count
        assert session.diagnostics[-1].code == "resource_limit"
        assert session.resources.managed_disk_bytes <= 16 * 1024
    assert list(storage.iterdir()) == []

    source.write_text("invalid\n" * 1000 + '{"n":1}')
    with Investigation.open([source]) as session:
        assert session.status.complete
        assert len(session.diagnostics) == 1000
        origin = session.diagnostic_page(997, 3)[-1].origin
        assert origin is not None and origin.position == 1000
        assert session.page().origins[0].position == 1001


def test_observed_prefix_mutation_plus_growth_never_becomes_ready(tmp_path, monkeypatch):
    import builtins

    source = tmp_path / "records.jsonl"
    source.write_text('{"n":1}\n')
    real_open = builtins.open
    changed = False

    class ChangingFile:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            nonlocal changed
            raw = self.stream.read(size)
            if not changed:
                changed = True
                with real_open(source, "r+b") as handle:
                    handle.write(b'{"n":2}\n{"n":3}\n')
            return raw

    def changing_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return ChangingFile(handle) if str(file) == str(source) and mode == "rb" else handle

    monkeypatch.setattr(builtins, "open", changing_open)
    with Investigation.open([source]) as session:
        assert session.status.phase == "failed"
        assert session.page().records == [{"n": 1}]
        assert session.diagnostics[-1].code == "source_changed"


def test_capture_errors_and_failed_storage_admission_clean_up_owned_files(tmp_path):
    import pytest

    from slogger.tools import ResourceLimits, ToolError

    source = tmp_path / "too_large.jsonl"
    source.write_text('{"n":' + "1" * 5000 + "}\n")
    storage = tmp_path / "storage"
    with Investigation.open([source], storage_dir=storage) as session:
        assert session.status.phase == "failed"
        assert session.diagnostics[-1].code == "capture_failed"
    assert list(storage.iterdir()) == []
    with pytest.raises(ToolError, match="budget"):
        Investigation.open([], storage_dir=storage, limits=ResourceLimits(disk_bytes=1))
    assert list(storage.iterdir()) == []
    with Investigation.open([tmp_path / "missing.jsonl"], storage_dir=storage) as session:
        assert session.status.phase == "failed"
        assert "missing.jsonl" in session.diagnostics[-1].message
    assert list(storage.iterdir()) == []


def test_oversized_line_diagnostic_identifies_its_original_physical_line(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "records.jsonl"
    source.write_text('{"n":1}\n\n{"message":"' + "x" * 100 + '"}\n')
    with Investigation.open([source], limits=ResourceLimits(max_record_bytes=32)) as session:
        assert session.status.phase == "failed"
        diagnostic = session.diagnostics[-1]
        assert diagnostic.code == "record_too_large"
        assert diagnostic.origin == SourceOrigin(str(source), 3, "file")
        assert session.page().records == [{"n": 1}]
