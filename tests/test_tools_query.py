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
