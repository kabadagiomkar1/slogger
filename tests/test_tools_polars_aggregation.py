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
