"""Wait for a matching log record to appear."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.query import query
from slogger.tools.tail import tail_once


@dataclass
class WatchResult:
    """Outcome of :func:`watch`: matched record, timeout flag, and counters."""

    matched: dict[str, Any] | None
    timed_out: bool
    elapsed_ms: float
    records_seen: int


def watch(
    path: str,
    *,
    filters: Filters | None = None,
    timeout: float = 30.0,
    existing: bool = False,
    interval: float = 0.25,
    stop: Callable[[], bool] | None = None,
    on_reopen: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stdin: TextIO | None = None,
) -> WatchResult:
    """Block until a matching record appears, or until ``timeout`` seconds.

    ``existing=True`` also considers records already in the file. CLI exit
    code ``3`` means timed out.
    """
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    predicate = filters if filters is not None else Filters()
    started = clock()
    deadline = started + timeout

    if path == "-":
        return _watch_stdin(
            predicate=predicate,
            clock=clock,
            stop=stop,
            started=started,
            deadline=deadline,
            stdin=stdin if stdin is not None else sys.stdin,
        )

    records_seen = 0
    current_after: str | None = None
    if existing:
        page = query(path, filters=predicate, limit=1, complete=True)
        records_seen += len(page.records)
        if page.records:
            return WatchResult(
                page.records[0], False, (clock() - started) * 1000.0, records_seen
            )
        eof = tail_once(path, after=None)
        current_after = eof.next_cursor
    else:
        eof = tail_once(path, after=None)
        current_after = eof.next_cursor

    known_size = os.path.getsize(path) if os.path.exists(path) else 0
    known_inode = os.stat(path).st_ino if os.path.exists(path) else None

    while True:
        if stop is not None and stop():
            return WatchResult(None, False, (clock() - started) * 1000.0, records_seen)

        now = clock()
        if now >= deadline:
            return WatchResult(None, True, (now - started) * 1000.0, records_seen)

        try:
            stat = os.stat(path)
        except FileNotFoundError:
            remaining = deadline - clock()
            if remaining <= 0:
                return WatchResult(
                    None, True, (clock() - started) * 1000.0, records_seen
                )
            sleep(min(interval, remaining))
            continue

        if known_inode is not None and (
            stat.st_ino != known_inode or stat.st_size < known_size
        ):
            current_after = None
            known_inode = stat.st_ino
            if on_reopen is not None:
                on_reopen(path)

        page = tail_once(path, filters=predicate, after=current_after)
        records_seen += len(page.records)
        if page.records:
            return WatchResult(
                page.records[0], False, (clock() - started) * 1000.0, records_seen
            )
        if page.next_cursor is not None:
            current_after = page.next_cursor

        known_size = stat.st_size
        if known_inode is None:
            known_inode = stat.st_ino

        now = clock()
        if now >= deadline:
            return WatchResult(None, True, (now - started) * 1000.0, records_seen)
        sleep(min(interval, deadline - now))


def _watch_stdin(
    *,
    predicate: Filters,
    clock: Callable[[], float],
    stop: Callable[[], bool] | None,
    started: float,
    deadline: float,
    stdin: TextIO,
) -> WatchResult:
    line_q: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            while True:
                line = stdin.readline()
                if line == "":
                    break
                line_q.put(line)
        finally:
            line_q.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    records_seen = 0
    line_no = 0

    while True:
        if stop is not None and stop():
            return WatchResult(None, False, (clock() - started) * 1000.0, records_seen)
        remaining = deadline - clock()
        if remaining <= 0:
            return WatchResult(None, True, (clock() - started) * 1000.0, records_seen)
        try:
            item = line_q.get(timeout=min(max(remaining, 0.0), 0.05) or 0.05)
        except queue.Empty:
            continue
        if item is None:
            raise ToolError("eof_without_match", "stdin closed without a match")
        line_no += 1
        text = item[:-1] if item.endswith("\n") else item
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        record = dict(data)
        record["_id"] = f"-:{line_no}"
        records_seen += 1
        if predicate.matches(record):
            return WatchResult(
                record, False, (clock() - started) * 1000.0, records_seen
            )
