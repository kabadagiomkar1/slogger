"""Exact selected-field counts through real captured investigation operations."""

import json
import math
from typing import Any

from slogger.tools import Field, Investigation, count_rows, scan


def test_value_counts_exclude_missing_and_preserve_typed_first_values(tmp_path):
    source = tmp_path / "counts.jsonl"
    rows = [
        {},
        {"v": None},
        {"v": False},
        {"v": -0.0},
        {"v": 0},
        {"v": 1.0},
        {"v": 1},
        {"v": True},
        {"v": "1"},
        {"v": 2**60},
        {"v": 2**60 + 1},
    ]
    source.write_text("invalid\n" + "\n".join(json.dumps(row) for row in rows))
    assert scan(source).aggregate(rows=count_rows()).execute().records == [{"rows": 11}]
    with Investigation.open([source, source]) as session:
        job = session.count_values(("v",), request_generation=7)
        result = job.wait(10)
        assert result is not None and job.status.phase == "complete"
        assert result.scope.presence == Field("v").exists()
        assert result.scope.request_generation == 7
        assert result.record_count == 8
        page = result.page()
        assert page.records == [
            {"value": None, "count": 2},
            {"value": False, "count": 2},
            {"value": -0.0, "count": 4},
            {"value": 1.0, "count": 4},
            {"value": True, "count": 2},
            {"value": "1", "count": 2},
            {"value": 2**60, "count": 2},
            {"value": 2**60 + 1, "count": 2},
        ]
        assert math.copysign(1, page.records[2]["value"]) == -1
        assert type(page.records[3]["value"]) is float
        assert page.origins == [None] * 8
        assert page.next_offset == 8 and not page.has_more


def test_nested_literal_paths_and_complete_paging_do_not_change_application_data(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "nested.jsonl"
    rows: list[dict[str, Any]] = [
        {
            "a": {"b": i},
            "a.b": "literal",
            "value": "application",
            "count": 999,
            "_id": i,
            "_aggregate_key": "real",
        }
        for i in range(12057)
    ]
    rows.append({"a": None, "a.b": "last"})
    source.write_text("\n".join(json.dumps(row) for row in rows))
    limits = ResourceLimits(
        ram_cache_bytes=1024,
        working_memory_bytes=64 * 1024,
        page_memory_bytes=4096,
        max_page_records=7,
    )
    with Investigation.open([source], limits=limits) as session:
        nested = session.count_values(("a", "b")).wait(20)
        literal = session.count_values(("a.b",)).wait(10)
        assert nested is not None and literal is not None
        assert nested.record_count == 12057
        output = []
        offset = 0
        while True:
            page = nested.page(offset, 7)
            output.extend(page.records)
            assert page.origins == [None] * len(page.records)
            if not page.has_more:
                break
            assert page.next_offset > offset
            offset = page.next_offset
        assert len(output) == 12057
        assert output[0] == {"value": 0, "count": 1}
        assert output[-1] == {"value": 12056, "count": 1}
        assert literal.page(limit=7).records == [
            {"value": "literal", "count": 12057},
            {"value": "last", "count": 1},
        ]
        assert session.page(12056, 1).records == [rows[12056]]
        assert session.resources.reserved_disk_bytes == 0


def test_explicit_view_lease_errors_and_empty_presence_keep_previous_results(tmp_path):
    import pytest

    from slogger.tools import ToolError, all_of

    source = tmp_path / "scopes.jsonl"
    rows = [{"v": "a", "n": 0}, {"n": 1}, {"v": "b", "n": 2}, {"v": [], "n": 3}]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source]) as session:
        view = session.filter(Field("n").lt(3)).wait(10)
        assert view is not None
        job = session.count_values(("v",), input_view=view, request_generation=2)
        input_scope = view.view_scope
        view.close()
        result = job.wait(10)
        assert result is not None
        assert result.scope.input_scope == input_scope
        assert result.page().records == [{"value": "a", "count": 1}, {"value": "b", "count": 1}]
        failed = session.count_values(("v",))
        assert failed.wait(10) is None
        assert failed.status.phase == "failed"
        assert failed.diagnostics[0].code == "data_incompatible"
        assert "scalar" in failed.diagnostics[0].message
        assert result.page().records == [{"value": "a", "count": 1}, {"value": "b", "count": 1}]
        empty = session.count_values(("absent",)).wait(10)
        assert empty is not None and empty.record_count == 0
        assert empty.page().records == []
        with pytest.raises(ToolError, match="closed"):
            session.count_values(("v",), input_view=view)
        other_source = tmp_path / "other.jsonl"
        other_source.write_text('{"v": 1}')
        with Investigation.open([other_source]) as other:
            other_view = other.filter(all_of()).wait(10)
            with pytest.raises(ToolError) as error:
                session.count_values(("v",), input_view=other_view)
            assert error.value.code == "scope_mismatch"
        assert session.page(3, 1).records == [rows[3]]
        assert session.resources.reserved_disk_bytes == 0
        result.close()
        with pytest.raises(ToolError) as error:
            result.page()
        assert error.value.code == "result_closed"


