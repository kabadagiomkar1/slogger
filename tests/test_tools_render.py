from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from slogger.tools.reader import Reader
from slogger.tools.render import (
    project,
    render_console_line,
    render_json_line,
    render_table,
    use_color,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
TRACE = "tests/fixtures/logs/trace.log"
MALFORMED = "tests/fixtures/logs/malformed.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_render_console_basic_line():
    row = list(Reader(BASIC))[2]
    line = render_console_line(row, color=False)
    assert (
        line
        == "2026-09-26T16:00:02.000Z INFO     app.pay  charging  amount=99.5 order_id=42 user=ada"
    )


def test_render_console_span_end_with_exception():
    row = list(Reader(TRACE))[4]
    line = render_console_line(row, color=False)
    assert "event=span.end" in line
    assert "status=error" in line
    assert "duration_ms=380.0" in line
    assert "error_type=TimeoutError" in line
    assert "error=boom" in line
    assert "span=charge" in line
    assert "span_id=2222222222222222" in line
    assert "parent_span_id=1111111111111111" in line
    assert "trace_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in line
    assert "\nTraceback" in line


def test_render_console_missing_timestamp():
    row = next(r for r in Reader(MALFORMED) if r["message"] == "no timestamp")
    line = render_console_line(row, color=False)
    assert line.startswith("- INFO")


def test_render_console_color():
    row = list(Reader(BASIC))[0]
    line = render_console_line(row, color=True)
    assert "\033[1;32m" in line


def test_render_console_dims_span_fields():
    row = list(Reader(TRACE))[0]
    line = render_console_line(row, color=True)
    assert "\033[2m" in line
    assert "span=checkout" in line


def test_project_and_truncate():
    row = list(Reader(BASIC))[2]
    projected = project(row, ["message", "user"], None)
    assert set(projected) == {"_id", "message", "user"}
    truncated = project(row, None, 5)
    assert truncated["message"] == "charg..."
    assert truncated["amount"] == 99.5


def test_render_json_line_fallback():
    text = render_json_line({"a": {1, 2}})
    data = json.loads(text)
    assert isinstance(data["a"], list)


def test_use_color_env(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = io.StringIO()
    assert use_color(stream) is False
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert use_color(stream) is True
    monkeypatch.delenv("FORCE_COLOR")
    monkeypatch.setenv("NO_COLOR", "")

    class Tty:
        def isatty(self):
            return True

    assert use_color(Tty()) is False


def test_render_table_basic():
    text = render_table([{"a": "x", "n": 1}], ["a", "n"])
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[0] == "a  n"
    assert lines[1] == "-  -"
    assert lines[2] == "x  1"


def test_render_table_empty_and_truncate():
    empty = render_table([], ["a"])
    assert empty.splitlines()[-1] == "(no rows)"
    long = "a" * 60
    text = render_table([{"a": long}], ["a"])
    cell = text.splitlines()[-1].strip()
    assert cell == ("a" * 37) + "..."
    assert len(cell) == 40
