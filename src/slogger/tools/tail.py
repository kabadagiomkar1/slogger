"""Follow and poll structured log files."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.query import Page, query
from slogger.tools.reader import Order, Reader, Source


def tail_once(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    after: str | None = None,
    limit: int | None = None,
    fields: Sequence[str] | None = None,
    truncate: int | None = None,
    order: Order = "concat",
) -> Page:
    """Read from ``after`` to EOF, holding back an unterminated final line."""
    page = query(
        sources,
        filters=filters,
        limit=limit,
        after=after,
        fields=fields,
        truncate=truncate,
        complete=False,
        order=order,
    )
    # Polling contract: always expose a resume cursor.
    if page.next_cursor is None:
        if page.records:
            page.next_cursor = page.records[-1]["_id"]
        else:
            page.next_cursor = after
    return page


def follow(
    path: str,
    *,
    filters: Filters | None = None,
    after: str | None = None,
    interval: float = 0.25,
    lines: int = 10,
    stop: Callable[[], bool] | None = None,
    on_reopen: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield matching records, then follow new complete lines.

    ``path`` must be a single file path or ``"-"``. Stdin is read until EOF.
    """
    predicate = filters if filters is not None else Filters()

    if path == "-":
        page = tail_once("-", filters=predicate, after=None)
        yield from page.records
        return

    current_after = after
    if lines > 0:
        page = query(path, filters=predicate, last=lines, complete=True)
        yield from page.records
        if page.records:
            current_after = page.records[-1]["_id"]
        else:
            # No matches in backlog; still resume from EOF so we don't replay.
            reader = Reader(path, complete=True)
            for record in reader:
                current_after = record["_id"]
    elif after is None:
        # -n 0: start at EOF, emit only newly appended complete lines.
        reader = Reader(path, complete=False)
        for record in reader:
            current_after = record["_id"]

    known_size = os.path.getsize(path) if os.path.exists(path) else 0
    known_inode = os.stat(path).st_ino if os.path.exists(path) else None

    while True:
        if stop is not None and stop():
            return
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            time.sleep(interval)
            continue

        if known_inode is not None and (
            stat.st_ino != known_inode or stat.st_size < known_size
        ):
            current_after = None
            known_inode = stat.st_ino
            if on_reopen is not None:
                on_reopen(path)

        page = tail_once(path, filters=predicate, after=current_after)
        for record in page.records:
            yield record
        if page.next_cursor is not None:
            current_after = page.next_cursor

        known_size = stat.st_size
        if known_inode is None:
            known_inode = stat.st_ino
        time.sleep(interval)
