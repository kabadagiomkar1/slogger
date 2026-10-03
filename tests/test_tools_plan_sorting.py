"""Sorting semantics exercised through finite query execution."""

from slogger.tools import scan


def test_sort_is_global_and_ties_use_source_ordinals():
    records = [
        {"duration": 3, "message": "third"},
        {"duration": 1.0, "message": "first"},
        {"duration": 1, "message": "second"},
    ]
    parent = scan(records)
    result = parent.sort_by("duration").execute()
    assert [r["message"] for r in result.records] == ["first", "second", "third"]
    assert [r["_id"] for r in result.records] == ["mem:1", "mem:2", "mem:0"]
    assert [r["message"] for r in parent.execute().records] == ["third", "first", "second"]
    assert result.metadata["preserves_record_identity"]
    assert result.metadata["source_cursor_eligible"] is False


def test_sort_direction_does_not_reverse_missing_or_null_placement():
    records = [
        {"name": "missing"},
        {"name": "null", "x": None},
        {"name": "low", "x": 1},
        {"name": "high", "x": 2},
    ]
    parent = scan(records)
    assert [r["name"] for r in parent.sort_by("x").execute().records] == [
        "low",
        "high",
        "null",
        "missing",
    ]
    assert [r["name"] for r in parent.sort_by("x", descending=True).execute().records] == [
        "high",
        "low",
        "null",
        "missing",
    ]
    assert [
        r["name"] for r in parent.sort_by("x", missing="first", nulls="first").execute().records
    ] == [
        "missing",
        "null",
        "low",
        "high",
    ]
    assert [
        r["name"] for r in parent.sort_by("x", descending=True, nulls="first").execute().records
    ] == [
        "null",
        "high",
        "low",
        "missing",
    ]


def test_limit_order_and_repeated_sort_ties_preserve_original_identity():
    records = [{"x": 3, "tie": 1}, {"x": 2, "tie": 1}, {"x": 1, "tie": 1}]
    parent = scan(records)
    assert [r["x"] for r in parent.sort_by("x").limit(2).execute().records] == [1, 2]
    assert [r["x"] for r in parent.limit(2).sort_by("x").execute().records] == [2, 3]
    assert [r["x"] for r in parent.sort_by("x").sort_by("tie").execute().records] == [3, 2, 1]
    assert [
        r["x"] for r in parent.sort_by("x").sort_by("tie", descending=True).execute().records
    ] == [3, 2, 1]


def test_strings_and_large_integers_sort_without_numeric_coercion():
    records = [{"x": 2**100 + 1}, {"x": 2**100}, {"x": 0.5}]
    assert [r["x"] for r in scan(records).sort_by("x").execute().records] == [
        0.5,
        2**100,
        2**100 + 1,
    ]
    assert [
        r["x"] for r in scan([{"x": "b"}, {"x": "A"}, {"x": "a"}]).sort_by("x").execute().records
    ] == ["A", "a", "b"]
    assert scan([]).sort_by("x").execute().records == []


def test_invalid_present_sort_domains_fail_with_field_and_operation():
    import pytest

    from slogger.tools import ToolError

    for value in (True, [], {}, float("nan"), float("inf")):
        with pytest.raises(ToolError) as failure:
            scan([{"x": value}]).sort_by("x").execute()
        assert failure.value.code == "data_incompatible"
        assert failure.value.extra["field"] == ["x"]
        assert failure.value.extra["operation"] == 1
    with pytest.raises(ToolError, match="mixes numeric and string"):
        scan([{"x": 1}, {"x": "1"}]).sort_by("x").execute()
    # Unsupported values outside an upstream limit are outside the sort domain.
    assert scan([{"x": 1}, {"x": []}]).limit(1).sort_by("x").execute().records == [
        {"x": 1, "_id": "mem:0"},
    ]


def test_sort_dependencies_and_arguments_validate_before_reading(tmp_path):
    import pytest

    from slogger.tools import ToolError

    plan = scan(tmp_path / "not-there.log").select("message").sort_by("x")
    for action in (plan.execute, plan.explain):
        with pytest.raises(ToolError) as failure:
            action()
        assert failure.value.code == "plan_invalid"
    for field in ("", None, ("x",)):
        with pytest.raises(ValueError):
            scan([]).sort_by(field)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="boolean"):
        scan([]).sort_by("x", descending=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="first.*last"):
        scan([]).sort_by("x", missing="middle")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="first.*last"):
        scan([]).sort_by("x", nulls="middle")  # type: ignore[arg-type]
    explanation = scan(tmp_path / "not-there.log").sort_by("x").limit(1).explain()
    assert explanation["execution"]["mode"] == "blocking"
    assert explanation["execution"]["working_memory"] == "input_proportional"
    assert explanation["properties"]["source_cursor_eligible"] is False
    assert explanation["properties"]["preserves_record_identity"] is True
    assert explanation["required_fields"] == [["x"]]
    assert "sort value domains" in explanation["pending_data_checks"]


def test_sort_is_global_across_sources_and_preserves_projected_ids(tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"x":9}\n{"x":7}\n')
    second.write_text('{"x":8}\n{"x":1}\n')
    result = scan([first, second]).sort_by("x").select("x").limit(2).execute()
    assert result.records == [{"x": 1, "_id": f"{second}:2"}, {"x": 7, "_id": f"{first}:2"}]
    assert result.metadata["input_rows"] == 4
