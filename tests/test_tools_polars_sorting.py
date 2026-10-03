"""Global native sorting through the public execution seam."""

import pytest

from slogger.tools import scan

pytest.importorskip("polars")


def test_native_sort_is_global_across_batches_with_original_source_ties():
    records = [{"x": i % 3, "message": str(i)} for i in range(2200)]
    plan = scan(records).sort_by("x", descending=True).limit(4).select("message")
    assert plan.execute(backend="polars").records == [
        {"message": "2", "_id": "mem:2"},
        {"message": "5", "_id": "mem:5"},
        {"message": "8", "_id": "mem:8"},
        {"message": "11", "_id": "mem:11"},
    ]
    assert plan.execute(backend="polars").records == plan.execute().records


@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize("missing", ["first", "last"])
@pytest.mark.parametrize("nulls", ["first", "last"])
def test_missing_null_placement_and_direction_match_reference(descending, missing, nulls):
    records = [
        {"name": "m0"},
        {"name": "n0", "x": None},
        {"name": "low", "x": 1},
        {"name": "high", "x": 2.0},
        {"name": "m1"},
        {"name": "n1", "x": None},
    ]
    plan = scan(records).sort_by("x", descending=descending, missing=missing, nulls=nulls)
    result = plan.execute(backend="polars")
    assert result.records == plan.execute().records
    assert result.metadata["preserves_record_identity"] is True
    assert result.metadata["source_cursor_eligible"] is False


def test_limit_order_and_repeated_sort_ties_use_original_ordinals():
    records = [{"x": 3, "tie": 1}, {"x": 2, "tie": 1}, {"x": 1, "tie": 1}]
    parent = scan(records)
    assert [r["x"] for r in parent.sort_by("x").limit(2).execute(backend="polars").records] == [
        1,
        2,
    ]
    assert [r["x"] for r in parent.limit(2).sort_by("x").execute(backend="polars").records] == [
        2,
        3,
    ]
    for descending in [False, True]:
        plan = parent.sort_by("x").sort_by("tie", descending=descending)
        assert [r["x"] for r in plan.execute(backend="polars").records] == [3, 2, 1]


def test_unicode_strings_large_integer_only_and_empty_inputs_sort_exactly():
    strings = [{"x": "λ"}, {"x": "a"}, {"x": "🙂"}, {"x": "A"}]
    assert [r["x"] for r in scan(strings).sort_by("x").execute(backend="polars").records] == [
        "A",
        "a",
        "λ",
        "🙂",
    ]
    records = [{"x": 2**53 + 1}, {"x": 2**53}, {"x": -(2**63)}, {"x": 2**63 - 1}]
    assert [r["x"] for r in scan(records).sort_by("x").execute(backend="polars").records] == [
        -(2**63),
        2**53,
        2**53 + 1,
        2**63 - 1,
    ]
    assert scan([]).sort_by("x").execute(backend="polars").records == []
    missing = scan([{}, {"x": None}, {}]).sort_by("x", missing="first")
    assert missing.execute(backend="polars").records == missing.execute().records


@pytest.mark.parametrize(
    "records",
    [
        [{"x": True}],
        [{"x": []}],
        [{"x": {}}],
        [{"x": float("nan")}],
        [{"x": float("inf")}],
        [{"x": 1}, {"x": "1"}],
        [{"x": 2**80}],
        [{"x": 2**53 + 1}, {"x": 1.0}],
    ],
)
def test_invalid_and_unsupported_domains_identify_field_and_logical_operation(records):
    from slogger.tools import Field, ToolError

    plan = scan(records).limit(10).limit(9).filter(Field("_id").exists()).sort_by("x")
    with pytest.raises(ToolError) as failure:
        plan.execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert failure.value.extra["field"] == ["x"]
    assert failure.value.extra["operation"] == 4


def test_upstream_limit_bounds_sort_domain_and_dependencies_fail_before_reads(tmp_path):
    from slogger.tools import ToolError

    assert scan([{"x": 1}, {"x": []}]).limit(1).sort_by("x").execute(backend="polars").records == [
        {"x": 1, "_id": "mem:0"}
    ]
    plan = scan(tmp_path / "absent.log").select("message").sort_by("x")
    for action in [plan.explain, plan.execute]:
        with pytest.raises(ToolError) as failure:
            action(backend="polars")
        assert failure.value.code == "plan_invalid"


def test_static_explain_reports_global_memory_and_cursor_ineligibility(tmp_path):
    explanation = scan(tmp_path / "absent.log").sort_by("x").limit(1).explain(backend="polars")
    assert explanation["execution"]["working_memory"] == "input_proportional"
    assert explanation["properties"]["source_cursor_eligible"] is False
    assert explanation["properties"]["preserves_record_identity"] is True
    assert "sort value domains" in explanation["pending_data_checks"]


def test_global_file_sort_reconstructs_original_records_after_projection(tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"x":9,"nested":{"a":null}}\n{"x":7}\n')
    second.write_text('{"x":8}\n{"x":1,"nested":[1,2]}\n')
    plan = scan([first, second]).sort_by("x").select("nested", "absent").limit(2)
    result = plan.execute(backend="polars")
    assert result.records == [{"nested": [1, 2], "_id": f"{second}:2"}, {"_id": f"{first}:2"}]
    assert result.metadata["input_rows"] == 4
    assert result.records == plan.execute().records


def test_native_group_aggregate_filter_sort_and_limit_compose():
    from slogger.tools import Field, count_rows, sum_of

    records = [{"k": "a", "v": 2}, {"k": "b", "v": 7}, {"k": "a", "v": 2}, {"k": "c", "v": 7}]
    plan = (
        scan(records)
        .group_by("k")
        .aggregate(total=sum_of(Field("v")), n=count_rows())
        .filter(Field("total").ge(4))
        .sort_by("total", descending=True)
        .limit(2)
    )
    assert plan.execute(backend="polars").records == [
        {"k": "b", "total": 7, "n": 1},
        {"k": "c", "total": 7, "n": 1},
    ]
    assert plan.execute(backend="polars").records == plan.execute().records
    # Sorting before grouping also changes the first-appearance group order.
    plan = scan(records).sort_by("v", descending=True).group_by("k").aggregate(n=count_rows())
    assert plan.execute(backend="polars").records == plan.execute().records


@pytest.mark.parametrize("value", [[1, 2], [True], ["a"], [1.0], [None]])
def test_native_sort_rejects_supported_array_lanes_as_sort_keys(value):
    from slogger.tools import ToolError

    # Array containment supports these values; sorting still requires a scalar key.
    with pytest.raises(ToolError) as failure:
        scan([{"x": value}]).sort_by("x").execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert failure.value.extra["field"] == ["x"]
    assert failure.value.extra["operation"] == 1
