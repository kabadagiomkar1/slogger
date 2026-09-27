from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools import CursorError, meta, query, trace
from slogger.tools.reader import Reader

REPO_ROOT = Path(__file__).resolve().parents[1]
A = "tests/fixtures/logs/interleaved/a.log"
B = "tests/fixtures/logs/interleaved/b.log"
TRACE = "tests/fixtures/logs/trace.log"
ROTATED = "tests/fixtures/logs/rotated/app.log*"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_order_time_merge_sequence_and_warnings():
    page = query([A, B], order="time")
    assert [r["message"] for r in page.records] == [
        "a1",
        "b1",
        "a2",
        "b2",
        "b3",
        "b4",
        "a3",
        "a4",
    ]
    assert page.warnings == [
        f"out_of_order:{A}:1",
        f"untimestamped:{B}:1",
    ]
    concat = query([A, B], order="concat")
    assert [r["message"] for r in concat.records] == [
        "a1",
        "a2",
        "a3",
        "a4",
        "b1",
        "b2",
        "b3",
        "b4",
    ]


def test_order_time_cursors_resume_without_loss():
    first = query([A, B], order="time", limit=3)
    assert first.next_cursor == f"time;{A}:2;{B}:1"
    second = query([A, B], order="time", after=first.next_cursor, limit=3)
    assert [r["message"] for r in second.records] == ["b2", "b3", "b4"]
    third = query([A, B], order="time", after=second.next_cursor, limit=3)
    assert [r["message"] for r in third.records] == ["a3", "a4"]
    assert third.next_cursor is None
    merged = first.records + second.records + third.records
    assert [r["message"] for r in merged] == [
        "a1",
        "b1",
        "a2",
        "b2",
        "b3",
        "b4",
        "a3",
        "a4",
    ]


def test_order_time_cursor_validation():
    with pytest.raises(CursorError):
        query([A, B], order="time", after=f"{A}:2")
    with pytest.raises(CursorError):
        query([A, B], after=f"time;{A}:2;{B}:1")
    with pytest.raises(CursorError):
        query([A], order="time", after=f"time;{A}:2;{B}:1")


def test_order_time_last():
    page = query([A, B], order="time", last=2)
    assert [r["message"] for r in page.records] == ["a3", "a4"]
    assert page.next_cursor is None


def test_meta_and_trace_accept_order_time():
    assert meta([A, B], order="time")["records"] == 8
    timed = trace(TRACE, trace_id="aaaa", order="time")
    concat = trace(TRACE, trace_id="aaaa", order="concat")
    assert timed.to_dict() == concat.to_dict()


def test_mixed_precision_merge_order():
    records = [
        {"timestamp": "2026-09-26T10:00:00Z", "message": "first"},
        {
            "timestamp": "2026-09-26T10:00:00.000500+00:00",
            "message": "second",
        },
    ]
    page = query([records[:1], records[1:]], order="time")
    assert [r["message"] for r in page.records] == ["first", "second"]


def test_rotated_glob_time_order():
    page = query(ROTATED, order="time")
    assert [r["message"] for r in page.records] == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert page.warnings == []


def test_reader_cursor_helper():
    reader = Reader([A, B], order="time")
    rows = []
    for record in reader:
        rows.append(record["message"])
        if len(rows) == 3:
            break
    assert reader.cursor() == f"time;{A}:2;{B}:1"
