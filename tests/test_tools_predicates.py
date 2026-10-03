"""Semantic contract for the typed Python filtering API."""

from dataclasses import FrozenInstanceError, replace

import pytest

from slogger.tools import Field, Filters, all_of, any_of, logger_prefix, not_, query
from slogger.tools.filters import Where
from slogger.tools.output_schema import validate_tool_output


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
    assert predicate.matches({"x": value}) is equal
    assert predicate.compile()({"x": value}) is equal


def test_presence_negation_and_incompatible_values():
    f = Field("x")
    assert f.exists().matches({"x": None})
    assert not f.missing().matches({"x": None})
    for predicate in (f.eq(None), f.ne(1), f.not_in([1]), f.regex("x"), f.ge(0)):
        assert not predicate.matches({})
    assert not f.ne(1).matches({"x": "1"})
    assert not f.not_in([1]).matches({"x": "2"})
    assert not_(f.eq(1)).matches({})
    assert not_(f.eq(1)).matches({"x": "1"})


@pytest.mark.parametrize("method", ["gt", "ge", "lt", "le"])
def test_ordering_is_typed(method):
    predicate = getattr(Field("x"), method)(2)
    assert not predicate.matches({"x": True})
    assert not predicate.matches({"x": "3"})
    assert not predicate.matches({"x": None})
    with pytest.raises(TypeError):
        getattr(Field("x"), method)(None)


def test_ordering_boundaries():
    f = Field("x")
    assert f.ge(2).matches({"x": 2.0})
    assert f.le(2).matches({"x": 2})
    assert not f.gt(2).matches({"x": 2})
    assert not f.lt(2).matches({"x": 2})
    assert f.gt("a").matches({"x": "b"})


def test_paths_and_literal_dots():
    record = {"request.method": "GET", "request": {"method": "POST"}}
    assert Field("request.method").eq("GET").matches(record)
    assert Field("request", "method").eq("POST").matches(record)
    assert Field("request", "method").missing().matches({"request": None})
    assert Field("request", "method").missing().matches({"request": []})
    for path in [(), ("",), ("request", "")]:
        with pytest.raises(ValueError):
            Field(*path)


def test_membership_and_arrays():
    f = Field("x")
    assert f.in_([True, "yes"]).matches({"x": True})
    assert not f.in_([1]).matches({"x": True})
    assert f.not_in([1, True]).matches({"x": 2})
    assert f.in_([None]).matches({"x": None})
    assert not f.in_(["a"]).matches({"x": ["a"]})
    assert f.contains_any([True, "b"]).matches({"x": [1, "b"]})
    assert not f.contains_all([True, "b"]).matches({"x": [1, "b"]})
    assert f.contains_all(["a", "a"]).matches({"x": ("a",)})
    assert not f.contains_any(["a"]).matches({"x": "a"})
    assert not f.contains_any(["a"]).matches({"x": [["a"]]})


def test_empty_compositions_and_candidates():
    assert all_of().matches({})
    assert not any_of().matches({})
    f = Field("x")
    assert not f.in_([]).matches({"x": 1})
    assert f.not_in([]).matches({"x": None})
    assert not f.not_in([]).matches({})
    assert not f.contains_any([]).matches({"x": []})
    assert f.contains_all([]).matches({"x": []})
    assert not f.contains_all([]).matches({"x": ""})


def test_string_matching_and_logger_boundaries():
    assert Field("x").regex("timeout").matches({"x": "request timeout"})
    assert not Field("x").regex("1").matches({"x": 1})
    assert Field("x").starts_with("pay").matches({"x": "payment"})
    predicate = logger_prefix("app.pay")
    assert predicate.matches({"logger": "app.pay"})
    assert predicate.matches({"logger": "app.pay.db"})
    assert not predicate.matches({"logger": "app.payment"})
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
    assert predicate.matches({"x": {"items": [1, True]}})
    explained = predicate.explain()
    explained["value"]["items"].append(4)
    assert predicate.explain()["value"] == {"items": [1, True]}
    values = [1, "a"]
    membership = Field("x").in_(iter(values))
    values.append(2)
    assert not membership.matches({"x": 2})
    with pytest.raises(FrozenInstanceError):
        predicate._value = None  # type: ignore[misc]
    assert predicate.compile() is predicate.compile()


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


def test_short_circuit():
    class Explosive(dict):
        def __contains__(self, key):
            if key == "boom":
                raise AssertionError("second branch must not be evaluated")
            return super().__contains__(key)

    record = Explosive(x=1)
    assert any_of(Field("x").eq(1), Field("boom").exists()).matches(record)
    assert not all_of(Field("x").eq(2), Field("boom").exists()).matches(record)


