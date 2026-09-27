"""Filter and page structured log records."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Reader, Source
from slogger.tools.render import project


@dataclass
class Page:
    records: list[dict[str, Any]]
    next_cursor: str | None
    skipped_lines: int
    warnings: list[str] = field(default_factory=list)


def query(
    sources: Source | Sequence[Source],
    *,
    filters: Filters | None = None,
    limit: int | None = None,
    after: str | None = None,
    last: int | None = None,
    fields: Sequence[str] | None = None,
    truncate: int | None = None,
    complete: bool = True,
    order: Order = "concat",
) -> Page:
    """Return matching records bounded by ``limit`` or ``last``.

    ``limit=None`` means unbounded. ``last`` keeps only the final N matches and
    is mutually exclusive with ``after`` (caller enforces).
    """
    if last is not None and after is not None:
        raise ValueError("--last and --after are mutually exclusive")

    predicate = filters if filters is not None else Filters()
    reader = Reader(sources, after=after, complete=complete, order=order)

    if last is not None:
        window: deque[dict[str, Any]] = deque(maxlen=last)
        for record in reader:
            if predicate.matches(record):
                window.append(project(record, fields, truncate))
        records = list(window)
        next_cursor = records[-1]["_id"] if records else after
        return Page(
            records=records,
            next_cursor=next_cursor if complete is False else None,
            skipped_lines=reader.skipped_lines,
            warnings=list(reader.warnings),
        )

    records = []
    next_cursor: str | None = None
    for record in reader:
        if not predicate.matches(record):
            continue
        records.append(project(record, fields, truncate))
        if limit is not None and limit > 0 and len(records) >= limit:
            if order == "time":
                next_cursor = reader.cursor()
            else:
                next_cursor = records[-1]["_id"]
            break
    else:
        # Exhausted input.
        if complete is False:
            if order == "time":
                next_cursor = reader.cursor()
            else:
                next_cursor = records[-1]["_id"] if records else after
        else:
            next_cursor = None

    return Page(
        records=records,
        next_cursor=next_cursor,
        skipped_lines=reader.skipped_lines,
        warnings=list(reader.warnings),
    )
