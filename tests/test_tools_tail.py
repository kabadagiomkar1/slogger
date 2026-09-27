from __future__ import annotations

import json
from pathlib import Path

import pytest

from slogger.tools.filters import Filters, level_number
from slogger.tools.tail import follow, tail_once

REPO_ROOT = Path(__file__).resolve().parents[1]
MALFORMED = "tests/fixtures/logs/malformed.log"
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_tail_once_holds_partial_line():
    page = tail_once(MALFORMED)
    assert len(page.records) == 4
    assert page.next_cursor == f"{MALFORMED}:7"
    assert page.records[-1]["message"] == "bad timestamp"


def test_tail_once_resume_after_newline(tmp_path):
    src = Path(MALFORMED).read_bytes()
    target = tmp_path / "malformed.log"
    target.write_bytes(src)
    page = tail_once(str(target))
    assert page.next_cursor == f"{target}:7"
    target.write_bytes(src + b"\n")
    page2 = tail_once(str(target), after=f"{target}:7")
    assert len(page2.records) == 1
    assert page2.records[0]["message"] == "three"
    assert page2.next_cursor == f"{target}:8"


def test_follow_partial_then_complete(tmp_path):
    path = tmp_path / "live.log"
    first = {
        "timestamp": "2026-09-26T16:00:00.000Z",
        "level": "INFO",
        "logger": "app",
        "message": "a",
        "file": "a.py",
        "func": "f",
        "line": 1,
    }
    path.write_text(json.dumps(first) + "\n" + '{"message":"b"', encoding="utf-8")
    stop_at = {"n": 0}

    def stop():
        stop_at["n"] += 1
        return stop_at["n"] > 3

    rows = list(follow(str(path), lines=10, interval=0.01, stop=stop))
    assert [row["message"] for row in rows] == ["a"]

    with path.open("a", encoding="utf-8") as handle:
        handle.write("}\n")
    stop_at["n"] = 0
    rows = list(
        follow(str(path), lines=0, after=f"{path}:1", interval=0.01, stop=stop)
    )
    assert [row["message"] for row in rows] == ["b"]


def test_follow_rotation(tmp_path):
    path = tmp_path / "app.log"
    rec = {
        "timestamp": "2026-09-26T16:00:00.000Z",
        "level": "INFO",
        "logger": "app",
        "message": "old",
        "file": "a.py",
        "func": "f",
        "line": 1,
    }
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    reopens: list[str] = []
    state = {"phase": 0}

    def stop():
        if state["phase"] == 0:
            path.rename(tmp_path / "app.log.2026-09-26")
            new_rec = dict(rec, message="new")
            path.write_text(json.dumps(new_rec) + "\n", encoding="utf-8")
            state["phase"] = 1
            return False
        if state["phase"] == 1:
            state["phase"] = 2
            return False
        return True

    rows = list(
        follow(
            str(path),
            lines=0,
            interval=0.01,
            stop=stop,
            on_reopen=reopens.append,
        )
    )
    assert "new" in [row["message"] for row in rows]
    assert reopens == [str(path)]
    assert any(row["_id"] == f"{path}:1" and row["message"] == "new" for row in rows)


def test_follow_backlog_lines():
    stop_at = {"n": 0}

    def stop():
        stop_at["n"] += 1
        return True

    rows = list(follow(BASIC, lines=1, interval=0.01, stop=stop))
    assert rows[0]["message"] == "stopped"


def test_follow_filters_backlog():
    stop_at = {"n": 0}

    def stop():
        stop_at["n"] += 1
        return True

    rows = list(
        follow(
            BASIC,
            filters=Filters(level_min=level_number("WARNING")),
            lines=10,
            interval=0.01,
            stop=stop,
        )
    )
    assert [row["message"] for row in rows] == ["retrying", "charge failed"]
