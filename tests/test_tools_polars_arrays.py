"""Native typed array filtering through the public query-plan interface."""

from typing import Any

import pytest

from slogger.tools import Field, scan

pytest.importorskip("polars")


def test_array_membership_preserves_typed_members_and_original_output():
    records: list[dict[str, Any]] = [
        {"tags": [True, None]},
        {"tags": [1, None]},
        {"tags": [1.0]},
        {"tags": ["1"]},
        {"tags": []},
        {"tags": None},
        {},
        {"tags": 1},
    ]
    for predicate in (
        Field("tags").contains_any([True, "1"]),
        Field("tags").contains_all([1, None]),
        Field("tags").contains_all([1, 1]),
    ):
        plan = scan(records).filter(predicate)
        assert plan.execute(backend="polars").records == plan.execute().records
    assert records[0]["tags"] == [True, None]


@pytest.mark.parametrize(
    "predicate",
    [
        Field("tags").contains_any([]),
        Field("tags").contains_all([]),
        Field("tags").contains_any([None]),
        Field("tags").contains_all([None, None]),
        Field("tags").in_([True, 1, None]),
        Field("tags").not_in([]),
        Field("tags").exists(),
    ],
)
def test_empty_null_array_and_scalar_membership_match_reference(predicate):
    records: list[dict[str, Any]] = [
        {"tags": []},
        {"tags": [None]},
        {"tags": [None, None]},
        {"tags": None},
        {},
        {"tags": True},
        {"tags": 1},
        {"tags": "x"},
    ]
    plan = scan(records).filter(predicate)
    assert plan.execute(backend="polars").records == plan.execute().records
    assert scan(records).filter(Field("tags").contains_all([])).execute(
        backend="polars"
    ).records == [dict(record, _id=f"mem:{i}") for i, record in enumerate(records[:3])]
    assert scan(records).filter(Field("tags").not_in([])).execute(backend="polars").records == [
        dict(records[i], _id=f"mem:{i}") for i in (3, 5, 6, 7)
    ]


def test_nested_paths_composition_negation_and_tuples_preserve_shape():
    from slogger.tools import all_of, any_of, not_

    records: list[dict[str, Any]] = [
        {"request": {"tags": ["retry", "pay"]}, "request.tags": [True]},
        {"request": {"tags": ("pay",)}, "request.tags": [1]},
        {"request": {"tags": None}},
        {},
    ]
    predicate = all_of(
        any_of(
            Field("request", "tags").contains_any(["retry"]),
            Field("request.tags").contains_any([1]),
        ),
        not_(Field("request", "tags").contains_all([])),
    )
    assert scan(records).filter(predicate).execute(backend="polars").records == []
    for predicate in (
        Field("request", "tags").contains_any(["pay"]),
        not_(Field("request", "tags").contains_any(["retry"])),
        Field("request.tags").contains_any([True]),
    ):
        plan = scan(records).filter(predicate)
        assert plan.execute(backend="polars").records == plan.execute().records
    selected = (
        scan(records)
        .filter(Field("request", "tags").contains_any(["pay"]))
        .execute(backend="polars")
    )
    assert selected.records[1]["request"]["tags"] == ("pay",)
    assert records[0]["request"]["tags"] == ["retry", "pay"]


@pytest.mark.parametrize(
    "array",
    [[True, 1], [1, 1.0], ["x", 1], [[1]], [{"x": 1}], [10**100], [float("nan")], [float("inf")]],
)
def test_unsupported_array_domains_fail_explicitly(array):
    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan([{"tags": array}]).filter(Field("tags").contains_any([1])).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert failure.value.extra["field"] == ["tags"]


def test_array_profiles_change_between_batches_without_coercion_or_partial_success():
    from slogger.tools import ToolError

    records: list[dict[str, Any]] = [{"tags": [1]} for _ in range(1024)] + [
        {"tags": [True]},
        {"tags": ["one"]},
        {"tags": [None]},
    ]
    plan = scan(records).filter(Field("tags").contains_any([True, "one", None]))
    assert plan.execute(backend="polars").records == [
        dict(records[i], _id=f"mem:{i}") for i in (1024, 1025, 1026)
    ]
    unsupported = scan(records + [{"tags": [1, True]}]).filter(Field("tags").contains_all([]))
    with pytest.raises(ToolError) as failure:
        unsupported.execute(backend="polars")
    assert failure.value.code == "data_incompatible"


def test_array_numeric_precision_guards_and_large_operands_fail_before_reading():
    from slogger.tools import ToolError

    for array, candidate in (([2**53 + 1], float(2**53)), ([float(2**53)], 2**53 + 1)):
        with pytest.raises(ToolError, match="precision") as failure:
            scan([{"tags": array}]).filter(Field("tags").contains_any([candidate])).execute(
                backend="polars"
            )
        assert failure.value.code == "data_incompatible"
    assert scan([{"tags": [2**63 - 1]}]).filter(Field("tags").contains_any([2**63 - 1])).execute(
        backend="polars"
    ).records == [
        {"tags": [2**63 - 1], "_id": "mem:0"},
    ]
    consumed = []

    def records():
        consumed.append(True)
        yield {"tags": [1]}

    with pytest.raises(ToolError) as failure:
        scan(records()).filter(Field("tags").contains_any([10**100])).execute(backend="polars")
    assert failure.value.code == "expression_unsupported"
    assert consumed == []


def test_array_group_keys_and_numeric_aggregate_inputs_remain_invalid():
    from slogger.tools import ToolError, count_rows, sum_of

    records = [{"tags": [1, None]}, {"tags": []}]
    plans = [
        scan(records).group_by("tags").aggregate(n=count_rows()),
        scan(records).aggregate(total=sum_of(Field("tags"))),
    ]
    for plan in plans:
        for backend in ("python", "polars"):
            with pytest.raises(ToolError) as failure:
                plan.execute(backend=backend)
            assert failure.value.code == "data_incompatible"


def test_native_strings_do_not_search_array_members():
    records: list[dict[str, Any]] = [{"tags": ["prefix"]}, {"tags": "prefix"}, {}]
    for predicate in (Field("tags").starts_with("pre"), Field("tags").regex("pre")):
        result = scan(records).filter(predicate).execute(backend="polars")
        assert result.records == [{"tags": "prefix", "_id": "mem:1"}]
