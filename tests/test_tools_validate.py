from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.validate import validate

REPO_ROOT = Path(__file__).resolve().parents[1]
INVALID = "tests/fixtures/logs/invalid.log"
MALFORMED = "tests/fixtures/logs/malformed.log"
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_validate_invalid():
    payload = validate(INVALID)
    assert payload["lines"] == 8
    assert payload["valid"] == 1
    assert payload["invalid"] == 7
    assert payload["kinds"] == {"not_json": 1, "not_object": 2, "schema": 4}
    assert len(payload["diagnostics"]) == 7
    assert payload["diagnostics"][0]["_id"] == f"{INVALID}:2"
    assert payload["diagnostics"][0]["kind"] == "schema"
    assert payload["diagnostics"][2]["kind"] == "not_json"
    capped = validate(INVALID, max_diagnostics=2)
    assert len(capped["diagnostics"]) == 2
    assert capped["diagnostics_capped"] is True
    assert capped["invalid"] == 7


def test_validate_malformed_memory_basic():
    payload = validate(MALFORMED)
    assert payload["lines"] == 7
    # Missing timestamp is a schema error; unterminated final line is still checked.
    assert payload["valid"] == 4
    assert payload["invalid"] == 3
    assert payload["kinds"] == {"not_json": 1, "not_object": 1, "schema": 1}
    mem = validate([{"message": "x"}, 5])  # type: ignore[arg-type]
    assert mem["kinds"]["not_object"] == 1
    assert mem["kinds"]["schema"] == 1
    assert [d["_id"] for d in mem["diagnostics"]] == ["mem:0", "mem:1"]
    assert validate(BASIC)["invalid"] == 0
