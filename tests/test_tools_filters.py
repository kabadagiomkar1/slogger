from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from slogger.tools.filters import (
    Filters,
    Where,
    level_number,
    parse_relative_or_iso,
    parse_where,
)
from slogger.tools.reader import Reader

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
MALFORMED = "tests/fixtures/logs/malformed.log"
TRACE = "tests/fixtures/logs/trace.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def basic():
    return list(Reader(BASIC))


def _messages(rows, filters: Filters):
    return [row["message"] for row in rows if filters.matches(row)]


def _ids(rows, filters: Filters):
    return [row["_id"] for row in rows if filters.matches(row)]


def test_parse_where_ops_and_values():
    assert parse_where("user=ada") == Where("user", "=", "ada")
    assert parse_where("amount>=99") == Where("amount", ">=", "99")
    assert parse_where("message~^charg") == Where("message", "~", "^charg")
    assert parse_where("note=a=b") == Where("note", "=", "a=b")
    assert parse_where("user=") == Where("user", "=", "")


def test_parse_where_rejects_spaced_and_invalid():
    for token in ("=x", "user", "user = ada"):
        with pytest.raises(ValueError):
            parse_where(token)


def test_where_filters_basic(basic):
    assert _messages(basic, Filters(where=(Where("user", "=", "ada"),))) == [
        "charging",
        "retrying",
        "charge failed",
    ]
    assert _messages(basic, Filters(where=(Where("amount", "=", "99.5"),))) == ["charging"]
    assert _messages(basic, Filters(where=(Where("amount", "=", "99"),))) == []
    assert _messages(basic, Filters(where=(Where("amount", ">", "99"),))) == ["charging"]
    assert _messages(basic, Filters(where=(Where("port", ">", "5000"),))) == ["connected"]
    assert _messages(basic, Filters(where=(Where("debug", "=", "false"),))) == ["started"]
    assert _messages(basic, Filters(where=(Where("note", "=", "null"),))) == ["stopped"]
    assert _messages(basic, Filters(where=(Where("tags", "~", "billing"),))) == ["charge failed"]
    assert _messages(
        basic, Filters(where=(Where("tags", "=", '["billing","retry"]'),))
    ) == ["charge failed"]


def test_missing_key_and_existence(basic):
    assert _messages(basic, Filters(where=(Where("user", "!=", "ada"),))) == []
    assert _messages(basic, Filters(missing=("user",))) == ["started", "connected", "stopped"]
    assert _messages(basic, Filters(has=("order_id",))) == [
        "charging",
        "retrying",
        "charge failed",
    ]


def test_timestamp_string_compare(basic):
    assert _messages(
        basic, Filters(where=(Where("timestamp", ">=", "2026-09-26T16:00:02.000Z"),))
    ) == ["charging", "retrying", "charge failed", "stopped"]


def test_level_and_logger(basic):
    assert _messages(basic, Filters(level_min=level_number("WARNING"))) == [
        "retrying",
        "charge failed",
    ]
    assert _messages(basic, Filters(level_exact=level_number("INFO"))) == [
        "started",
        "charging",
        "stopped",
    ]
    assert level_number("warning") == 30
    assert level_number("30") == 30
    with pytest.raises(ValueError):
        level_number("nope")
    assert _messages(basic, Filters(logger="app")) == [
        "started",
        "connected",
        "charging",
        "retrying",
        "charge failed",
        "stopped",
    ]
    assert _messages(basic, Filters(logger="app.pay")) == [
        "charging",
        "retrying",
        "charge failed",
    ]
    assert _messages(basic, Filters(logger="app.p")) == []


def test_grep_and_since_until(basic):
    assert _messages(basic, Filters(grep="charg")) == ["charging", "charge failed"]
    since = parse_relative_or_iso("2026-09-26T16:00:02.000Z")
    until = parse_relative_or_iso("2026-09-26T16:00:02.000Z")
    assert _messages(basic, Filters(since=since)) == [
        "charging",
        "retrying",
        "charge failed",
        "stopped",
    ]
    assert _messages(basic, Filters(until=until)) == [
        "started",
        "connected",
        "charging",
        "retrying",
    ]


def test_invalid_grep_raises_value_error():
    with pytest.raises(ValueError, match="invalid --grep"):
        Filters(grep="[")


def test_since_excludes_bad_timestamps():
    rows = list(Reader(MALFORMED))
    since = parse_relative_or_iso("2026-09-26T17:00:00.000Z")
    assert _messages(rows, Filters(since=since)) == ["one", "two", "three"]
    assert len([row for row in rows if Filters().matches(row)]) == 5


def test_parse_relative_or_iso():
    now = datetime(2026, 9, 26, 16, 0, 0, tzinfo=timezone.utc)
    assert parse_relative_or_iso("10m", now=now) == datetime(
        2026, 9, 26, 15, 50, 0, tzinfo=timezone.utc
    )
    assert parse_relative_or_iso("2h", now=now) == datetime(
        2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc
    )
    assert parse_relative_or_iso("1d", now=now) == datetime(
        2026, 9, 25, 16, 0, 0, tzinfo=timezone.utc
    )
    assert parse_relative_or_iso("30s", now=now) == datetime(
        2026, 9, 26, 15, 59, 30, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError):
        parse_relative_or_iso("10x")
    assert parse_relative_or_iso("2026-09-26T16:00:00Z") == datetime(
        2026, 9, 26, 16, 0, 0, tzinfo=timezone.utc
    )


def test_exclude_events():
    rows = list(Reader(TRACE))
    kept = [row for row in rows if Filters(exclude_events=True).matches(row)]
    assert len(kept) == 5
    assert [row["message"] for row in kept] == [
        "connected",
        "charging",
        "rolling back",
        "working",
        "loose",
    ]
