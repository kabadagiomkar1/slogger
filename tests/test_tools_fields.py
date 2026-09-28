from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools.fields import fields
from slogger.tools.filters import Filters

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


def test_fields_cache_hit_miss_and_filtered(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    src = tmp_path / "app.log"
    src.write_text(Path(BASIC).read_text(encoding="utf-8"), encoding="utf-8")
    cache_file = Path(str(src) + ".slogger-fields.json")

    first = fields(str(src), cache=True)
    assert cache_file.is_file()
    mtime = cache_file.stat().st_mtime_ns

    second = fields(str(src), cache=True)
    assert second == first
    assert cache_file.stat().st_mtime_ns == mtime

    # Filtered calls must not read or write the unfiltered cache incorrectly.
    filtered = fields(str(src), filters=Filters(level_min=40), cache=True)
    assert filtered["scanned"] == 1
    third = fields(str(src), cache=True)
    assert third == first
    assert cache_file.stat().st_mtime_ns == mtime

    # Identity change invalidates; add a real record so the payload changes.
    extra = (
        '{"timestamp":"2026-09-26T16:00:05.000Z","level":"INFO","logger":"app",'
        '"message":"extra","file":"main.py","func":"main","line":99}\n'
    )
    with open(src, "a", encoding="utf-8") as handle:
        handle.write(extra)
    fourth = fields(str(src), cache=True)
    assert fourth["scanned"] == first["scanned"] + 1
    assert fourth != first


def test_fields_cache_dir_and_skips_stdin_memory(tmp_path):
    src = tmp_path / "app.log"
    src.write_text(Path(REPO_ROOT, BASIC).read_text(encoding="utf-8"), encoding="utf-8")
    cache_dir = tmp_path / "cache"
    fields(str(src), cache=True, cache_dir=str(cache_dir))
    assert any(cache_dir.iterdir())

    rows = [
        {
            "timestamp": "2026-09-26T16:00:00.000Z",
            "level": "INFO",
            "logger": "app",
            "message": "x",
            "file": "a.py",
            "func": "f",
            "line": 1,
        }
    ]
    fields(rows, cache=True, cache_dir=str(cache_dir))
    # Still only the one file-backed entry.
    assert len(list(cache_dir.iterdir())) == 1


def test_fields_default_api_does_not_write_cache(tmp_path):
    src = tmp_path / "app.log"
    src.write_text(Path(REPO_ROOT, BASIC).read_text(encoding="utf-8"), encoding="utf-8")
    fields(str(src))
    assert not Path(str(src) + ".slogger-fields.json").exists()


@pytest.mark.parametrize("nested", [False, True])
def test_cache_detection_does_not_consume_generators(nested):
    source = ({"message": str(i)} for i in range(3))
    payload = fields([source] if nested else source, cache=True)
    assert payload["scanned"] == 3
    assert payload["keys"]["message"]["distinct"] == 3
