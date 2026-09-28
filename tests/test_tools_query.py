from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.filters import Filters
from slogger.tools.query import query

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_query_memory_api():
    page = query([{"message": "x", "level": "INFO"}], filters=Filters(level_min=20))
    assert len(page.records) == 1
    assert page.records[0]["_id"] == "mem:0"
    assert page.next_cursor is None
    assert page.skipped_lines == 0


def test_query_limit_and_after():
    page = query(BASIC, limit=2)
    assert [row["_id"] for row in page.records] == [f"{BASIC}:1", f"{BASIC}:2"]
    assert page.next_cursor == f"{BASIC}:2"
    page2 = query(BASIC, limit=2, after=page.next_cursor)
    assert [row["_id"] for row in page2.records] == [f"{BASIC}:3", f"{BASIC}:4"]


def test_truncation_preserves_cursor():
    rows = [{"message": "long message"}, {"message": "next message"}]
    first = query(rows, limit=1, truncate=2)
    assert first.records[0]["message"] == "lo..."
    assert first.records[0]["_id"] == "mem:0"
    assert query(rows, after=first.next_cursor).records[0]["message"] == "next message"


def test_last_time_page_has_merge_cursor():
    rows = [{"message": "one"}, {"message": "two"}]
    page = query(rows, last=1, order="time", complete=False)
    assert page.next_cursor == "time;mem:2"
    assert query(rows, after=page.next_cursor, order="time").records == []


def test_poll_cursor_advances_over_nonmatching_records():
    rows = [{"level": "INFO"}, {"level": "DEBUG"}]
    page = query(rows, filters=Filters(level_min=40), complete=False)
    assert page.records == []
    assert page.next_cursor == "mem:1"
