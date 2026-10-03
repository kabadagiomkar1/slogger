"""Execution adapters preserve query semantics at caller seams."""

import builtins
import json
import random
from typing import Any

import pytest

from slogger.tools import Field, ToolError, all_of, any_of, not_, scan


@pytest.mark.parametrize("backend", ["python", "polars"])
@pytest.mark.parametrize("order", ["concat", "time"])
def test_file_selection_accounts_for_decoding_and_source_order(tmp_path, backend, order):
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
    result = scan(sources, order=order).filter(predicate).execute(backend=backend)
    assert [row["n"] for row in result.records] == ([1, 3, 2] if order == "concat" else [1, 2, 3])
    assert result.warnings == []
    assert result.metadata["skipped_lines"] == 1
    assert result.metadata["input_rows"] == 4


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
    reference = scan(path).filter(predicate).execute().records
    result = scan(path).filter(predicate).execute(backend=backend)
    assert result.records == reference
    assert result.metadata["input_rows"] == len(records)


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
    assert scan(path).limit(1).execute(backend="polars").records == [{"v": 1}]
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
