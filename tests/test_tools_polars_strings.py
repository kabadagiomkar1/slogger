"""Native string behavior through the public execution seam."""

from typing import Any

import pytest

from slogger.tools import Field, logger_prefix, not_, scan

pytest.importorskip("polars")


def test_prefix_and_logger_hierarchy_match_reference_without_numeric_coercion():
    records = [
        {},
        {"logger": None},
        {"logger": 1},
        {"logger": True},
        {"logger": "app.pay"},
        {"logger": "app.pay.worker"},
        {"logger": "app.payroll"},
        {"logger": "APP.pay"},
    ]
    plan = scan(records).filter(logger_prefix("app.pay"))
    assert plan.execute(backend="polars").records == [
        {"logger": "app.pay", "_id": "mem:4"},
        {"logger": "app.pay.worker", "_id": "mem:5"},
    ]
    assert plan.execute(backend="polars").records == plan.execute().records
    plan = scan(records).filter(Field("logger").starts_with("app.pay"))
    assert [r["_id"] for r in plan.execute(backend="polars").records] == ["mem:4", "mem:5", "mem:6"]
    assert plan.execute(backend="polars").records == plan.execute().records


@pytest.mark.parametrize("pattern", ["", "timeout", "λ", "a\nb", "# plain"])
def test_literal_regex_patterns_match_python_substring_semantics(pattern):
    records = [
        {},
        {"x": None},
        {"x": 1},
        {"x": True},
        {"x": ""},
        {"x": "timeout λ a\nb # plain"},
        {"x": "other"},
    ]
    plan = scan(records).filter(Field("x").regex(pattern))
    assert plan.execute(backend="polars").records == plan.execute().records


@pytest.mark.parametrize(
    "pattern",
    [
        r"\w+",
        r"\d",
        r"\s",
        "a$",
        "^a",
        "a.*b",
        "[ab]",
        "a|b",
        "a+",
        "a?",
        "a{2}",
        "(ab)",
        "(?i)a",
        "a(?=b)",
        r"(a)\1",
        r"a\.b",
    ],
)
def test_nonliteral_regex_is_rejected_before_source_reads(pattern):
    from slogger.tools import ToolError

    consumed = []

    def records():
        consumed.append(True)
        yield {"x": "a\n"}

    plan = scan(records()).filter(Field("x").regex(pattern))
    for action in (plan.execute, plan.explain):
        with pytest.raises(ToolError) as failure:
            action(backend="polars")
        assert failure.value.code == "expression_unsupported"
        assert failure.value.extra["pattern"] == pattern
        assert failure.value.extra["field"] == ["x"]
    assert consumed == []


def test_python_regex_semantics_and_eager_validation_remain_unchanged():
    with pytest.raises(ValueError, match="regex"):
        Field("x").regex("(")
    assert scan([{"x": "²"}]).filter(Field("x").regex(r"\w")).execute().records == [
        {"x": "²", "_id": "mem:0"}
    ]
    assert scan([{"x": "a\n"}]).filter(Field("x").regex("a$")).execute().records == [
        {"x": "a\n", "_id": "mem:0"}
    ]


def test_nested_string_negation_and_late_lanes_match_reference():
    records: list[dict[str, Any]] = [{} for _ in range(1100)]
    records.extend(
        [
            {"request": {"message": None}},
            {"request": {"message": False}},
            {"request": {"message": "timeout"}},
            {"request": {"message": "ok"}},
        ]
    )
    field = Field("request", "message")
    for predicate in [
        field.starts_with("time"),
        field.regex("timeout"),
        not_(field.starts_with("time")),
        not_(field.regex("timeout")),
    ]:
        plan = scan(records).filter(predicate)
        assert plan.execute(backend="polars").records == plan.execute().records


def test_empty_prefix_and_literal_unicode_regex_have_exact_results():
    records = [{}, {"x": None}, {"x": ""}, {"x": "λ🙂"}, {"x": 1}]
    assert scan(records).filter(Field("x").starts_with("")).execute(backend="polars").records == [
        {"x": "", "_id": "mem:2"},
        {"x": "λ🙂", "_id": "mem:3"},
    ]
    assert scan(records).filter(Field("x").regex("🙂")).execute(backend="polars").records == [
        {"x": "λ🙂", "_id": "mem:3"}
    ]


def test_prefix_does_not_interpret_regex_syntax():
    records = [{"x": "a.*[literal]"}, {"x": "ab"}]
    assert scan(records).filter(Field("x").starts_with("a.*[")).execute(
        backend="polars"
    ).records == [{"x": "a.*[literal]", "_id": "mem:0"}]
