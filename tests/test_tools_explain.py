from __future__ import annotations

from datetime import datetime, timezone

from slogger.tools.filters import Filters, Where, parse_relative_or_iso


def test_explain_empty():
    payload = Filters().explain()
    assert payload["schema_version"] == 1
    assert payload["filters"]["level_min"] is None
    assert payload["filters"]["where"] == []
    assert payload["filters"]["exclude_events"] is False
    assert "multiple --where clauses are ANDed" in payload["notes"]


def test_explain_normalises_filters():
    since = datetime(2026, 9, 26, 15, 0, 0, tzinfo=timezone.utc)
    payload = Filters(
        level_min=40,
        logger="app.pay",
        where=(Where("user", "=", "ada"), Where("amount", ">=", "99")),
        has=("order_id",),
        missing=("exception",),
        grep="timeout",
        since=since,
        exclude_events=True,
    ).explain()
    assert payload["filters"] == {
        "level_min": 40,
        "level_exact": None,
        "logger": "app.pay",
        "where": [
            {"key": "user", "op": "=", "value": "ada"},
            {"key": "amount", "op": ">=", "value": "99"},
        ],
        "has": ["order_id"],
        "missing": ["exception"],
        "grep": "timeout",
        "since": "2026-09-26T15:00:00.000Z",
        "until": None,
        "span": None,
        "trace": None,
        "exclude_events": True,
    }


def test_explain_resolves_relative_since_via_parse():
    now = datetime(2026, 9, 26, 16, 0, 0, tzinfo=timezone.utc)
    since = parse_relative_or_iso("10m", now=now)
    payload = Filters(since=since).explain()
    assert payload["filters"]["since"] == "2026-09-26T15:50:00.000Z"


def test_filters_from_mapping_roundtrip():
    original = Filters(level_min=40, where=(Where("user", "=", "ada"),), exclude_events=True)
    restored = Filters.from_mapping(original.explain()["filters"])
    assert restored.level_min == 40
    assert restored.where == (Where("user", "=", "ada"),)
    assert restored.exclude_events is True
