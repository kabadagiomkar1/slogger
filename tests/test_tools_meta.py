from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.filters import Filters, level_number
from slogger.tools.meta import meta

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
TRACE = "tests/fixtures/logs/trace.log"
MALFORMED = "tests/fixtures/logs/malformed.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_meta_basic():
    payload = meta(BASIC)
    assert payload["schema_version"] == 1
    assert payload["records"] == 6
    assert payload["levels"] == {"INFO": 3, "DEBUG": 1, "WARNING": 1, "ERROR": 1}
    assert payload["loggers"] == ["app", "app.db", "app.pay"]
    assert payload["spans"] == []
    assert payload["traces"] == 0
    assert payload["first_timestamp"] == "2026-09-26T16:00:00.000Z"
    assert payload["last_timestamp"] == "2026-09-26T16:00:04.000Z"


def test_meta_trace_file():
    payload = meta(TRACE)
    assert payload["traces"] == 3
    assert payload["spans"] == ["charge", "checkout", "child", "other"]


def test_meta_malformed():
    payload = meta(MALFORMED)
    assert payload["records"] == 5
    assert payload["skipped_lines"] == 2
    assert payload["first_timestamp"] == "2026-09-26T17:00:00.000Z"
    assert payload["last_timestamp"] == "2026-09-26T17:00:02.000Z"


def test_meta_honours_filters():
    payload = meta(BASIC, filters=Filters(level_min=level_number("ERROR")))
    assert payload["records"] == 1
