from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.watch import watch

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.sleeps.append(dt)
        self.t += dt


def test_watch_timeout_quiet_file(tmp_path):
    path = tmp_path / "quiet.log"
    path.write_text("")
    clock = FakeClock()
    result = watch(
        str(path),
        timeout=1.0,
        interval=0.25,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.timed_out is True
    assert result.matched is None
    assert result.elapsed_ms == 1000.0
    assert len(clock.sleeps) == 4


def test_watch_match_on_second_poll(tmp_path):
    path = tmp_path / "grow.log"
    path.write_text("")
    clock = FakeClock()
    polls = {"n": 0}

    real_sleep = clock.sleep

    def sleep_and_append(dt: float) -> None:
        real_sleep(dt)
        polls["n"] += 1
        if polls["n"] == 1:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "timestamp": "2026-09-26T16:00:00.000Z",
                            "level": "INFO",
                            "logger": "app",
                            "message": "hello",
                            "file": "a.py",
                            "func": "f",
                            "line": 1,
                        }
                    )
                    + "\n"
                )

    result = watch(
        str(path),
        timeout=5.0,
        interval=0.25,
        clock=clock,
        sleep=sleep_and_append,
    )
    assert result.timed_out is False
    assert result.matched is not None
    assert result.matched["message"] == "hello"


def test_watch_existing_and_stop(tmp_path):
    clock = FakeClock()
    result = watch(
        BASIC,
        filters=Filters(grep="stopped"),
        existing=True,
        timeout=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.matched is not None
    assert result.matched["message"] == "stopped"
    assert clock.sleeps == []

    clock = FakeClock()
    result = watch(
        BASIC,
        filters=Filters(grep="stopped"),
        existing=False,
        timeout=0.5,
        interval=0.25,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.timed_out is True

    clock = FakeClock()
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    path = tmp_path / "s.log"
    path.write_text("")
    result = watch(
        str(path),
        timeout=5.0,
        interval=0.25,
        clock=clock,
        sleep=clock.sleep,
        stop=stop,
    )
    assert result.matched is None
    assert result.timed_out is False


def test_watch_stdin(monkeypatch):
    clock = FakeClock()
    stream = io.StringIO(
        json.dumps(
            {
                "timestamp": "2026-09-26T16:00:00.000Z",
                "level": "INFO",
                "logger": "app",
                "message": "one",
                "file": "a.py",
                "func": "f",
                "line": 1,
            }
        )
        + "\n"
        + json.dumps(
            {
                "timestamp": "2026-09-26T16:00:01.000Z",
                "level": "ERROR",
                "logger": "app",
                "message": "two",
                "file": "a.py",
                "func": "f",
                "line": 2,
            }
        )
        + "\n"
    )
    result = watch(
        "-",
        filters=Filters(level_min=40),
        timeout=5.0,
        clock=clock,
        sleep=clock.sleep,
        stdin=stream,
    )
    assert result.matched is not None
    assert result.matched["message"] == "two"

    with pytest.raises(ToolError) as exc:
        watch(
            "-",
            timeout=5.0,
            clock=FakeClock(),
            sleep=lambda _dt: None,
            stdin=io.StringIO(""),
        )
    assert exc.value.code == "eof_without_match"