def test_disk_failure_cancel_and_close_release_staging_without_losing_capture(tmp_path):
    import time

    from slogger.tools import ResourceLimits

    source = tmp_path / "resources.jsonl"
    rows = [{"single": None, "many": f"value-{i:08d}"} for i in range(3000)]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    limits = ResourceLimits(disk_bytes=600000, ram_cache_bytes=1024)
    with Investigation.open([source], limits=limits) as session:
        assert session.status.complete
        previous = session.count_values(("single",)).wait(10)
        assert previous is not None
        failed = session.count_values(("many",))
        assert failed.wait(10) is None
        assert failed.diagnostics[0].code == "resource_limit"
        assert previous.page().records == [{"value": None, "count": 3000}]
        assert session.page(2999, 1).records == [rows[-1]]
        assert session.resources.reserved_disk_bytes == 0
    with Investigation.open([source]) as session:
        root = session.storage.root
        job = session.count_values(("many",))
        deadline = time.monotonic() + 5
        while job.status.processed_records == 0 and not job.done and time.monotonic() < deadline:
            time.sleep(0.005)
        job.cancel()
        assert job.wait(10) is None
        assert job.done and job.status.phase == "cancelled"
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(2999, 1).records == [rows[-1]]
        second = session.count_values(("many",))
        session.close()
        assert second.done and second.wait(0) is None
        assert not root.exists()


def test_field_binding_requires_explicit_paths_and_present_nonfinite_values_fail(tmp_path):
    import pytest

    from slogger.tools import FieldBinding

    source = tmp_path / "nonfinite.jsonl"
    source.write_text('{"v": NaN}\n{"other": [1]}')
    with Investigation.open([source]) as session:
        with pytest.raises(TypeError, match="tuple"):
            invalid_path: Any = "v"
            session.count_values(invalid_path)
        invalid_paths: Any = ((), ("",), (0,))
        for path in invalid_paths:
            with pytest.raises(ValueError):
                FieldBinding(path)
        job = session.count_values(("v",))
        assert job.wait(10) is None and job.status.phase == "failed"
        assert job.diagnostics[0].code == "data_incompatible"
        assert "finite" in job.diagnostics[0].message
        empty = session.count_values(("absent",)).wait(10)
        assert empty is not None and empty.record_count == 0
        assert session.resources.reserved_disk_bytes == 0


def test_incomplete_capture_never_produces_complete_counts(tmp_path):
    import pytest

    from slogger.tools import ToolError

    missing = tmp_path / "missing.jsonl"
    with Investigation.open([missing]) as session:
        assert not session.status.complete
        with pytest.raises(ToolError) as error:
            session.count_values(("v",))
        assert error.value.code == "dataset_incomplete"
        assert session.resources.reserved_disk_bytes == 0


def test_cleanup_filesystem_failure_is_reported_and_job_settles(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "cleanup.jsonl"
    source.write_text('{"v": []}')
    original_unlink = Path.unlink
    failed = False

    def unavailable_once(path, *args, **kwargs):
        nonlocal failed
        if path.name.startswith("aggregate-") and not failed:
            failed = True
            raise OSError("cleanup unavailable")
        return original_unlink(path, *args, **kwargs)

    with Investigation.open([source]) as session:
        monkeypatch.setattr(Path, "unlink", unavailable_once)
        job = session.count_values(("v",))
        assert job.wait(10) is None and job.done
        assert job.status.phase == "failed"
        assert [diagnostic.code for diagnostic in job.diagnostics] == [
            "data_incompatible",
            "cleanup_failed",
        ]
        assert session.page().records == [{"v": []}]
        assert session.resources.reserved_disk_bytes == 0


def test_present_collection_domain_error_precedes_aggregate_serialization_admission(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "collection.jsonl"
    source.write_text(json.dumps({"v": list(range(500))}))
    with Investigation.open([source], limits=ResourceLimits(working_memory_bytes=65536)) as session:
        assert session.status.complete
        job = session.count_values(("v",))
        assert job.wait(10) is None
        assert job.diagnostics[0].code == "data_incompatible"
        assert "scalar" in job.diagnostics[0].message
