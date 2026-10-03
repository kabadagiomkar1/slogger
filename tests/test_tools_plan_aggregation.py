import pytest

from slogger.tools import Field, ToolError, count_rows, mean_of, scan, sum_of


def test_grouped_numeric_results_and_post_filter():
    result = (
        scan([{"k": "a", "v": 2}, {"k": "b", "v": 9}, {"k": "a", "v": 4}])
        .group_by("k")
        .aggregate(n=count_rows(), total=sum_of(Field("v")), avg=mean_of(Field("v")))
        .filter(Field("n").ge(2))
        .select("k", "total", "avg")
        .execute()
    )
    assert result.records == [{"k": "a", "total": 6, "avg": 3.0}]
    assert result.metadata["preserves_record_identity"] is False


def test_group_identity_and_stable_order_are_typed():
    records = [{"k": True}, {"k": 1}, {}, {"k": None}, {"k": 1.0}, {"k": 2**60}, {"k": 2**60 + 1}]
    result = scan(records).group_by("k").aggregate(n=count_rows()).execute()
    assert result.records == [
        {"k": True, "n": 1},
        {"k": 1, "n": 2},
        {"n": 1},
        {"k": None, "n": 1},
        {"k": 2**60, "n": 1},
        {"k": 2**60 + 1, "n": 1},
    ]
    assert all("_id" not in record for record in result.records)


def test_empty_and_missing_numeric_reductions():
    from slogger.tools import max_of, min_of

    empty = (
        scan([])
        .aggregate(
            n=count_rows(),
            total=sum_of(Field("v")),
            avg=mean_of(Field("v")),
            lo=min_of(Field("v")),
            hi=max_of(Field("v")),
        )
        .execute()
    )
    assert empty.records == [{"n": 0, "total": 0, "avg": None, "lo": None, "hi": None}]
    assert scan([]).group_by("k").aggregate(n=count_rows()).execute().records == []
    result = (
        scan([{}, {"v": None}, {"v": 2**100}, {"v": 1}])
        .aggregate(n=count_rows(), total=sum_of(Field("v")))
        .execute()
    )
    assert result.records == [{"n": 4, "total": 2**100 + 1}]


def test_multiple_keys_nested_reduction_and_limits():
    result = (
        scan(
            [
                {"a": "x", "b": 1, "obj": {"v": 2}},
                {"a": "x", "b": 2, "obj": {"v": 3}},
                {"a": "x", "b": 1, "obj": {"v": 7}},
            ]
        )
        .group_by("a", "b")
        .aggregate(total=sum_of(Field("obj", "v")))
        .limit(1)
        .execute()
    )
    assert result.records == [{"a": "x", "b": 1, "total": 9}]
    assert result.schema == ("a", "b", "total")


@pytest.mark.parametrize("value", [True, "3", [], {}])
def test_numeric_aggregate_rejects_incompatible_present_values(value):
    with pytest.raises(ToolError, match="numeric aggregate") as error:
        scan([{"v": value}]).aggregate(total=sum_of(Field("v"))).execute()
    assert error.value.code == "data_incompatible"


@pytest.mark.parametrize("value", [[], {}])
def test_group_keys_reject_collections(value):
    with pytest.raises(ToolError, match="scalar"):
        scan([{"k": value}]).group_by("k").aggregate(n=count_rows()).execute()


def test_aggregate_schema_and_builder_validation():
    with pytest.raises(ValueError, match="unique"):
        scan([]).group_by("k", "k")
    with pytest.raises(ValueError, match="collide"):
        scan([]).group_by("k").aggregate(k=count_rows())
    with pytest.raises(ValueError):
        scan([]).aggregate()
    plan = scan([]).group_by("k").aggregate(n=count_rows())
    with pytest.raises(ToolError, match="unavailable"):
        plan.filter(Field("v").eq(1)).execute()
    with pytest.raises(ToolError, match="unavailable"):
        plan.select("v").execute()
    assert not hasattr(scan([]).group_by("k"), "execute")


def test_explain_aggregation_does_not_consume_source():
    seen = []

    def source():
        seen.append(True)
        yield {"k": 1}

    info = scan(source()).group_by("k").aggregate(n=count_rows()).explain()
    assert seen == []
    assert info["properties"]["preserves_record_identity"] is False
    assert info["properties"]["schema"] == ["k", "n"]


def test_python_float_reductions_have_compensated_reference_semantics():
    values = [{"v": value} for value in [1e16, 1.0, 1.0]]
    result = scan(values).aggregate(total=sum_of(Field("v")), avg=mean_of(Field("v"))).execute()
    assert result.records == [{"total": 10000000000000002.0, "avg": 3333333333333334.0}]
