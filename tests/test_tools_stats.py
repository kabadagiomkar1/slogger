from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.filters import Filters, Where
from slogger.tools.query import summary
from slogger.tools.stats import percentile, stats

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
DURATIONS = "tests/fixtures/logs/durations.log"
TRACE = "tests/fixtures/logs/trace.log"
GROUPED = "tests/fixtures/logs/grouped.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_percentile_examples():
    assert percentile([5, 100, 380, 410], 50) == 100
    assert percentile([5, 100, 380, 410], 95) == 410
    assert percentile(list(range(1, 11)), 95) == 10
    assert percentile(list(range(1, 11)), 50) == 5
    assert percentile([7], 99) == 7
    assert percentile(sorted([3, 1]), 50) == 1


def test_stats_basic_and_durations():
    assert stats(BASIC)["totals"] == {
        "records": 6,
        "levels": {"INFO": 3, "DEBUG": 1, "WARNING": 1, "ERROR": 1},
    }
    totals = stats(DURATIONS, spans=True)["totals"]
    assert totals["spans"] == 12
    assert totals["completed"] == 12
    assert totals["failed"] == 1
    assert totals["unfinished"] == 0
    assert totals["missing_start"] == 0
    assert totals["invalid_durations"] == 2
    assert totals["duration_ms"]["count"] == 10
    assert totals["duration_ms"]["min"] == 1.0
    assert totals["duration_ms"]["max"] == 10.0
    assert totals["duration_ms"]["mean"] == 5.5
    assert totals["duration_ms"]["p50"] == 5.0
    assert totals["duration_ms"]["p95"] == 10.0
    assert totals["duration_ms"]["p99"] == 10.0
    groups = stats(DURATIONS, spans=True)["groups"]
    assert len(groups) == 1
    assert groups[0]["value"] == "work"
    assert groups[0]["spans"] == 12


def test_stats_buckets_and_trace():
    buckets = stats(DURATIONS, spans=True, bucket="1m")["totals"]["buckets"]
    assert buckets[0]["start"] == "2026-09-26T12:00:00.000Z"
    assert buckets[0]["spans"] == 5
    assert buckets[0]["duration_ms"]["count"] == 5
    assert buckets[0]["duration_ms"]["p50"] == 3.0
    assert buckets[1]["start"] == "2026-09-26T12:01:00.000Z"
    assert buckets[1]["spans"] == 5
    assert buckets[1]["duration_ms"]["p50"] == 8.0
    assert buckets[2]["start"] == "2026-09-26T12:02:00.000Z"
    assert buckets[2]["spans"] == 2
    assert buckets[2]["duration_ms"]["count"] == 0
    assert buckets[2]["duration_ms"]["p50"] is None

    totals = stats(TRACE, spans=True)["totals"]
    assert totals["spans"] == 5
    assert totals["unfinished"] == 1
    assert totals["missing_start"] == 1
    assert totals["failed"] == 1
    assert totals["duration_ms"]["count"] == 4
    assert totals["duration_ms"]["p50"] == 100.0
    assert totals["duration_ms"]["p95"] == 410.0
    assert totals["duration_ms"]["mean"] == 223.75


def test_stats_group_by_and_cap():
    payload = stats(GROUPED, group_by="request_id")
    assert [g["records"] for g in payload["groups"]] == [3, 1, 1, 1, 1]
    assert payload["ungrouped"] == 1
    capped = stats(DURATIONS, spans=True, max_samples=3)["totals"]["duration_ms"]
    assert capped["percentiles_capped"] is True
    assert capped["count"] == 10
    assert capped["max"] == 10.0
    assert capped["p50"] == 2.0


def test_summary_and_empty():
    payload = summary(BASIC, filters=Filters(where=(Where("user", "=", "ada"),)))
    assert payload["matched"] == 3
    assert payload["first_id"] == f"{BASIC}:3"
    assert payload["last_id"] == f"{BASIC}:5"
    assert payload["first_timestamp"] == "2026-09-26T16:00:02.000Z"
    assert payload["last_timestamp"] == "2026-09-26T16:00:03.000Z"
    assert payload["loggers"] == {"app.pay": 3}
    empty = stats([], spans=True)
    assert empty["totals"]["records"] == 0
    assert empty["totals"]["duration_ms"]["count"] == 0
    assert empty["totals"]["duration_ms"]["p50"] is None


@pytest.mark.parametrize("bucket", [0, -1, True])
def test_stats_rejects_invalid_integer_buckets(bucket):
    with pytest.raises(ValueError, match="bucket"):
        stats([], bucket=bucket)
