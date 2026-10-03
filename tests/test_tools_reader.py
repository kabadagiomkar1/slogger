from pathlib import Path

import pytest

from slogger.tools import scan

REPO_ROOT = Path(__file__).resolve().parents[1]
MALFORMED = "tests/fixtures/logs/malformed.log"
ROTATED_GLOB = "tests/fixtures/logs/rotated/app.log*"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_reader_malformed_skips_and_ids():
    reader = scan(MALFORMED).execute()
    rows = reader.records
    assert [row["_id"] for row in rows] == [f"{MALFORMED}:{n}" for n in (1, 5, 6, 7, 8)]
    assert reader.metadata["skipped_lines"] == 2
    assert [row["message"] for row in rows] == [
        "one",
        "two",
        "no timestamp",
        "bad timestamp",
        "three",
    ]


def test_reader_rotated_glob_messages():
    rows = scan(ROTATED_GLOB).execute().records
    assert [row["message"] for row in rows] == ["r1", "r2", "r3", "r4", "r5", "r6"]
