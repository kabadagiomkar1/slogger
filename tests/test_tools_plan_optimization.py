"""Conservative rewrites verified through the public execution/explain seam."""

import pytest

from slogger.tools import Field, scan


def test_python_combines_adjacent_limits_and_keeps_original_error_indices():
    plan = scan([{"x": 3}, {"x": 1}, {"x": 2}]).limit(3).limit(2)
    explanation = plan.explain()
    assert [n["op"] for n in explanation["operations"]] == ["scan", "limit"]
    assert explanation["operations"][1]["count"] == 2
    assert "combine_adjacent_limits" in explanation["normalization"]["rewrites"]
    assert plan.execute().records == scan([{"x": 3}, {"x": 1}, {"x": 2}]).limit(2).execute().records
    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan([{"x": True}]).limit(3).limit(2).sort_by("x").execute()
    assert failure.value.extra["operation"] == 3


def test_python_combines_builtin_filters_and_normalizes_boolean_without_mutation():
    from slogger.tools import all_of, any_of, not_

    records = [{"x": None, "keep": True}, {"x": 1, "keep": True}, {"x": 2, "keep": False}, {}]
    predicate = all_of(all_of(Field("keep").eq(True)), not_(not_(any_of(Field("x").eq(1)))))
    legacy_description = predicate.explain()
    plan = scan(records).filter(predicate).filter(Field("x").exists())
    explanation = plan.explain()
    assert [n["op"] for n in explanation["operations"]] == ["scan", "filter"]
    assert set(explanation["normalization"]["rewrites"]) == {
        "normalize_boolean_composition",
        "combine_python_filters",
    }
    assert explanation["required_fields"] == [["keep"], ["x"]]
    assert plan.execute().records == [{"x": 1, "keep": True, "_id": "mem:1"}]
    assert predicate.explain() == legacy_description
    assert (
        plan.execute().records
        == scan(records)
        .filter(all_of(Field("keep").eq(True), Field("x").eq(1), Field("x").exists()))
        .execute()
        .records
    )


def test_projection_collapse_preserves_lineage_identity_and_original_validation():
    from slogger.tools import ToolError

    plan = scan([{"x": 1, "unused": {"z": None}}, {}]).select("x", "unused").select("x")
    explanation = plan.explain()
    assert [n["op"] for n in explanation["operations"]] == ["scan", "project"]
    assert explanation["required_fields"] == [["x"]]
    assert explanation["normalization"]["operation_origins"] == [[0], [1, 2]]
    assert plan.execute().records == [{"x": 1, "_id": "mem:0"}, {"_id": "mem:1"}]
    with pytest.raises(ToolError) as failure:
        scan([]).select("x").select("removed").execute()
    assert failure.value.code == "plan_invalid"
    assert failure.value.extra["operation"] == 2


def test_filters_do_not_cross_limits():
    plan = scan([{"x": 0}, {"x": 1}]).filter(Field("x").eq(0)).limit(1).filter(Field("x").eq(1))
    assert [n["op"] for n in plan.explain()["operations"]] == ["scan", "filter", "limit", "filter"]
    assert plan.execute().records == []


def test_sorting_and_grouping_keep_their_domains_after_normalization():
    from slogger.tools import ToolError, count_rows

    records = [{"x": "a"}, {"x": "a"}, {"x": "b"}]
    plan = scan(records).limit(3).limit(2).group_by("x").aggregate(n=count_rows()).sort_by("n")
    assert plan.execute().records == [{"x": "a", "n": 2}]
    assert (
        plan.execute().records
        == scan(records)
        .limit(2)
        .group_by("x")
        .aggregate(n=count_rows())
        .sort_by("n")
        .execute()
        .records
    )
    # A false constant does not let normalization erase a nonconstant dependency.
    from slogger.tools import all_of, any_of

    predicate = all_of(any_of(), Field("x").eq(1))
    assert scan([]).filter(predicate).explain()["required_fields"] == [["x"]]
    with pytest.raises(ToolError) as failure:
        scan([]).select("kept").filter(predicate).execute()
    assert failure.value.code == "plan_invalid"


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_static_normalization_does_not_consume_source(backend):
    if backend == "polars":
        pytest.importorskip("polars")
    consumed = []

    def records():
        consumed.append(True)
        yield {"x": 1}

    plan = scan(records()).select("x", "extra").select("x").limit(2).limit(5)
    explanation = plan.explain(backend=backend)
    assert consumed == []
    assert "collapse_adjacent_projections" in explanation["normalization"]["rewrites"]
    assert "combine_adjacent_limits" in explanation["normalization"]["rewrites"]
    assert plan.execute(backend=backend).records == [{"x": 1, "_id": "mem:0"}]
    assert consumed == [True]


def test_polars_preserves_filter_domains_and_limit_read_ahead():
    pytest.importorskip("polars")
    from slogger.tools import ToolError, all_of

    records = [{"keep": True, "x": 1}, {"keep": False, "x": 10**100}]
    first, second = Field("keep").eq(True), Field("x").eq(1)
    staged = scan(records).filter(first).filter(second)
    assert [n["op"] for n in staged.explain(backend="polars")["operations"]] == [
        "scan",
        "filter",
        "filter",
    ]
    assert staged.execute(backend="polars").records == [{"keep": True, "x": 1, "_id": "mem:0"}]
    with pytest.raises(ToolError) as failure:
        scan(records).filter(all_of(first, second)).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    plan = scan([{"x": i} for i in range(10)]).limit(10).limit(1)
    explanation = plan.explain(backend="polars")
    assert [n["op"] for n in explanation["operations"]] == ["scan", "limit", "limit"]
    result = plan.execute(backend="polars")
    assert result.metadata["input_rows"] == 10
    assert result.records == [{"x": 0, "_id": "mem:0"}]
    zero = scan(records).limit(10).limit(0)
    assert zero.execute(backend="polars").metadata["input_rows"] == 0


def test_zero_limits_do_not_suppress_existing_blocking_errors():
    from slogger.tools import ToolError, sum_of

    with pytest.raises(ToolError) as sorting:
        scan([{"x": True}]).limit(3).limit(2).sort_by("x").limit(0).execute()
    assert sorting.value.code == "data_incompatible"
    assert sorting.value.extra["operation"] == 3
    with pytest.raises(ToolError) as aggregation:
        scan([{"x": True}]).limit(3).limit(2).aggregate(total=sum_of(Field("x"))).limit(0).execute()
    assert aggregation.value.code == "data_incompatible"


def test_collapsed_projection_preserves_hidden_id_after_explicit_selection():
    result = scan([{"x": 1}, {}]).select("x", "_id").select("x").execute()
    assert result.schema == ("x",)
    assert result.records == [{"x": 1, "_id": "mem:0"}, {"_id": "mem:1"}]


def test_polars_boolean_normalization_does_not_erase_binding_errors():
    pytest.importorskip("polars")
    from slogger.tools import ToolError, all_of, any_of, not_

    predicate = all_of(any_of(), not_(not_(Field("x").eq(1))))
    plan = scan([{"x": 10**100}]).filter(predicate)
    assert plan.explain(backend="polars")["required_fields"] == [["x"]]
    with pytest.raises(ToolError) as failure:
        plan.execute(backend="polars")
    assert failure.value.code == "data_incompatible"
