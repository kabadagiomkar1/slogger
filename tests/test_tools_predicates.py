"""Typed expression semantics verified through public query execution."""

from dataclasses import FrozenInstanceError

import pytest

from slogger.tools import Field, all_of, any_of, logger_prefix, not_, scan


def selected(expression, record):
    return bool(scan([record]).filter(expression).execute().records)


@pytest.mark.parametrize(
    "value,expected,equal",
    [
        (1, 1.0, True),
        (True, 1, False),
        (False, 0, False),
        ("1", 1, False),
        (None, None, True),
        ([True], [1], False),
        ({"x": True}, {"x": 1}, False),
        ({"x": [1, None]}, {"x": [1.0, None]}, True),
    ],
)
def test_typed_equality(value, expected, equal):
    predicate = Field("x").eq(expected)
    assert selected(predicate, {"x": value}) is equal


def test_presence_negation_and_incompatible_values():
    f = Field("x")
    assert selected(f.exists(), {"x": None})
    assert not selected(f.missing(), {"x": None})
    for predicate in (f.eq(None), f.ne(1), f.not_in([1]), f.regex("x"), f.ge(0)):
        assert not selected(predicate, {})
    assert not selected(f.ne(1), {"x": "1"})
    assert not selected(f.not_in([1]), {"x": "2"})
    assert selected(not_(f.eq(1)), {})
    assert selected(not_(f.eq(1)), {"x": "1"})


@pytest.mark.parametrize("method", ["gt", "ge", "lt", "le"])
def test_ordering_is_typed(method):
    predicate = getattr(Field("x"), method)(2)
    assert not selected(predicate, {"x": True})
    assert not selected(predicate, {"x": "3"})
    assert not selected(predicate, {"x": None})
    with pytest.raises(TypeError):
        getattr(Field("x"), method)(None)


def test_ordering_boundaries():
    f = Field("x")
    assert selected(f.ge(2), {"x": 2.0})
    assert selected(f.le(2), {"x": 2})
    assert not selected(f.gt(2), {"x": 2})
    assert not selected(f.lt(2), {"x": 2})
    assert selected(f.gt("a"), {"x": "b"})


def test_paths_and_literal_dots():
    record = {"request.method": "GET", "request": {"method": "POST"}}
    assert selected(Field("request.method").eq("GET"), record)
    assert selected(Field("request", "method").eq("POST"), record)
    assert selected(Field("request", "method").missing(), {"request": None})
    assert selected(Field("request", "method").missing(), {"request": []})
    for path in [(), ("",), ("request", "")]:
        with pytest.raises(ValueError):
            Field(*path)


def test_membership_and_arrays():
    f = Field("x")
    assert selected(f.in_([True, "yes"]), {"x": True})
    assert not selected(f.in_([1]), {"x": True})
    assert selected(f.not_in([1, True]), {"x": 2})
    assert selected(f.in_([None]), {"x": None})
    assert not selected(f.in_(["a"]), {"x": ["a"]})
    assert selected(f.contains_any([True, "b"]), {"x": [1, "b"]})
    assert not selected(f.contains_all([True, "b"]), {"x": [1, "b"]})
    assert selected(f.contains_all(["a", "a"]), {"x": ("a",)})
    assert not selected(f.contains_any(["a"]), {"x": "a"})
    assert not selected(f.contains_any(["a"]), {"x": [["a"]]})


def test_empty_compositions_and_candidates():
    assert selected(all_of(), {})
    assert not selected(any_of(), {})
    f = Field("x")
    assert not selected(f.in_([]), {"x": 1})
    assert selected(f.not_in([]), {"x": None})
    assert not selected(f.not_in([]), {})
    assert not selected(f.contains_any([]), {"x": []})
    assert selected(f.contains_all([]), {"x": []})
    assert not selected(f.contains_all([]), {"x": ""})


