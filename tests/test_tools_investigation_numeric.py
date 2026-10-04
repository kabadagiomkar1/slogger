"""Complete numeric summaries through real captured investigation scopes."""

import json

from slogger.tools import Field, Investigation, any_of


def test_numeric_summary_counts_present_null_and_uses_nested_exact_path(tmp_path):
    source = tmp_path / "numeric.jsonl"
    rows = [{}, {"x": {"v": None}}, {"x": {"v": 0}}, {"x": {"v": 2}}, {"x.v": 99}]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source, source]) as session:
        job = session.summarize_values(("x", "v"), request_generation=5)
        result = job.wait(10)
        assert result is not None and job.status.phase == "complete"
        assert result.scope.presence == Field("x", "v").exists()
        assert result.scope.metrics == ("count", "sum", "mean", "min", "max")
        assert result.scope.request_generation == 5
        assert result.page().records == [{"count": 6, "sum": 4, "mean": 1.0, "min": 0, "max": 2}]
        assert result.page().origins == [None]
        assert session.page().records == rows + rows
        assert session.resources.reserved_disk_bytes == 0


def test_original_sequence_float_replay_crosses_spill_boundaries_and_reclaims_spool(tmp_path):
    from slogger.tools import ResourceLimits, count_rows, max_of, mean_of, min_of, scan, sum_of

    source = tmp_path / "float-replay.jsonl"
    rows = [{"v": value} for value in [1e16] + [0] * 26000 + [1.0, -1e16]]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    expected = (
        scan(source)
        .filter(Field("v").exists())
        .aggregate(
            count=count_rows(),
            sum=sum_of(Field("v")),
            mean=mean_of(Field("v")),
            min=min_of(Field("v")),
            max=max_of(Field("v")),
        )
        .execute()
        .records
    )
    with Investigation.open(
        [source],
        limits=ResourceLimits(
            ram_cache_bytes=1024,
            working_memory_bytes=65536,
            max_page_records=1,
        ),
    ) as session:
        before = session.resources.managed_disk_bytes
        job = session.summarize_values(("v",))
        result = job.wait(30)
        assert result is not None
        assert result.page(limit=1).records == expected
        assert result.page(limit=1).records[0]["sum"] == 1.0
        # Successful reduction releases its contribution spool; only one result remains.
        assert session.resources.managed_disk_bytes - before < 65536
        result.close()
        assert session.resources.managed_disk_bytes == before


def test_numeric_metric_choices_empty_input_exact_integers_and_first_ties(tmp_path):
    import math

    import pytest

    source = tmp_path / "domains.jsonl"
    rows = [{"v": 2**1200}, {"v": 1}, {"v": None}, {"v": False}, {}]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source]) as session:
        empty = session.summarize_values(("absent",)).wait(10)
        assert empty is not None
        assert empty.page().records == [
            {"count": 0, "sum": 0, "mean": None, "min": None, "max": None}
        ]
        counts = session.summarize_values(("v",), metrics=("count",)).wait(10)
        assert counts is not None and counts.page().records == [{"count": 4}]
        view = session.filter(any_of(Field("v").eq(2**1200), Field("v").eq(1))).wait(10)
        assert view is not None
        exact = session.summarize_values(("v",), metrics=("sum",), input_view=view).wait(10)
        assert exact is not None and exact.page().records == [{"sum": 2**1200 + 1}]
        assert exact.scope.input_scope == view.view_scope
        for invalid in ((), ("bogus",), ("sum", "sum")):
            with pytest.raises(ValueError, match="metrics"):
                session.summarize_values(("v",), metrics=invalid)
    source.write_text('{"v": -0.0}\n{"v": 0}')
    with Investigation.open([source]) as session:
        result = session.summarize_values(("v",), metrics=("max", "min")).wait(10)
        assert result is not None
        row = result.page().records[0]
        assert list(row) == ["max", "min"]
        assert all(
            isinstance(value, float) and math.copysign(1, value) < 0 for value in row.values()
        )


