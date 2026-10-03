"""Sparse and heterogeneous semantics through the public execution seam."""

import pytest

from slogger.tools import Field, scan

pytest.importorskip("polars")


def test_sparse_nested_mixed_scalars_preserve_type_and_presence():
    records = [
        {},
        {"request": None},
        {"request": {"x": None}},
        {"request": {"x": True}},
        {"request": {"x": 1}},
        {"request": {"x": 1.0}},
        {"request": {"x": "1"}},
    ]
    field = Field("request", "x")
    for predicate, expected in [
        (field.eq(1), [4, 5]),
        (field.eq(True), [3]),
        (field.eq(None), [2]),
        (field.missing(), [0, 1]),
        (field.not_in([1]), []),
    ]:
        plan = scan(records).filter(predicate)
        result = plan.execute(backend="polars")
        assert result.records == plan.execute().records
        assert [record["_id"] for record in result.records] == [f"mem:{i}" for i in expected]


@pytest.mark.parametrize(
    "predicate",
    [
        Field("x").ne(1),
        Field("x").gt(1),
        Field("x").in_([None, True, 2, "2"]),
        Field("x").not_in([]),
        Field("x").not_in([True]),
        Field("x").not_in([None, 1]),
        Field("x").exists(),
        Field("x").missing(),
    ],
)
def test_heterogeneous_comparison_contract_matches_python(predicate):
    records = [{}, {"x": None}, {"x": False}, {"x": True}, {"x": 1}, {"x": 2.5}, {"x": "2"}]
    plan = scan(records).filter(predicate)
    assert plan.execute(backend="polars").records == plan.execute().records


def test_dotted_keys_and_nonmapping_intermediates_remain_distinct():
    records = [
        {"a.b": 1, "a": {"b": 2}, "ordinal": "user", "field_0_null": "user"},
        {"a.b": 2, "a": [2]},
        {"a": {"b": None}},
        {"a": "text"},
    ]
    assert scan(records).filter(Field("a.b").eq(1)).execute(backend="polars").records == [
        dict(records[0], _id="mem:0")
    ]
    plan = scan(records).filter(Field("a", "b").missing())
    assert plan.execute(backend="polars").records == [
        dict(records[1], _id="mem:1"),
        dict(records[3], _id="mem:3"),
    ]
    assert scan(records).filter(Field("a", "b").eq(None)).select("a", "absent").execute(
        backend="polars"
    ).records == [{"a": {"b": None}, "_id": "mem:2"}]


def test_late_fields_and_types_rebind_across_multiple_batches():
    records = [{} for _ in range(1100)]
    records.extend([{"x": None}, {"x": True}, {"x": 1}, {"x": 1.0}, {"x": "1"}])
    plan = scan(records).filter(Field("x").in_([True, 1, "1"]))
    assert plan.execute(backend="polars").records == [
        {"x": True, "_id": "mem:1101"},
        {"x": 1, "_id": "mem:1102"},
        {"x": 1.0, "_id": "mem:1103"},
        {"x": "1", "_id": "mem:1104"},
    ]
    assert plan.execute(backend="polars").records == plan.execute().records


def test_later_unsupported_data_fails_instead_of_returning_partial_success():
    from slogger.tools import ToolError

    records = [{"x": 1} for _ in range(1100)] + [{"x": [[]]}]
    with pytest.raises(ToolError) as failure:
        scan(records).filter(Field("x").eq(1)).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert failure.value.extra["field"] == ["x"]


def test_large_integer_lanes_stay_exact_and_mixed_float_ranges_fail_explicitly():
    from slogger.tools import ToolError

    records = [{"x": 2**53}, {"x": 2**53 + 1}, {"x": 1.0}, {"x": True}]
    # A large integer literal would also touch the float lane; that unsupported
    # mixed-domain comparison is rejected, rather than rounding it.
    with pytest.raises(ToolError, match="precision"):
        scan(records).filter(Field("x").eq(2**53 + 1)).execute(backend="polars")
    plan = scan(records[:2]).filter(Field("x").eq(2**53 + 1))
    assert plan.execute(backend="polars").records == [{"x": 2**53 + 1, "_id": "mem:1"}]
    plan = scan([{"x": -(2**63)}, {"x": 2**63 - 1}]).filter(Field("x").gt(0))
    assert plan.execute(backend="polars").records == [{"x": 2**63 - 1, "_id": "mem:1"}]
    with pytest.raises(ToolError, match="Int64"):
        scan([{"x": 2**63}]).filter(Field("x").eq(1)).execute(backend="polars")


def test_deterministic_mixed_scalar_records_match_reference():
    import random

    from slogger.tools import all_of, any_of, not_

    random_source = random.Random(314159)
    values = [None, False, True, -1, 0, 1, 1.0, 1.5, "1", "", "a"]
    records = [
        {} if random_source.randrange(4) == 0 else {"x": random_source.choice(values)}
        for _ in range(2400)
    ]
    predicates = [
        all_of(Field("x").exists(), not_(Field("x").eq(1))),
        any_of(Field("x").eq(True), Field("x").in_([None, "1", 1.5])),
        not_(Field("x").not_in([1, False, "a"])),
    ]
    for predicate in predicates:
        plan = scan(records).filter(predicate)
        assert plan.execute(backend="polars").records == plan.execute().records
