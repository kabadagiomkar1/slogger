from __future__ import annotations

from datetime import timezone
from pathlib import Path

import pytest

from slogger.tools import CursorError, Reader, parse_id, parse_timestamp, resolve_sources

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
MALFORMED = "tests/fixtures/logs/malformed.log"
ROTATED_GLOB = "tests/fixtures/logs/rotated/app.log*"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_reader_basic_ids_and_count():
    rows = list(Reader(BASIC))
    assert len(rows) == 6
    assert [row["_id"] for row in rows] == [f"{BASIC}:{n}" for n in range(1, 7)]
    assert rows[-1]["_id"].endswith(":6")
    assert rows[0]["message"] == "started"


def test_reader_memory_copies_and_ids():
    src = [{"message": "a"}, {"message": "b"}]
    rows = list(Reader(src))
    assert rows[0] is not src[0]
    assert [row["_id"] for row in rows] == ["mem:0", "mem:1"]


def test_reader_malformed_skips_and_ids():
    reader = Reader(MALFORMED)
    rows = list(reader)
    assert [row["_id"] for row in rows] == [f"{MALFORMED}:{n}" for n in (1, 5, 6, 7, 8)]
    assert reader.skipped_lines == 2
    assert [row["message"] for row in rows] == [
        "one",
        "two",
        "no timestamp",
        "bad timestamp",
        "three",
    ]


def test_reader_complete_false_holds_trailing_partial():
    reader = Reader(MALFORMED, complete=False)
    rows = list(reader)
    assert [row["_id"] for row in rows] == [f"{MALFORMED}:{n}" for n in (1, 5, 6, 7)]
    assert reader.skipped_lines == 2
    assert rows[-1]["message"] == "bad timestamp"


def test_resolve_sources_rotation_order():
    resolved = resolve_sources(ROTATED_GLOB)
    assert resolved == [
        "tests/fixtures/logs/rotated/app.log.2026-09-25",
        "tests/fixtures/logs/rotated/app.log.2026-09-26",
        "tests/fixtures/logs/rotated/app.log",
    ]


def test_reader_rotated_glob_messages():
    rows = list(Reader(ROTATED_GLOB))
    assert [row["message"] for row in rows] == ["r1", "r2", "r3", "r4", "r5", "r6"]


def test_reader_after_across_rotated_files():
    after = "tests/fixtures/logs/rotated/app.log.2026-09-26:1"
    rows = list(Reader(ROTATED_GLOB, after=after))
    assert [row["message"] for row in rows] == ["r4", "r5", "r6"]


def test_reader_after_past_end_raises():
    with pytest.raises(CursorError) as exc:
        Reader("tests/fixtures/logs/rotated/app.log", after="tests/fixtures/logs/rotated/app.log:9")
    assert exc.value.code == "cursor_invalid"


def test_reader_after_unknown_source_raises():
    with pytest.raises(CursorError) as exc:
        Reader(ROTATED_GLOB, after="nope.log:1")
    assert exc.value.code == "cursor_invalid"


def test_reader_memory_after():
    rows = list(Reader([{"message": "a"}, {"message": "b"}], after="mem:0"))
    assert len(rows) == 1
    assert rows[0]["_id"] == "mem:1"
    assert rows[0]["message"] == "b"


def test_parse_timestamp_variants():
    moment = parse_timestamp("2026-09-26T16:00:00.000Z")
    assert moment is not None
    assert moment.tzinfo == timezone.utc
    assert moment.year == 2026
    assert parse_timestamp("not-a-date") is None
    assert parse_timestamp(None) is None
    naive = parse_timestamp("2026-09-26T16:00:00")
    assert naive is not None
    assert naive.tzinfo == timezone.utc
    us = parse_timestamp("2026-09-26T16:00:00.239123Z")
    assert us is not None
    assert us.microsecond == 239123


def test_parse_id_windows_drive():
    assert parse_id(r"C:\logs\app.log:12") == (r"C:\logs\app.log", 12)


def test_reader_missing_file_raises_at_construction():
    with pytest.raises(FileNotFoundError):
        Reader("missing.log")
