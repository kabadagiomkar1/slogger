from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.fields import fields

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_fields_basic_keys():
    payload = fields(BASIC)
    assert payload["schema_version"] == 1
    assert payload["scanned"] == 6
    assert payload["scan_capped"] is False
    user = payload["keys"]["user"]
    assert user["count"] == 3
    assert user["present_pct"] == 50.0
    assert user["distinct"] == 1
    assert user["samples"] == ["ada"]
    assert user["type"] == "str"
    assert payload["keys"]["tags"]["type"] == "array"
    assert payload["keys"]["note"]["type"] == "null"
    assert payload["keys"]["amount"]["type"] == "float"
    assert payload["keys"]["port"]["type"] == "int"
    assert payload["keys"]["debug"]["type"] == "bool"
    assert "ctx_message" in payload["keys"]
    assert "_id" not in payload["keys"]


def test_fields_top_values():
    payload = fields(BASIC, key="logger", top=2)
    assert payload["key"] == "logger"
    assert payload["top"] == [
        {"value": "app.pay", "count": 3},
        {"value": "app", "count": 2},
    ]


def test_fields_scan_cap():
    payload = fields(BASIC, scan=2)
    assert payload["scanned"] == 2
    assert payload["scan_capped"] is True
    assert "user" not in payload["keys"]
