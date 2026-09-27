from __future__ import annotations

import json
from pathlib import Path

import pytest

from slogger.cli import main
from slogger.tools.filters import Filters
from slogger.tools.query import query

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
MALFORMED = "tests/fixtures/logs/malformed.log"
ROTATED = "tests/fixtures/logs/rotated/app.log*"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def _run(argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _json_lines(stdout: str):
    lines = [line for line in stdout.splitlines() if line.strip()]
    records = [json.loads(line) for line in lines[:-1]]
    meta = json.loads(lines[-1])
    return records, meta


def test_query_json_level_warning(capsys):
    code, out, err = _run(
        ["query", BASIC, "--level", "WARNING", "--format", "json"],
        capsys,
    )
    assert code == 0
    assert err == ""
    records, meta = _json_lines(out)
    assert len(records) == 2
    assert records[0]["_id"] == f"{BASIC}:4"
    assert records[1]["_id"] == f"{BASIC}:5"
    assert meta["_meta"]["schema_version"] == 1
    assert meta["_meta"]["returned"] == 2
    assert meta["_meta"]["skipped_lines"] == 0
    assert meta["_meta"]["next_cursor"] is None


def test_query_json_limit_and_after(capsys):
    code, out, _ = _run(["query", BASIC, "--format", "json", "--limit", "2"], capsys)
    assert code == 0
    records, meta = _json_lines(out)
    assert [r["_id"] for r in records] == [f"{BASIC}:1", f"{BASIC}:2"]
    assert meta["_meta"]["next_cursor"] == f"{BASIC}:2"

    code, out, _ = _run(
        ["query", BASIC, "--format", "json", "--limit", "2", "--after", f"{BASIC}:2"],
        capsys,
    )
    assert code == 0
    records, meta = _json_lines(out)
    assert [r["_id"] for r in records] == [f"{BASIC}:3", f"{BASIC}:4"]
    assert meta["_meta"]["next_cursor"] == f"{BASIC}:4"

    code, out, _ = _run(
        ["query", BASIC, "--format", "json", "--after", f"{BASIC}:6"],
        capsys,
    )
    assert code == 0
    records, meta = _json_lines(out)
    assert records == []
    assert meta["_meta"]["next_cursor"] is None


def test_query_json_default_limit_not_hit(capsys):
    code, out, _ = _run(["query", BASIC, "--format", "json"], capsys)
    assert code == 0
    records, meta = _json_lines(out)
    assert len(records) == 6
    assert meta["_meta"]["next_cursor"] is None


def test_query_console_where(capsys):
    code, out, err = _run(
        ["query", BASIC, "--format", "console", "--where", "user=ada"],
        capsys,
    )
    assert code == 0
    assert err == ""
    assert len(out.splitlines()) == 3


def test_query_malformed_console_skipped(capsys):
    code, out, err = _run(["query", MALFORMED, "--format", "console"], capsys)
    assert code == 0
    assert len(out.splitlines()) == 5
    assert "skipped 2 lines that were not JSON objects" in err


def test_query_fail_if_any(capsys):
    code, _, _ = _run(
        ["query", BASIC, "--level", "ERROR", "--fail-if-any", "--format", "json"],
        capsys,
    )
    assert code == 1
    code, _, _ = _run(
        ["query", BASIC, "--level", "CRITICAL", "--fail-if-any", "--format", "json"],
        capsys,
    )
    assert code == 0


def test_query_last(capsys):
    code, out, _ = _run(["query", BASIC, "--last", "2", "--format", "json"], capsys)
    assert code == 0
    records, meta = _json_lines(out)
    assert [r["_id"] for r in records] == [f"{BASIC}:5", f"{BASIC}:6"]
    assert meta["_meta"]["next_cursor"] is None


def test_query_after_nocolon_is_usage_error(capsys):
    code, out, err = _run(
        ["query", BASIC, "--after", "nocolon", "--format", "json"],
        capsys,
    )
    assert code == 64
    assert err.startswith("usage:")
    assert "Traceback" not in err


def test_query_last_with_after_is_usage_error(capsys):
    code, out, err = _run(
        ["query", BASIC, "--last", "2", "--after", "x:1", "--format", "json"],
        capsys,
    )
    assert code == 64
    assert out == ""
    assert err.startswith("usage:")


def test_query_after_with_stdin_is_usage_error(capsys):
    # Values starting with "-" must use --after=-:1 form for argparse.
    code, out, err = _run(["query", "-", "--after=-:1", "--format", "json"], capsys)
    assert code == 64
    assert out == ""
    assert "stdin" in err


def test_query_missing_file_json_error(capsys):
    code, out, err = _run(["query", "nope.log", "--format", "json"], capsys)
    assert code == 2
    assert out == ""
    payload = json.loads(err.strip())
    assert payload["error"] == "file_not_found"


def test_query_spaced_where_is_usage_error(capsys):
    code, out, err = _run(
        ["query", BASIC, "--where", "user = ada", "--format", "json"],
        capsys,
    )
    assert code == 64
    assert out == ""
    assert err.startswith("usage:")


def test_query_fields_and_truncate(capsys):
    code, out, _ = _run(
        ["query", BASIC, "--format", "json", "--fields", "message", "--truncate", "4"],
        capsys,
    )
    assert code == 0
    records, _ = _json_lines(out)
    assert set(records[0]) == {"_id", "message"}
    assert records[0]["message"] == "star..."


def test_query_rotated_glob(capsys):
    code, out, _ = _run(["query", ROTATED, "--format", "json"], capsys)
    assert code == 0
    records, _ = _json_lines(out)
    assert [r["message"] for r in records] == ["r1", "r2", "r3", "r4", "r5", "r6"]


def test_no_command_and_help(capsys):
    code, out, err = _run([], capsys)
    assert code == 64
    assert out == ""
    assert "usage:" in err

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_default_format_is_json_when_not_tty(capsys):
    code, out, _ = _run(["query", BASIC], capsys)
    assert code == 0
    records, meta = _json_lines(out)
    assert len(records) == 6
    assert "_meta" in meta


def test_query_api_memory():
    page = query([{"message": "x", "level": "INFO"}], filters=Filters(level_min=20))
    assert page.records[0]["_id"] == "mem:0"


def test_meta_and_fields_cli(capsys):
    code, out, _ = _run(["meta", BASIC, "--format", "json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema_version"] == 1
    assert payload["records"] == 6

    code, out, _ = _run(["fields", BASIC, "--format", "json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema_version"] == 1
    assert "user" in payload["keys"]

    code, out, _ = _run(["fields", BASIC, "--key", "user", "--format", "console"], capsys)
    assert code == 0
    assert "ada" in out


def test_trace_cli(capsys):
    TRACE = "tests/fixtures/logs/trace.log"
    code, out, _ = _run(["trace", TRACE, "aaaa", "--format", "json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema_version"] == 1
    assert payload["spans"][0]["children"][0]["span"] == "charge"

    code, out, err = _run(["trace", TRACE, "ffff", "--format", "json"], capsys)
    assert code == 2
    assert out == ""
    assert json.loads(err)["error"] == "trace_not_found"

    code, out, _ = _run(["trace", TRACE, "--where", "order_id=42", "--format", "json"], capsys)
    assert code == 0
    assert json.loads(out)["trace_id"] == "a" * 32

    code, out, err = _run(
        ["trace", TRACE, "aaaa", "--where", "x=y", "--format", "json"],
        capsys,
    )
    assert code == 64
    assert out == ""


def test_tail_once_cli(capsys):
    code, out, _ = _run(["tail", BASIC, "--once", "--format", "json"], capsys)
    assert code == 0
    records, meta = _json_lines(out)
    assert len(records) == 6
    assert meta["_meta"]["next_cursor"] == f"{BASIC}:6"

    code, out, _ = _run(
        ["tail", BASIC, "--once", "--after", f"{BASIC}:5", "--format", "json"],
        capsys,
    )
    assert code == 0
    records, _ = _json_lines(out)
    assert [r["_id"] for r in records] == [f"{BASIC}:6"]

    code, out, err = _run(["tail", "a.log", "b.log"], capsys)
    assert code == 64
    assert out == ""


def test_help_lists_p0_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    # argparse writes help to stdout
    captured = capsys.readouterr()
    for name in ("query", "tail", "trace", "meta", "fields"):
        assert name in captured.out
