from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.filters import Filters, level_number
from slogger.tools.reader import Reader
from slogger.tools.spans import SpanCollector
from slogger.tools.trace import build_trace, trace

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE = "tests/fixtures/logs/trace.log"
GROUPED = "tests/fixtures/logs/grouped.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_build_trace_keep_logs_false():
    records = list(Reader(TRACE))
    full = build_trace(records, "a" * 32, keep_logs=True)
    bare = build_trace(records, "a" * 32, keep_logs=False)
    assert bare.logs == []
    assert bare.spans[0].logs == []
    assert bare.spans[0].children[0].logs == []
    assert bare.status == full.status
    assert bare.duration_ms == full.duration_ms
    assert bare.spans[0].span == full.spans[0].span


def test_span_collector_trace_log():
    collector = SpanCollector(keep_logs=False)
    for record in Reader(TRACE):
        tid = record.get("trace_id")
        if isinstance(tid, str):
            collector.add(record, tid)
    groups = list(collector.finish())
    assert len(groups) == 3
    by_id = dict(groups)
    assert by_id["b" * 32].status == "unknown"
    assert "missing_parent:4444444444444444" in by_id["c" * 32].warnings


def test_span_collector_selection_keeps_full_tree():
    collector = SpanCollector(keep_logs=False)
    for record in Reader(TRACE):
        tid = record.get("trace_id")
        if isinstance(tid, str):
            collector.add(record, tid)
    selected = list(
        collector.finish(predicate=Filters(level_min=level_number("ERROR")).matches)
    )
    assert len(selected) == 1
    group_key, tr = selected[0]
    assert group_key == "a" * 32
    root = tr.spans[0]
    assert root.span == "checkout"
    assert root.started == "2026-09-26T18:00:00.000Z"
    assert root.status == "ok"


def test_span_collector_max_groups():
    collector = SpanCollector(keep_logs=False, max_groups=2)
    for record in Reader(TRACE):
        tid = record.get("trace_id")
        if isinstance(tid, str):
            collector.add(record, tid)
    groups = list(collector.finish())
    assert collector.groups_seen == 3
    assert collector.groups_capped is True
    assert len(groups) == 2


def test_trace_group_by_request_id():
    result = trace(GROUPED, group_by=("request_id", "r1"))
    assert result.trace_id is None
    assert result.group == {"key": "request_id", "value": "r1"}
    assert len(result.spans) == 1
    assert result.spans[0].span == "job"
    assert result.spans[0].status == "unknown"
    assert [log["message"] for log in result.logs] == ["a", "b"]
    assert result.matched_traces == 1