def test_string_matching_and_logger_boundaries():
    assert selected(Field("x").regex("timeout"), {"x": "request timeout"})
    assert not selected(Field("x").regex("1"), {"x": 1})
    assert selected(Field("x").starts_with("pay"), {"x": "payment"})
    predicate = logger_prefix("app.pay")
    assert selected(predicate, {"logger": "app.pay"})
    assert selected(predicate, {"logger": "app.pay.db"})
    assert not selected(predicate, {"logger": "app.payment"})
    with pytest.raises(ValueError):
        Field("x").regex("[")
    with pytest.raises(TypeError):
        Field("x").regex(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Field("x").starts_with(1)  # type: ignore[arg-type]


def test_operand_snapshots_and_explanation_is_detached():
    operand = {"items": [1, True]}
    predicate = Field("x").eq(operand)
    operand["items"].append(3)
    assert selected(predicate, {"x": {"items": [1, True]}})
    explained = predicate.explain()
    explained["expression"]["right"]["value"]["items"].append(4)
    assert predicate.explain()["expression"]["right"]["value"] == {"items": [1, True]}
    values = [1, "a"]
    membership = Field("x").in_(iter(values))
    values.append(2)
    assert not selected(membership, {"x": 2})


def test_invalid_operands_and_accidental_boolean():
    for value in (object(), float("inf"), float("nan"), {1: "x"}):
        with pytest.raises(TypeError):
            Field("x").eq(value)
    for values in ("abc", {"a": 1}, [[1]], [{"a": 1}]):
        with pytest.raises(TypeError):
            Field("x").in_(values)
    with pytest.raises(TypeError, match="all_of"):
        bool(Field("x").exists())
    with pytest.raises(TypeError):
        all_of(True)  # type: ignore[arg-type]


def test_cyclic_operands_rejected_but_shared_values_allowed():
    cyclic: list = []
    cyclic.append(cyclic)
    with pytest.raises(TypeError, match="cycles"):
        Field("x").eq(cyclic)
    child = [1]
    assert selected(Field("x").eq([child, child]), {"x": [[1], [1]]})


def test_expression_equality_preserves_typed_behavior():
    assert Field("x").eq(1) == Field("x").eq(1.0)
    assert Field("x").eq(True) != Field("x").eq(1)
    assert Field("x").in_([True]) != Field("x").in_([1])
    assert Field("x").eq({"a": 1, "b": True}) == Field("x").eq({"b": True, "a": 1})
    assert all_of(Field("x").eq(True)) != all_of(Field("x").eq(1))


def test_ixr_inspection_is_immutable_and_execution_independent():
    predicate = all_of(Field("request", "method").eq("POST"), Field("level").in_(["ERROR"]))
    from slogger.tools import And

    ixr = predicate
    assert isinstance(ixr, And)
    assert ixr.required_fields() == frozenset({("request", "method"), ("level",)})
    assert ixr.explain()["version"] == 1
    with pytest.raises(FrozenInstanceError):
        ixr.children = ()  # type: ignore[misc]
    assert selected(predicate, {"request": {"method": "POST"}, "level": "ERROR"})


def test_ixr_snapshots_preserve_types_and_detached_inspection():
    value = {"nested": [True, 1, None]}
    predicate = Field("x").eq(value)
    expression = predicate
    value["nested"].append(False)
    assert expression == Field("x").eq({"nested": [True, 1, None]})
    assert expression != Field("x").eq({"nested": [1, 1, None]})
    description = expression.explain()
    description["expression"]["right"]["value"]["nested"].append("changed")
    assert selected(predicate, {"x": {"nested": [True, 1, None]}})
    assert expression.explain()["expression"]["right"]["type"] == "object"
    assert Field("x").missing().explain()["expression"]["op"] == "not"


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_direct_ixr_builders_compose_and_execute(backend):
    from slogger.tools import And, Compare

    expression = Field("x").ge(2) & ~Field("excluded").eq(True)
    assert isinstance(expression, And)
    assert isinstance(Field("x").eq(2), Compare)
    result = (
        scan([{"x": 1}, {"x": 2}, {"x": 3, "excluded": True}])
        .filter(expression)
        .execute(backend=backend)
    )
    assert result.records == [{"x": 2}]
