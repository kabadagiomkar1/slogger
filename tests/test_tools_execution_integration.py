"""New execution adapters preserve existing tooling contracts at caller seams."""

import builtins
import json
import random
from typing import Any

import pytest

from slogger.tools import Field, Filters, Predicate, ToolError, all_of, any_of, not_, query, scan


@pytest.mark.parametrize("backend", ["python", "polars"])
@pytest.mark.parametrize("order", ["concat", "time"])
def test_file_selection_matches_legacy_metadata_and_cursor_replay(tmp_path, backend, order):
    if backend == "polars":
        pytest.importorskip("polars")
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    first.write_text(
        'malformed\n{"timestamp":"2026-01-02T00:00:00Z","level":"ERROR","n":1}\n'
        '{"timestamp":"2026-01-04T00:00:00Z","level":"ERROR","n":3}\n'
    )
    second.write_text(
        '{"timestamp":"2026-01-01T00:00:00Z","level":"INFO","n":0}\n'
        '{"timestamp":"2026-01-03T00:00:00Z","level":"ERROR","n":2}\n'
    )
    sources = [first, second]
    predicate = Field("level").eq("ERROR")
    filters = Filters(predicate=predicate)
    legacy = query(sources, filters=filters, order=order)
    result = scan(sources, order=order).filter(predicate).execute(backend=backend)
    assert result.records == legacy.records
    assert result.warnings == legacy.warnings
    assert result.metadata["skipped_lines"] == legacy.skipped_lines == 1
    assert result.metadata["input_rows"] == 4
    collected, cursor = [], None
    for _ in range(5):
        page = query(sources, filters=filters, order=order, limit=1, after=cursor)
        collected.extend(page.records)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None
    assert collected == result.records


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_seeded_sparse_nested_typed_expression_parity(backend, tmp_path):
    if backend == "polars":
        pytest.importorskip("polars")
    rng = random.Random(20261003)
    values = [None, False, True, -1, 0, 1, 3, 3.5, 8, "3", "ada", "bob"]
    records = []
    for _ in range(1400):
        record: dict[str, Any] = {}
        for key in ("amount", "user", "disabled"):
            if rng.randrange(4):
                record[key] = rng.choice(values)
        if rng.randrange(3):
            record["request"] = {"method": rng.choice(["POST", "GET", None])}
        records.append(record)
    path = tmp_path / "sparse.log"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    predicate = all_of(
        any_of(Field("amount").ge(3), Field("user").in_(["ada", "bob"])),
        not_(Field("disabled").eq(True)),
        any_of(Field("request", "method").eq("POST"), Field("request").missing()),
    )
    reference = query(path, filters=Filters(predicate=predicate)).records
    result = scan(path).filter(predicate).execute(backend=backend)
    assert result.records == reference
    assert result.metadata["input_rows"] == len(records)


def test_legacy_conversion_and_custom_predicates_remain_on_legacy_path():
    class Even(Predicate):
        def compile(self):
            return lambda record: record["n"] % 2 == 0

        def explain(self):
            return {"custom": "even"}

    records = [{"n": 2, "amount": "99"}, {"n": 3, "amount": 100}, {"n": 4, "amount": 100}]
    converted = Filters.from_mapping({"where": [{"key": "amount", "op": ">=", "value": 99}]})
    selected = query(records, filters=converted).records
    assert len(selected) == 3
    assert query(records, filters=Filters(predicate=Even())).records == [
        {"n": 2, "amount": "99", "_id": "mem:0"},
        {"n": 4, "amount": 100, "_id": "mem:2"},
    ]
    for backend in ("python", "polars"):
        with pytest.raises(ToolError) as failure:
            scan(records).filter(Even()).execute(backend=backend)
        assert failure.value.code == "expression_unsupported"


def test_native_failure_and_limit_close_owned_file_handles(tmp_path, monkeypatch):
    pytest.importorskip("polars")
    from slogger.tools import sum_of

    path = tmp_path / "app.log"
    path.write_text('{"v":1}\n{"v":"bad"}\n')
    opened, real_open = [], builtins.open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", tracking_open)
    assert scan(path).limit(1).execute(backend="polars").records == [{"v": 1, "_id": f"{path}:1"}]
    assert opened and all(handle.closed for handle in opened)
    with pytest.raises(ToolError) as failure:
        scan(path).aggregate(total=sum_of(Field("v"))).execute(backend="polars")
    assert failure.value.code == "data_incompatible"
    assert all(handle.closed for handle in opened)


def test_presence_only_paths_do_not_require_supported_value_domains():
    pytest.importorskip("polars")
    records = [{}, {"x": None}, {"x": {"a": 1}}, {"x": [True, "mixed", {}]}, {"x": 2**100}]
    for predicate in (
        Field("x").exists(),
        Field("x").missing(),
        all_of(Field("x").exists(), Field("x", "a").eq(1)),
    ):
        plan = scan(records).filter(predicate)
        assert plan.execute(backend="polars").records == plan.execute().records
    # A value predicate on the identical path still requires value binding.
    with pytest.raises(ToolError) as failure:
        scan(records).filter(all_of(Field("x").exists(), Field("x").eq(1))).execute(
            backend="polars"
        )
    assert failure.value.code == "data_incompatible"
