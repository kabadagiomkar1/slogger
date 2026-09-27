from __future__ import annotations

import pytest

from slogger.tools.grouping import group_value, parse_group_selector
from slogger.tools.timeparse import parse_bucket, parse_duration_ms


def test_group_value_types():
    assert group_value({"k": 1}, "k") == ("number", 1.0)
    assert group_value({"k": True}, "k") == ("bool", True)
    assert group_value({"k": None}, "k") == ("null", None)
    assert group_value({"k": [1]}, "k") == ("array", "[1]")
    assert group_value({}, "k") is None


def test_parse_group_selector():
    assert parse_group_selector("request_id=r1") == ("request_id", "r1")
    with pytest.raises(ValueError):
        parse_group_selector("request_id")


def test_parse_duration_ms():
    assert parse_duration_ms("500ms") == 500.0
    assert parse_duration_ms("1.5s") == 1500.0
    assert parse_duration_ms("2m") == 120_000.0
    with pytest.raises(ValueError):
        parse_duration_ms("x")


def test_parse_bucket():
    assert parse_bucket("1m") == 60
    assert parse_bucket("30s") == 30
    assert parse_bucket("1h") == 3600
    assert parse_bucket("1d") == 86400
    with pytest.raises(ValueError):
        parse_bucket("2w")
