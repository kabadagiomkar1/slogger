"""Backend-independent record projection preserving hidden source identity."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .runtime import RecordRow


def project_rows(rows: Iterable[RecordRow], fields: tuple[str, ...]) -> Iterator[RecordRow]:
    for row in rows:
        record = {name: row.record[name] for name in fields if name in row.record}
        if row.record_id is not None:
            record["_id"] = row.record_id
        yield RecordRow(record, row.ordinal, row.record_id)
