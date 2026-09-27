from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.failures import failures

REPO_ROOT = Path(__file__).resolve().parents[1]
ERRORS = "tests/fixtures/logs/errors.log"
BASIC = "tests/fixtures/logs/basic.log"
TRACE = "tests/fixtures/logs/trace.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_failures_errors_log():
    payload = failures(ERRORS)
    assert payload["error_records"] == 5
    assert payload["failed_spans"] == 1
    assert payload["total_groups"] == 5
    g0 = payload["groups"][0]
    assert g0["kind"] == "record"
    assert g0["error_type"] == "TimeoutError"
    assert g0["frame"] == "pay.py:48"
    assert g0["count"] == 2
    assert len(g0["samples"]) == 2
    assert g0["samples"][0]["_id"].endswith(":1")
    assert g0["samples"][1]["_id"].endswith(":2")
    assert [g["frame"] for g in payload["groups"]] == [
        "pay.py:48",
        "pay.py:70",
        "pay.py:9",
        "a.py:3",
        "pay.py:60",
    ]


def test_failures_samples_and_show_trace():
    payload = failures(ERRORS, samples=1, show_trace=True)
    assert all(len(g["samples"]) == 1 for g in payload["groups"])
    span = next(g for g in payload["groups"] if g["kind"] == "span")
    assert span["frame"] == "pay.py:9"
    assert span["trace_ids"] == ["b" * 32]


def test_failures_basic_and_trace():
    basic = failures(BASIC)
    assert basic["error_records"] == 1
    assert basic["failed_spans"] == 0
    assert basic["groups"][0]["error_type"] == "TimeoutError"
    assert basic["groups"][0]["frame"] == "pay.py:48"
    tr = failures(TRACE)
    assert tr["error_records"] == 0
    assert tr["failed_spans"] == 1
    assert tr["groups"][0]["frame"] == "shop.py:9"
    assert tr["groups"][0]["error_type"] == "TimeoutError"


def test_failures_top_and_cap():
    top = failures(ERRORS, top=2)
    assert top["returned"] == 2
    assert top["total_groups"] == 5
    capped = failures(ERRORS, max_groups=2)
    assert capped["groups_capped"] is True
