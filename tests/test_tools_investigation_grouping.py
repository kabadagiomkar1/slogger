"""Exact grouped summaries through real captured investigation scopes."""

import json
from typing import Any

from slogger.tools import Field, GroupBinding, Investigation


def test_grouped_numeric_nested_literal_and_secondary_missing_preserve_originals(tmp_path):
    source = tmp_path / "groups.jsonl"
    rows = [
        {"selected": {"v": 2}, "region": {"name": "west"}, "region.name": False},
        {"selected": {"v": None}, "region": {"name": "west"}, "region.name": False},
        {"selected": {"v": 4}, "region": {"name": "west"}, "region.name": 0},
        {"selected": {"v": 6}, "region.name": None},
        {"selected": {"v": 8}},
        {"region": [], "region.name": {}},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    grouping = (
        GroupBinding(("region", "name"), "nested"),
        GroupBinding(("region.name",), "literal"),
    )
    with Investigation.open([source, source]) as session:
        job = session.summarize_values(("selected", "v"), grouping=grouping, request_generation=9)
        result = job.wait(10)
        assert result is not None and job.status.phase == "complete"
        assert result.scope.grouping == grouping
        assert result.scope.presence == Field("selected", "v").exists()
        assert result.scope.request_generation == 9
        assert result.record_count == job.status.result_records == 4
        assert result.page().records == [
            {
                "nested": "west",
                "literal": False,
                "count": 4,
                "sum": 4,
                "mean": 2.0,
                "min": 2,
                "max": 2,
            },
            {"nested": "west", "literal": 0, "count": 2, "sum": 8, "mean": 4.0, "min": 4, "max": 4},
            {"literal": None, "count": 2, "sum": 12, "mean": 6.0, "min": 6, "max": 6},
            {"count": 2, "sum": 16, "mean": 8.0, "min": 8, "max": 8},
        ]
        assert result.page().origins == [None] * 4
        assert session.page().records == rows + rows
        assert session.resources.reserved_disk_bytes == 0


def test_grouped_value_counts_typed_identity_first_representatives_and_complete_pages(tmp_path):
    import math

    from slogger.tools import ResourceLimits

    source = tmp_path / "typed-groups.jsonl"
    keys = [None, False, -0.0, 0, 1.0, 1, True, "1", 2**60, 2**60 + 1]
    rows = [{"v": "one", "g": key} for key in keys]
    rows += [{"v": "one"}, {"v": None}, {"v": False}, {"v": 0}, {"v": 1}]
    rows += [{"v": "one", "g": "late-" + str(i)} for i in range(12057)]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    grouping = (GroupBinding(("g",), "group"),)
    with Investigation.open(
        [source],
        limits=ResourceLimits(
            working_memory_bytes=65536,
            ram_cache_bytes=1024,
            max_page_records=3,
            page_memory_bytes=4096,
        ),
    ) as session:
        before = session.resources.managed_disk_bytes
        job = session.count_values(("v",), grouping=grouping)
        result = job.wait(30)
        assert result is not None and result.record_count == 12070
        output = []
        offset = 0
        while True:
            page = result.page(offset, 3)
            output.extend(page.records)
            assert page.origins == [None] * len(page.records)
            if not page.has_more:
                break
            assert page.next_offset > offset
            offset = page.next_offset
        assert output[:8] == [
            {"group": None, "value": "one", "count": 1},
            {"group": False, "value": "one", "count": 1},
            {"group": -0.0, "value": "one", "count": 2},
            {"group": 1.0, "value": "one", "count": 2},
            {"group": True, "value": "one", "count": 1},
            {"group": "1", "value": "one", "count": 1},
            {"group": 2**60, "value": "one", "count": 1},
            {"group": 2**60 + 1, "value": "one", "count": 1},
        ]
        assert math.copysign(1, output[2]["group"]) == -1
        assert type(output[3]["group"]) is float
        assert output[8:13] == [
            {"value": "one", "count": 1},
            {"value": None, "count": 1},
            {"value": False, "count": 1},
            {"value": 0, "count": 1},
            {"value": 1, "count": 1},
        ]
        assert output[-1] == {"group": "late-12056", "value": "one", "count": 1}
        result.close()
        assert session.resources.managed_disk_bytes == before


def test_grouped_numeric_replay_matches_reference_with_many_interleaved_groups(tmp_path):
    from slogger.tools import ResourceLimits, count_rows, max_of, min_of, scan, sum_of

    source = tmp_path / "replay-groups.jsonl"
    rows = [{"g": "float", "v": 1e16}]
    for i in range(26000):
        rows.append({"g": "float", "v": 0})
        if i < 257:
            rows.append({"g": i, "v": 2**1200 + i})
    rows += [{"g": "float", "v": 1.0}, {"g": "float", "v": -1e16}]
    rows += [{"g": "round", "v": v} for v in (2**53 + 1, -(2**53), 0.0)]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    expected = (
        scan(source)
        .filter(Field("v").exists())
        .group_by("g")
        .aggregate(
            count=count_rows(),
            sum=sum_of(Field("v")),
            min=min_of(Field("v")),
            max=max_of(Field("v")),
        )
        .execute()
        .records
    )
    with Investigation.open(
        [source],
        limits=ResourceLimits(working_memory_bytes=65536, ram_cache_bytes=1024, max_page_records=3),
    ) as session:
        before = session.resources.managed_disk_bytes
        result = session.summarize_values(
            ("v",), grouping=(GroupBinding(("g",)),), metrics=("count", "sum", "min", "max")
        ).wait(40)
        assert result is not None and result.record_count == len(expected) == 259
        output = []
        for offset in range(0, result.record_count, 3):
            output.extend(result.page(offset, 3).records)
        assert output == expected
        assert output[0]["sum"] == 1.0 and output[-1]["sum"] == 0.0
        result.close()
        assert session.resources.managed_disk_bytes == before
        # Group means count numeric values, while null contributes only to row count.
    source.write_text('{"g":"x","v":2}\n{"g":"x","v":null}\n{"g":"x","v":6}')
    with Investigation.open([source]) as session:
        result = session.summarize_values(("v",), grouping=(GroupBinding(("g",)),)).wait(10)
        assert result is not None
        assert result.page().records == [
            {"g": "x", "count": 3, "sum": 8, "mean": 4.0, "min": 2, "max": 6}
        ]


def test_group_bindings_reject_ambiguous_names_and_keep_empty_grouped_scope_empty(tmp_path):
    import pytest

    source = tmp_path / "names.jsonl"
    source.write_text('{"v":1,"count":2,"value":3}')
    with Investigation.open([source]) as session:
        for grouping in (
            (GroupBinding(("count",)),),
            (GroupBinding(("x",), "same"), GroupBinding(("y",), "same")),
            (GroupBinding(("x",), "a"), GroupBinding(("x",), "b")),
        ):
            with pytest.raises(ValueError, match="Grouping"):
                session.summarize_values(("v",), grouping=grouping)
        with pytest.raises(ValueError, match="Grouping"):
            session.count_values(("v",), grouping=(GroupBinding(("value",)),))
        with pytest.raises(TypeError, match="grouping"):
            invalid: Any = [GroupBinding(("count",), "group")]
            session.count_values(("v",), grouping=invalid)
        for request in (session.count_values, session.summarize_values):
            result = request(("absent",), grouping=(GroupBinding(("count",), "group"),)).wait(10)
            assert result is not None and result.record_count == 0 and result.page().records == []


def test_group_domain_validation_and_finalization_errors_match_reference_order(tmp_path):
    import pytest

    from slogger.tools import ToolError, mean_of, scan, sum_of

    source = tmp_path / "group-errors.jsonl"
    cases = [
        ([{"g": "first", "v": 1e308}, {"g": "first", "v": 1e308}, {"g": [], "v": False}], ("sum",)),
        (
            [{"g": "first", "v": 1e308}, {"g": "first", "v": 1e308}, {"g": "later", "v": False}],
            ("sum",),
        ),
        (
            [{"g": "first", "v": 2**1200}, {"g": "later", "v": 1e308}, {"g": "later", "v": 1e308}],
            ("mean", "sum"),
        ),
    ]
    for rows, metrics in cases:
        source.write_text("\n".join(json.dumps(row) for row in rows))
        specs = {
            metric: mean_of(Field("v")) if metric == "mean" else sum_of(Field("v"))
            for metric in metrics
        }
        with pytest.raises(ToolError) as reference:
            scan(source).filter(Field("v").exists()).group_by("g").aggregate(**specs).execute()
        with Investigation.open([source]) as session:
            before = session.resources.managed_disk_bytes
            job = session.summarize_values(
                ("v",), grouping=(GroupBinding(("g",)),), metrics=metrics
            )
            assert job.wait(10) is None and job.status.phase == "failed"
            assert job.diagnostics[0].code == reference.value.code == "data_incompatible"
            assert job.diagnostics[0].message == str(reference.value)
            assert session.resources.managed_disk_bytes == before
            assert session.resources.reserved_disk_bytes == 0
    source.write_text('{"g":null,"v":false}\n{"g":null,"v":"7"}\n{"g":[]}')
    with Investigation.open([source]) as session:
        result = session.summarize_values(
            ("v",), grouping=(GroupBinding(("g",)),), metrics=("count",)
        ).wait(10)
        assert result is not None and result.page().records == [{"g": None, "count": 2}]


def test_grouped_replay_cancellation_releases_index_spool_and_borrowed_scope(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    source = tmp_path / "group-cancel.jsonl"
    source.write_text("\n".join(json.dumps({"g": i % 5, "v": i}) for i in range(500)))
    entered, release = threading.Event(), threading.Event()
    original_open = Path.open

    def delayed_replay(path, mode="r", *args, **kwargs):
        if path.name.startswith("numeric-") and mode == "rb":
            entered.set()
            assert release.wait(10)
        return original_open(path, mode, *args, **kwargs)

    with Investigation.open([source]) as session:
        previous = session.count_values(("g",)).wait(10)
        assert previous is not None
        before = session.resources.managed_disk_bytes
        view = session.filter(Field("v").ge(250)).wait(10)
        assert view is not None
        scope = view.view_scope
        monkeypatch.setattr(Path, "open", delayed_replay)
        job = session.summarize_values(("v",), grouping=(GroupBinding(("g",)),), input_view=view)
        view.close()
        try:
            assert entered.wait(10)
            assert job.status.processed_records == 250
            job.cancel()
        finally:
            release.set()
        assert job.wait(10) is None and job.status.phase == "cancelled"
        assert job.scope.input_scope == scope
        assert previous.page().records == [{"value": i, "count": 100} for i in range(5)]
        assert session.resources.managed_disk_bytes == before
        assert session.resources.reserved_disk_bytes == 0


def test_grouped_disk_admission_and_creation_cleanup_preserve_existing_data(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest

    from slogger.tools import ResourceLimits

    source = tmp_path / "group-disk.jsonl"
    source.write_text("\n".join(json.dumps({"v": 1, "g": i}) for i in range(2000)))
    with Investigation.open(
        [source], limits=ResourceLimits(disk_bytes=450000, ram_cache_bytes=1024)
    ) as session:
        assert session.status.complete
        previous = session.summarize_values(("v",), metrics=("count",)).wait(10)
        assert previous is not None
        before = session.resources.managed_disk_bytes
        job = session.summarize_values(("v",), grouping=(GroupBinding(("g",)),))
        assert job.wait(20) is None and job.diagnostics[0].code == "resource_limit"
        assert session.resources.managed_disk_bytes == before
        assert previous.page().records == [{"count": 2000}]
    source.write_text('{"g":"x","v":1}')
    original_touch = Path.touch

    def unavailable_index(path, *args, **kwargs):
        if path.name.startswith("contributions-"):
            raise OSError("group index unavailable")
        return original_touch(path, *args, **kwargs)

    with Investigation.open([source]) as session:
        view = session.filter(Field("v").exists()).wait(10)
        assert view is not None
        before = session.resources.managed_disk_bytes
        with monkeypatch.context() as faults:
            faults.setattr(Path, "touch", unavailable_index)
            with pytest.raises(OSError, match="group index unavailable"):
                session.summarize_values(("v",), grouping=(GroupBinding(("g",)),), input_view=view)
        assert session.resources.managed_disk_bytes == before
        view.close()
        assert session.resources.managed_disk_bytes < before
        assert session.page().records == [{"g": "x", "v": 1}]
