"""Actual optional adapter execution through the caller interface."""

from typing import Any

import pytest

from slogger.tools import Field, all_of, any_of, not_, scan

pytest.importorskip("polars")


def test_polars_scalar_plan_matches_python_and_preserves_original_shape():
    records = [
        {"level": "INFO", "duration": 30, "nested": {"x": None}},
        {"level": "ERROR", "duration": 700, "nested": {"x": [1, 2]}},
        {"level": "WARNING", "duration": 600},
    ]
    predicate = all_of(
        Field("level").in_(["ERROR", "WARNING"]),
        any_of(Field("duration").ge(650), not_(Field("level").eq("WARNING"))),
    )
    plan = scan(records).filter(predicate).select("nested", "absent").limit(1)
    result = plan.execute(backend="polars")
    assert result.records == [{"nested": {"x": [1, 2]}, "_id": "mem:1"}]
    assert result.records == plan.execute().records
    assert result.schema == ("nested", "absent")
    assert result.metadata["backend"] == "polars"


@pytest.mark.parametrize(
    "predicate",
    [
        Field("x").eq(1),
        Field("x").ne(1),
        Field("x").gt(1),
        Field("x").le(1),
        Field("x").in_([None, 1, True, "1"]),
        Field("x").not_in([None, 1]),
        Field("x").in_([]),
        Field("x").not_in([]),
        Field("x").exists(),
        not_(Field("x").eq(1)),
        all_of(),
        any_of(),
    ],
)
def test_nullable_scalar_comparisons_and_composition_match_python(predicate):
    records = [{"x": None}, {"x": 1}, {"x": 2}]
    plan = scan(records).filter(predicate)
    assert plan.execute(backend="polars").records == plan.execute().records


@pytest.mark.parametrize(
    "values,candidate",
    [
        ([True, False, None], True),
        (["a", "b", None], "a"),
        ([1.5, 2.0, None], 2),
        ([None, None], None),
    ],
)
def test_scalar_type_identity_matches_python(values, candidate):
    plan = scan([{"x": value} for value in values]).filter(Field("x").ne(candidate))
    assert plan.execute(backend="polars").records == plan.execute().records


def test_limit_order_zero_and_arbitrary_integer_counts(tmp_path):
    plan = scan([{"x": 0}, {"x": 1}, {"x": 1}])
    assert plan.filter(Field("x").eq(1)).limit(1).execute(backend="polars").records == [
        {"x": 1, "_id": "mem:1"}
    ]
    assert plan.limit(1).filter(Field("x").eq(1)).execute(backend="polars").records == []
    path = tmp_path / "bad.log"
    path.write_text("bad\n")
    zero = scan(path).limit(0).execute(backend="polars")
    assert zero.records == []
    assert zero.metadata["input_rows"] == 0
    assert plan.limit(10**50).execute(backend="polars").records == plan.execute().records


def test_static_polars_explain_reports_pending_checks_without_reading():
    consumed = []

    def records():
        consumed.append(True)
        yield {"x": 1}

    explanation = scan(records()).filter(Field("x").eq(1)).explain(backend="polars")
    assert consumed == []
    assert explanation["execution"]["pending_data_checks"]
    assert explanation["execution"]["backend"] == "polars"


@pytest.mark.parametrize(
    "records", [[{}], [{"x": []}], [{"x": True}, {"x": 1}], [{"x": 2**80}], [{"x": float("inf")}]]
)
def test_unsupported_data_is_explicit(records):
    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan(records).filter(Field("x").eq(1)).execute(backend="polars")
    assert failure.value.code == "data_incompatible"


@pytest.mark.parametrize(
    "predicate",
    [
        Field("request", "x").eq(1),
        Field("x").eq({"a": 1}),
        Field("x").regex("a"),
        Field("x").contains_any([1]),
        Field("x").eq(2**80),
    ],
)
def test_unsupported_expressions_fail_before_source_reads(predicate):
    from slogger.tools import ToolError

    consumed = []

    def records():
        consumed.append(True)
        yield {"x": 1}

    with pytest.raises(ToolError) as failure:
        scan(records()).filter(predicate).execute(backend="polars")
    assert failure.value.code == "expression_unsupported"
    assert consumed == []


def test_mixed_numeric_comparison_cannot_silently_round():
    from slogger.tools import ToolError

    plan = scan([{"x": 2**53 + 1}]).filter(Field("x").eq(float(2**53)))
    assert plan.execute().records == []
    with pytest.raises(ToolError) as failure:
        plan.execute(backend="polars")
    assert failure.value.code == "data_incompatible"


def test_file_metadata_execution_errors_and_closed_schema(tmp_path):
    from slogger.tools import ToolError

    path = tmp_path / "app.log"
    path.write_text('bad\n{"x":1}\n{"x":2,"nested":{"a":null}}\n')
    plan = scan(path).filter(Field("x").eq(2)).select("nested", "absent")
    result = plan.execute(backend="polars")
    assert result.records == [{"nested": {"a": None}, "_id": f"{path}:3"}]
    assert result.metadata["skipped_lines"] == 1
    assert result.warnings == []
    with pytest.raises(ToolError) as failure:
        scan(path).select("nested").filter(Field("x").eq(1)).execute(backend="polars")
    assert failure.value.code == "plan_invalid"
    with pytest.raises(ToolError) as failure:
        scan(tmp_path / "missing.log").execute(backend="polars")
    assert failure.value.code == "execution_failed"
    assert isinstance(failure.value.__cause__, FileNotFoundError)


def test_native_batches_are_global_for_filter_limits_and_late_errors():
    from slogger.tools import ToolError

    records: list[dict[str, Any]] = [{"x": i} for i in range(2200)]
    plan = scan(records).filter(Field("x").ge(1500)).limit(2)
    assert plan.execute(backend="polars").records == [
        {"x": 1500, "_id": "mem:1500"},
        {"x": 1501, "_id": "mem:1501"},
    ]
    records.append({"x": []})
    with pytest.raises(ToolError) as failure:
        scan(records).filter(Field("x").ge(1500)).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert scan(records).limit(1).filter(Field("x").ge(0)).execute(backend="polars").records == [
        {"x": 0, "_id": "mem:0"}
    ]


def test_polars_sorting_is_rejected_until_native_support_is_available():
    from slogger.tools import ToolError

    plan = scan([{"x": 1}]).sort_by("x")
    for action in (plan.execute, plan.explain):
        with pytest.raises(ToolError) as failure:
            action(backend="polars")
        assert failure.value.code == "operation_unsupported"


def test_polars_aggregation_is_rejected_until_native_support_is_available():
    from slogger.tools import ToolError, count_rows

    plan = scan([{"k": "a"}]).group_by("k").aggregate(n=count_rows())
    for action in (plan.execute, plan.explain):
        with pytest.raises(ToolError) as failure:
            action(backend="polars")
        assert failure.value.code == "operation_unsupported"