def test_filters_compatibility_replacement_mutation_and_explain():
    predicate = Field("user").in_(["ada", "bob"])
    filters = Filters(level_min=30, where=(Where("amount", ">=", "99"),), predicate=predicate)
    record = {"level": "ERROR", "amount": 100, "user": "ada"}
    assert filters.matches(record)
    assert not filters.matches(dict(record, user="cara"))
    assert not replace(filters, level_min=50).matches(record)
    filters.predicate = Field("user").eq("cara")
    assert not filters.matches(record)
    explanation = filters.explain()
    validate_tool_output("explain", explanation)
    assert explanation["filters"]["predicate"]["expression"] == filters.predicate.explain()
    with pytest.raises(ValueError, match="inspection-only"):
        Filters.from_mapping(explanation["filters"])
    with pytest.raises(TypeError):
        Filters(predicate=True)  # type: ignore[arg-type]
    assert "predicate" not in Filters().explain()["filters"]


def test_compound_query_pagination():
    def records():
        for i in range(10):
            yield {"level": "ERROR", "request": {"method": "POST"}, "n": i}

    filters = Filters(
        predicate=all_of(
            Field("request", "method").eq("POST"),
            Field("n").in_([1, 3, 5]),
        )
    )
    page = query(records(), filters=filters, limit=2, complete=False)
    assert [row["n"] for row in page.records] == [1, 3]
    # Reader currently materializes in-memory iterables for replayable cursors.
    next_page = query(records(), filters=filters, after=page.next_cursor, limit=2)
    assert [row["n"] for row in next_page.records] == [5]


def test_cyclic_operands_rejected_but_shared_values_allowed():
    cyclic: list = []
    cyclic.append(cyclic)
    with pytest.raises(TypeError, match="cycles"):
        Field("x").eq(cyclic)
    child = [1]
    assert Field("x").eq([child, child]).matches({"x": [[1], [1]]})


def test_recursive_explanation_validation():
    filters = Filters(
        predicate=all_of(
            Field("x").exists(),
            not_(any_of(Field("x").in_([1]), Field("y").missing())),
        )
    )
    payload = filters.explain()
    validate_tool_output("explain", payload)
    payload["filters"]["predicate"]["expression"]["children"][1]["children"] = []
    with pytest.raises(ValueError):
        validate_tool_output("explain", payload)


def test_expression_equality_preserves_typed_behavior():
    assert Field("x").eq(1) == Field("x").eq(1.0)
    assert Field("x").eq(True) != Field("x").eq(1)
    assert Field("x").in_([True]) != Field("x").in_([1])
    assert Field("x").eq({"a": 1, "b": True}) == Field("x").eq({"b": True, "a": 1})
    assert all_of(Field("x").eq(True)) != all_of(Field("x").eq(1))


def test_ixr_inspection_is_immutable_and_execution_independent():
    predicate = all_of(Field("request", "method").eq("POST"), Field("level").in_(["ERROR"]))
    from slogger.tools.ixr import And

    ixr = predicate.to_ixr()
    assert isinstance(ixr, And)
    assert ixr.required_fields() == frozenset({("request", "method"), ("level",)})
    assert ixr.explain()["version"] == 1
    with pytest.raises(FrozenInstanceError):
        ixr.children = ()  # type: ignore[misc]
    assert predicate.compile() is predicate.compile()
    assert predicate.matches({"request": {"method": "POST"}, "level": "ERROR"})


def test_custom_predicates_remain_usable_without_ixr():
    from slogger.tools import Predicate

    class Custom(Predicate):
        def compile(self):
            return lambda record: record.get("accepted") is True

        def explain(self):
            return {"custom": "accepted"}

    predicate = all_of(Custom(), Field("level").eq("ERROR"))
    assert Filters(predicate=predicate).matches({"accepted": True, "level": "ERROR"})
    with pytest.raises(TypeError, match="does not support IXR"):
        predicate.to_ixr()


def test_ixr_snapshots_preserve_types_and_detached_inspection():
    value = {"nested": [True, 1, None]}
    predicate = Field("x").eq(value)
    expression = predicate.to_ixr()
    value["nested"].append(False)
    assert expression == Field("x").eq({"nested": [True, 1, None]}).to_ixr()
    assert expression != Field("x").eq({"nested": [1, 1, None]}).to_ixr()
    description = expression.explain()
    description["expression"]["right"]["value"]["nested"].append("changed")
    assert predicate.matches({"x": {"nested": [True, 1, None]}})
    assert expression.explain()["expression"]["right"]["type"] == "object"
    assert Field("x").missing().to_ixr().explain()["expression"]["op"] == "not"


def test_custom_composition_compiles_only_when_executed():
    from slogger.tools import Predicate

    compilations = []

    class Custom(Predicate):
        def compile(self):
            compilations.append(True)
            return lambda record: True

        def explain(self):
            return {"custom": True}

    predicate = all_of(Custom(), Field("x").eq(1))
    assert compilations == []
    matcher = predicate.compile()
    assert predicate.compile() is matcher
    assert compilations == [True]
    assert matcher({"x": 1})
