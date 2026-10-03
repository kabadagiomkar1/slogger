"""Aggregate execution parity through QueryPlan.execute."""

import pytest

from slogger.tools import Field, count_rows, max_of, mean_of, min_of, scan, sum_of

pytest.importorskip("polars")


def test_native_global_group_aggregates_match_python():
    rows = [{"k": "a" if i % 2 else "b", "v": i} for i in range(2100)]
    plan = (
        scan(rows)
        .group_by("k")
        .aggregate(
            n=count_rows(),
            total=sum_of(Field("v")),
            avg=mean_of(Field("v")),
            lo=min_of(Field("v")),
            hi=max_of(Field("v")),
        )
    )
    assert plan.execute(backend="polars").records == plan.execute().records


def test_native_empty_reductions_and_all_missing_numeric_values():
    for rows in ([], [{}], [{"v": None}]):
        plan = scan(rows).aggregate(
            n=count_rows(),
            total=sum_of(Field("v")),
            avg=mean_of(Field("v")),
            lo=min_of(Field("v")),
            hi=max_of(Field("v")),
        )
        assert plan.execute(backend="polars").records == plan.execute().records
    assert scan([]).group_by("k").aggregate(n=count_rows()).execute(backend="polars").records == []


def test_native_typed_groups_multiple_keys_and_post_filter():
    rows = [
        {"k": True, "b": 1},
        {"k": 1, "b": 1},
        {},
        {"k": None},
        {"k": 1.0, "b": 1},
        {"k": "1", "b": 1},
        {"k": 2**60},
        {"k": 2**60 + 1},
    ]
    # Large pure-integer keys stay exact; unsafe mixed numeric domains are rejected.
    plan = scan(rows[:-2]).group_by("k", "b").aggregate(n=count_rows()).filter(Field("n").ge(1))
    assert plan.execute(backend="polars").records == plan.execute().records
    plan = scan(rows[-2:]).group_by("k").aggregate(n=count_rows())
    assert plan.execute(backend="polars").records == plan.execute().records


def test_native_nested_reductions_late_types_and_global_mean():
    rows = [{"k": "a", "obj": {"v": 2}} for _ in range(1100)]
    rows += [{"k": "a", "obj": {"v": 8.0}}, {"k": "b", "obj": {"v": None}}]
    plan = (
        scan(rows)
        .group_by("k")
        .aggregate(avg=mean_of(Field("obj", "v")), total=sum_of(Field("obj", "v")))
    )
    actual, expected = plan.execute(backend="polars").records, plan.execute().records
    assert actual[0]["avg"] == pytest.approx(expected[0]["avg"], rel=1e-12, abs=1e-12)
    assert actual[0]["total"] == expected[0]["total"]
    assert actual[1] == expected[1]


@pytest.mark.parametrize(
    "rows",
    [
        [{"v": True}],
        [{"v": "2"}],
        [{"v": []}],
        [{"v": 2**63}],
        [{"v": 2**63 - 1}, {"v": 1}],
        [{"v": 2**53}, {"v": 1.0}],
    ],
)
def test_native_reductions_reject_unsafe_values(rows):
    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan(rows).aggregate(total=sum_of(Field("v"))).execute(backend="polars")
    assert failure.value.code == "data_incompatible"


def test_native_group_keys_reject_unsafe_mixed_numbers_and_structures():
    from slogger.tools import ToolError

    for rows in ([{"k": 2**53}, {"k": 1.0}], [{"k": []}], [{"k": {}}]):
        with pytest.raises(ToolError) as failure:
            scan(rows).group_by("k").aggregate(n=count_rows()).execute(backend="polars")
        assert failure.value.code == "data_incompatible"


def test_native_aggregate_schema_projection_and_identity():
    plan = (
        scan([{"k": "a", "v": 3}, {"k": "b", "v": 7}])
        .group_by("k")
        .aggregate(total=sum_of(Field("v")))
        .filter(Field("total").gt(4))
        .select("k", "total")
        .limit(1)
    )
    result = plan.execute(backend="polars")
    assert result.records == [{"k": "b", "total": 7}]
    assert result.schema == ("k", "total")
    assert result.metadata["preserves_record_identity"] is False
    assert plan.explain(backend="polars")["execution"]["working_memory"] == "input_proportional"


