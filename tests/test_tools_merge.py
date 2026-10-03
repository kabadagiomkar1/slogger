from pathlib import Path

import pytest

from slogger.tools import scan

REPO_ROOT = Path(__file__).resolve().parents[1]
A = "tests/fixtures/logs/interleaved/a.log"
B = "tests/fixtures/logs/interleaved/b.log"
ROTATED = "tests/fixtures/logs/rotated/app.log*"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_order_time_merge_sequence_and_warnings():
    page = scan([A, B], order="time").execute()
    assert [r["message"] for r in page.records] == ["a1", "b1", "a2", "b2", "b3", "b4", "a3", "a4"]
    assert page.warnings == [f"out_of_order:{A}:1", f"untimestamped:{B}:1"]
    concat = scan([A, B], order="concat").execute()
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


def test_mixed_precision_merge_order():
    records = [
        {"timestamp": "2026-09-26T10:00:00Z", "message": "first"},
        {"timestamp": "2026-09-26T10:00:00.000500+00:00", "message": "second"},
    ]
    page = scan([records[:1], records[1:]], order="time").execute()
    assert [r["message"] for r in page.records] == ["first", "second"]


def test_rotated_glob_time_order():
    page = scan(ROTATED, order="time").execute()
    assert [r["message"] for r in page.records] == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert page.warnings == []
