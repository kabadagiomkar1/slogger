from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.tree import tree

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE = "tests/fixtures/logs/trace.log"
GROUPED = "tests/fixtures/logs/grouped.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_tree_default():
    payload = tree(TRACE)
    assert payload["schema_version"] == 1
    assert payload["total"] == 3
    assert payload["returned"] == 3
    assert payload["truncated"] is False
    ids = [row["trace_id"] for row in payload["traces"]]
    assert ids == ["a" * 32, "b" * 32, "c" * 32]
    a, b, c = payload["traces"]
    assert a["spans"] == 2
    assert a["completed"] == 2
    assert a["failed"] == 1
    assert a["unfinished"] == 0
    assert a["status"] == "error"
    assert a["duration_ms"] == 410.0
    assert b["spans"] == 1
    assert b["unfinished"] == 1
    assert b["status"] == "unknown"
    assert b["duration_ms"] is None
    assert c["roots"] == 2
    assert c["spans"] == 2
    assert c["completed"] == 1
    assert c["missing_start"] == 1
    assert c["warnings"] == 2
    assert c["status"] == "ok"
    assert c["duration_ms"] is None


def test_tree_filters_and_sort():
    assert [r["trace_id"] for r in tree(TRACE, status="error")["traces"]] == ["a" * 32]
    assert [r["trace_id"] for r in tree(TRACE, slower_than_ms=400)["traces"]] == [
        "a" * 32
    ]
    empty = tree(TRACE, slower_than_ms=500)
    assert empty["total"] == 0
    assert empty["traces"] == []
    ordered = tree(TRACE, sort="duration")
    assert [r["trace_id"] for r in ordered["traces"]] == [
        "a" * 32,
        "b" * 32,
        "c" * 32,
    ]
    top = tree(TRACE, top=1)
    assert top["returned"] == 1
    assert top["total"] == 3
    assert top["truncated"] is True
    assert [r["trace_id"] for r in tree(TRACE, span="charge")["traces"]] == ["a" * 32]


def test_tree_group_by_and_empty():
    payload = tree(GROUPED, group_by="request_id")
    assert payload["ungrouped"] == 1
    assert len(payload["traces"]) == 1
    row = payload["traces"][0]
    assert row["group"] == {"key": "request_id", "value": "r1"}
    assert row["spans"] == 1
    assert row["unfinished"] == 1
    empty = tree([])
    assert empty["total"] == 0
    assert empty["traces"] == []