@pytest.mark.parametrize("backend", ["python", "polars"])
@pytest.mark.parametrize("reducer", [sum_of, mean_of])
def test_reductions_reject_nonfinite_results_and_intermediates(backend, reducer):
    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan([{"v": 1e308}, {"v": 1e308}]).aggregate(result=reducer(Field("v"))).execute(
            backend=backend
        )
    assert failure.value.code == "data_incompatible"


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("reducer", [sum_of, mean_of])
def test_native_float_cancellation_matches_compensated_reference(grouped, reducer):

    rows = [{"k": "a", "v": value} for value in [1e16, 1.0, -1e16]]
    plan = scan(rows)
    grouped_plan = plan.group_by("k") if grouped else plan
    plan = grouped_plan.aggregate(value=reducer(Field("v")))
    assert plan.execute(backend="polars").records == plan.execute().records


def test_native_integer_mean_uses_exact_numerator_and_extrema_allow_mixed_signs():
    rows = [{"k": "a", "v": value} for value in [10**16, 1, -(10**16)]]
    for plan in (scan(rows), scan(rows).group_by("k")):
        query_plan = plan.aggregate(avg=mean_of(Field("v")), total=sum_of(Field("v")))
        assert query_plan.execute(backend="polars").records == query_plan.execute().records
    plan = scan([{"v": v} for v in [1e16, 1.0, -1e16]]).aggregate(
        lo=min_of(Field("v")), hi=max_of(Field("v"))
    )
    assert plan.execute(backend="polars").records == [{"lo": -1e16, "hi": 1e16}]


def test_native_float_reductions_preserve_positive_and_negative_groups():
    rows = [
        {"k": "positive", "v": 2.0},
        {"k": "negative", "v": -3.0},
        {"k": "positive", "v": 4.0},
        {"k": "negative", "v": -5.0},
    ]
    plan = scan(rows).group_by("k").aggregate(total=sum_of(Field("v")), avg=mean_of(Field("v")))
    assert plan.execute(backend="polars").records == plan.execute().records


def test_repeated_fraction_reductions_match_compensated_reference():
    plan = scan([{"v": 0.1} for _ in range(100_000)]).aggregate(
        total=sum_of(Field("v")), avg=mean_of(Field("v"))
    )
    expected = [{"total": 10000.0, "avg": 0.1}]
    for backend in ("python", "polars"):
        result = plan.execute(backend=backend).records
        assert result[0]["total"] == pytest.approx(expected[0]["total"], rel=1e-12, abs=1e-12)
        assert result[0]["avg"] == pytest.approx(expected[0]["avg"], rel=1e-12, abs=1e-12)


def test_native_grouped_million_fraction_sum_has_no_accumulation_drift():
    plan = (
        scan([{"k": "a", "v": 0.1} for _ in range(1_000_000)])
        .group_by("k")
        .aggregate(total=sum_of(Field("v")), avg=mean_of(Field("v")))
    )
    result = plan.execute(backend="polars").records[0]
    assert result["total"] == pytest.approx(100000.0, rel=1e-12, abs=1e-12)
    assert result["avg"] == pytest.approx(0.1, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("values", [[1e-300], [1e20, 1e-20]])
def test_native_fixed_point_float_range_is_explicit_and_extrema_stay_supported(values):
    from slogger.tools import ToolError

    rows = [{"v": value} for value in values]
    with pytest.raises(ToolError) as failure:
        scan(rows).aggregate(total=sum_of(Field("v"))).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert "exact native lane range" in failure.value.message
    plan = scan(rows).aggregate(lo=min_of(Field("v")), hi=max_of(Field("v")))
    assert plan.execute(backend="polars").records == plan.execute().records