def test_numeric_domain_errors_win_before_final_overflow_and_match_reference(tmp_path):
    import pytest

    from slogger.tools import ToolError, mean_of, scan, sum_of

    source = tmp_path / "invalid.jsonl"
    for bad in (False, "7", [], {}, float("nan"), float("inf")):
        rows = [{"v": 1e308}, {"v": 1e308}, {"v": bad}]
        source.write_text("\n".join(json.dumps(row) for row in rows))
        with pytest.raises(ToolError) as reference:
            scan(source).filter(Field("v").exists()).aggregate(sum=sum_of(Field("v"))).execute()
        with Investigation.open([source]) as session:
            job = session.summarize_values(("v",), metrics=("sum", "count"))
            assert job.wait(10) is None
            assert job.diagnostics[0].code == reference.value.code == "data_incompatible"
            assert job.diagnostics[0].message == str(reference.value)
            assert session.resources.reserved_disk_bytes == 0
    for values, metric in (([1e308, 1e308, -1e308], "sum"), ([2**1200], "mean")):
        source.write_text("\n".join(json.dumps({"v": v}) for v in values))
        spec = sum_of(Field("v")) if metric == "sum" else mean_of(Field("v"))
        with pytest.raises(ToolError) as reference:
            scan(source).aggregate(result=spec).execute()
        with Investigation.open([source]) as session:
            job = session.summarize_values(("v",), metrics=(metric,))
            assert job.wait(10) is None
            assert job.diagnostics[0].message == str(reference.value)
    source.write_text("\n".join(json.dumps({"v": v}) for v in [2**53 + 1, -(2**53), 0.0]))
    with Investigation.open([source]) as session:
        result = session.summarize_values(("v",), metrics=("sum",)).wait(10)
        assert result is not None and result.page().records == [{"sum": 0.0}]


def test_cancel_during_numeric_replay_releases_borrowed_scope_and_spool(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    source = tmp_path / "cancel.jsonl"
    source.write_text("\n".join(json.dumps({"v": v}) for v in range(500)))
    entered, release = threading.Event(), threading.Event()
    original_open = Path.open

    def delayed_replay(path, mode="r", *args, **kwargs):
        if path.name.startswith("numeric-") and mode == "rb":
            entered.set()
            assert release.wait(10)
        return original_open(path, mode, *args, **kwargs)

    with Investigation.open([source]) as session:
        previous = session.summarize_values(("v",), metrics=("count",)).wait(10)
        assert previous is not None
        before = session.resources.managed_disk_bytes
        view = session.filter(Field("v").ge(250)).wait(10)
        assert view is not None
        monkeypatch.setattr(Path, "open", delayed_replay)
        job = session.summarize_values(("v",), input_view=view)
        scope = view.view_scope
        view.close()
        try:
            assert entered.wait(10)
            assert job.status.processed_records == 250
            job.cancel()
        finally:
            release.set()
        assert job.wait(10) is None and job.status.phase == "cancelled"
        assert job.scope.input_scope == scope
        assert previous.page().records == [{"count": 500}]
        assert session.resources.managed_disk_bytes == before
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(499, 1).records == [{"v": 499}]


def test_numeric_spool_resource_failure_and_cleanup_error_retain_prior_result(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from slogger.tools import ResourceLimits

    source = tmp_path / "disk.jsonl"
    source.write_text('{"v":1}\n' * 50000)
    with Investigation.open(
        [source], limits=ResourceLimits(disk_bytes=2400000, ram_cache_bytes=1024)
    ) as session:
        assert session.status.complete
        previous = session.summarize_values(("v",), metrics=("count",)).wait(10)
        assert previous is not None
        before = session.resources.managed_disk_bytes
        job = session.summarize_values(("v",))
        assert job.wait(30) is None
        assert job.diagnostics[0].code == "resource_limit"
        assert session.resources.managed_disk_bytes == before
        assert previous.page().records == [{"count": 50000}]
    source.write_text('{"v": false}')
    original_unlink = Path.unlink
    failed = False

    def unavailable_once(path, *args, **kwargs):
        nonlocal failed
        if path.name.startswith("numeric-") and not failed:
            failed = True
            raise OSError("spool cleanup unavailable")
        return original_unlink(path, *args, **kwargs)

    with Investigation.open([source]) as session:
        monkeypatch.setattr(Path, "unlink", unavailable_once)
        job = session.summarize_values(("v",))
        assert job.wait(10) is None and job.done
        assert [item.code for item in job.diagnostics] == ["data_incompatible", "cleanup_failed"]
        assert session.page().records == [{"v": False}]
        assert session.resources.reserved_disk_bytes == 0


def test_exact_integer_output_exceeding_decimal_conversion_limit_remains_pageable(tmp_path):
    source = tmp_path / "integer-output.jsonl"
    source.write_text("\n".join(json.dumps({"v": 10**4299}) for _ in range(10)))
    with Investigation.open([source]) as session:
        job = session.summarize_values(("v",), metrics=("sum",))
        result = job.wait(10)
        assert result is not None
        assert result.page().records == [{"sum": 10**4300}]
