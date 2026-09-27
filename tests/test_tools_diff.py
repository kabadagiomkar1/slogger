from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.diff import diff
from slogger.tools.filters import Filters

REPO_ROOT = Path(__file__).resolve().parents[1]
A = "tests/fixtures/logs/interleaved/a.log"
B = "tests/fixtures/logs/interleaved/b.log"
BASIC = "tests/fixtures/logs/basic.log"
GROUPED = "tests/fixtures/logs/grouped.log"
TRACE = "tests/fixtures/logs/trace.log"
DURATIONS = "tests/fixtures/logs/durations.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_diff_basic_cases():
    payload = diff(A, B)
    assert payload["totals"]["records"] == {
        "before": 4,
        "after": 4,
        "abs": 0,
        "pct": 0.0,
    }
    payload = diff(BASIC, GROUPED)
    rec = payload["totals"]["records"]
    assert rec["before"] == 6
    assert rec["after"] == 8
    assert rec["abs"] == 2
    assert abs(rec["pct"] - (2 / 6 * 100)) < 1e-9


def test_diff_spans_and_groups():
    payload = diff(TRACE, DURATIONS, spans=True)
    assert payload["totals"]["spans"]["before"] == 5
    assert payload["totals"]["spans"]["after"] == 12
    p50 = payload["totals"]["duration_ms.p50"]
    assert p50["before"] == 100.0
    assert p50["after"] == 5.0
    assert p50["abs"] == -95.0
    assert p50["pct"] == -95.0
    assert payload["totals"]["failed"]["abs"] == 0

    payload = diff(BASIC, GROUPED, group_by="request_id")
    assert payload["groups"] == []
    assert payload["removed"] == []
    assert [ (g["type"], g["value"]) for g in payload["added"] ] == [
        ("array", '["r1"]'),
        ("null", None),
        ("number", 7.0),
        ("str", "r1"),
        ("str", "r2"),
    ]


def test_diff_zero_baseline_and_filters():
    payload = diff([], BASIC)
    assert payload["totals"]["records"] == {
        "before": 0,
        "after": 6,
        "abs": 6,
        "pct": None,
    }
    from datetime import datetime, timezone

    since = datetime(2026, 9, 26, 16, 0, 2, tzinfo=timezone.utc)
    payload = diff(BASIC, BASIC, filters=Filters(since=since))
    assert payload["before"]["records"] == payload["after"]["records"]
    assert payload["before"]["records"] < 6
