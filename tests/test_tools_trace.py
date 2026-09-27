from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters, Where
from slogger.tools.trace import build_trace, find_trace_id, render_trace, trace

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE = "tests/fixtures/logs/trace.log"
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_trace_aaaa():
    result = trace(TRACE, trace_id="aaaa")
    assert result.trace_id == "a" * 32
    assert result.status == "error"
    assert result.duration_ms == 410.0
    assert result.warnings == []
    root = result.spans[0]
    assert root.span == "checkout"
    assert root.status == "ok"
    assert root.duration_ms == 410.0
    assert root.started == "2026-09-26T18:00:00.000Z"
    assert root.ended == "2026-09-26T18:00:00.410Z"
    assert root.fields == {"user": "ada"}
    assert [log["message"] for log in root.logs] == ["connected", "rolling back"]
    child = root.children[0]
    assert child.span == "charge"
    assert child.status == "error"
    assert child.error_type == "TimeoutError"
    assert child.error == "boom"
    assert child.duration_ms == 380.0
    assert child.fields == {"user": "ada", "order_id": "42"}
    assert [log["message"] for log in child.logs] == ["charging"]


def test_trace_bbbb_unfinished():
    result = trace(TRACE, trace_id="bbbb")
    root = result.spans[0]
    assert root.status == "unknown"
    assert root.ended is None
    assert root.duration_ms is None
    assert [log["message"] for log in root.logs] == ["working"]
    assert result.status == "unknown"
    assert result.ended is None


def test_trace_cccc_orphan_and_duplicates():
    result = trace(TRACE, trace_id="cccc")
    assert len(result.spans) == 2
    child, other = result.spans
    assert child.span == "child"
    assert child.orphan is True
    assert child.parent_span_id == "9999999999999999"
    assert child.status == "ok"
    assert child.duration_ms == 100.0
    assert other.span == "other"
    assert other.missing_start is True
    assert other.started is None
    assert other.ended == "2026-09-26T18:02:00.200Z"
    assert [log["message"] for log in result.logs] == ["loose"]
    assert "missing_parent:4444444444444444" in result.warnings
    assert "duplicate_end:4444444444444444" in result.warnings
    assert result.status == "ok"
    assert result.duration_ms is None


def test_trace_short_prefix_raises():
    with pytest.raises(ValueError):
        trace(TRACE, trace_id="a")


def test_find_trace_ambiguous_and_missing():
    records = [
        {"trace_id": "abcd1111111111111111111111111111", "message": "a"},
        {"trace_id": "abcd2222222222222222222222222222", "message": "b"},
    ]
    with pytest.raises(ToolError) as exc:
        find_trace_id(records, prefix="abcd")
    assert exc.value.code == "ambiguous_trace"
    candidates = exc.value.extra["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 2
    with pytest.raises(ToolError) as exc:
        find_trace_id(records, prefix="ffff")
    assert exc.value.code == "trace_not_found"


def test_trace_by_where():
    result = trace(TRACE, filters=Filters(where=(Where("order_id", "=", "42"),)))
    assert result.trace_id == "a" * 32
    assert result.matched_records == 3
    assert result.matched_traces == 1


def test_trace_by_grep_loose():
    result = trace(TRACE, filters=Filters(grep="loose"))
    assert result.trace_id == "c" * 32


def test_trace_no_trace_on_match():
    with pytest.raises(ToolError) as exc:
        trace(BASIC, filters=Filters(grep="started"))
    assert exc.value.code == "no_trace_on_match"


def test_build_trace_missing_timestamps_stable():
    records = [
        {"trace_id": "d" * 32, "span_id": "1" * 16, "event": "span.start", "span": "x"},
        {"trace_id": "d" * 32, "span_id": "1" * 16, "message": "mid"},
        {
            "trace_id": "d" * 32,
            "span_id": "1" * 16,
            "event": "span.end",
            "status": "ok",
            "duration_ms": 1,
        },
    ]
    result = build_trace(records, "d" * 32)
    assert [log["message"] for log in result.spans[0].logs] == ["mid"]


def test_render_trace_aaaa():
    text = render_trace(trace(TRACE, trace_id="aaaa"), color=False)
    assert text.splitlines()[0] == (
        "trace aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  2026-09-26T18:00:00.000Z  "
        "total 410 ms  status=error"
    )
    assert "checkout" in text
    assert "├─" in text or "└─" in text
    assert "charge" in text
    assert "error" in text
    assert "connected" in text
    text_no_logs = render_trace(trace(TRACE, trace_id="aaaa"), color=False, logs=False)
    assert "connected" not in text_no_logs


def test_render_unfinished_and_orphan():
    text = render_trace(trace(TRACE, trace_id="bbbb"), color=False)
    assert "unknown" in text
    assert "?" in text
    text = render_trace(trace(TRACE, trace_id="cccc"), color=False)
    assert "(orphan)" in text
