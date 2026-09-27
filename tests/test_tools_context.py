from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.context import context
from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters, level_number

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE = "tests/fixtures/logs/trace.log"
BASIC = "tests/fixtures/logs/basic.log"
A = "tests/fixtures/logs/interleaved/a.log"
B = "tests/fixtures/logs/interleaved/b.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_context_same_trace():
    page = context(TRACE, record_id=f"{TRACE}:4", before=1, after=1)
    assert [r["_id"] for r in page.records] == [f"{TRACE}:{n}" for n in range(1, 8)]
    anchor = next(r for r in page.records if r.get("_anchor"))
    assert anchor["_id"] == f"{TRACE}:4"
    assert page.context_meta is not None
    assert page.context_meta["trace_records"] == 7


def test_context_neighbours_and_filters():
    page = context(
        TRACE, record_id=f"{TRACE}:9", before=2, after=2, same_trace=False
    )
    assert [r["_id"] for r in page.records] == [
        f"{TRACE}:{n}" for n in (7, 8, 9, 10, 11)
    ]
    page = context(
        BASIC,
        record_id=f"{BASIC}:3",
        before=1,
        after=1,
        filters=Filters(level_min=level_number("WARNING")),
    )
    assert [r["_id"] for r in page.records] == [f"{BASIC}:3", f"{BASIC}:4"]


def test_context_trace_cap_and_errors():
    page = context(TRACE, record_id=f"{TRACE}:9", max_trace=1)
    assert page.context_meta is not None
    assert page.context_meta["trace_capped"] is True
    with pytest.raises(ToolError) as exc:
        context(TRACE, record_id=f"{TRACE}:999")
    assert exc.value.code == "record_not_found"
    with pytest.raises(ValueError):
        context(TRACE, record_id="bad")


def test_context_order_time():
    page = context(
        [A, B], record_id=f"{B}:2", before=1, after=1, order="time"
    )
    assert [r["message"] for r in page.records] == ["a2", "b2", "b3"]
    concat = context(
        [A, B], record_id=f"{B}:2", before=1, after=1, order="concat"
    )
    assert [r["message"] for r in concat.records] == ["b1", "b2", "b3"]
