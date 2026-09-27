"""Iterate JSONL log sources with stable ``_id`` cursors."""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from slogger.tools.errors import CursorError

# TimedRotatingFileHandler(when="midnight", utc=True) suffix / extMatch.
_ROTATION_SUFFIX = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)$")

Source = str | os.PathLike[str] | Iterable[Mapping[str, Any]]


def parse_id(value: str) -> tuple[str, int]:
    """Split ``<source>:<n>`` with :meth:`str.rsplit` so drive letters survive."""
    source, _, line_text = value.rpartition(":")
    if not source or not line_text:
        raise ValueError(f"malformed record id: {value!r}")
    try:
        line = int(line_text)
    except ValueError as exc:
        raise ValueError(f"malformed record id: {value!r}") from exc
    if line < 0:
        raise ValueError(f"malformed record id: {value!r}")
    return source, line


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are treated as UTC.

    Accepts 0–9 fractional digits, ``Z``, and numeric offsets. Returns ``None``
    when ``value`` is missing or unparseable.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _as_path_str(source: str | os.PathLike[str]) -> str:
    return source if isinstance(source, str) else os.fspath(source)


def _line_count(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _is_rotation_sibling(path: str, base: str) -> bool:
    prefix = base + "."
    if not path.startswith(prefix):
        return False
    return bool(_ROTATION_SUFFIX.fullmatch(path[len(prefix) :]))


def _order_paths(paths: list[str]) -> list[str]:
    """Move a live file after its rotated siblings when both are present."""
    path_set = set(paths)
    bases = {
        path
        for path in paths
        if any(_is_rotation_sibling(other, path) for other in path_set if other != path)
    }
    if not bases:
        return paths

    result: list[str] = []
    deferred: list[str] = []
    for path in paths:
        if path in bases:
            deferred.append(path)
        else:
            result.append(path)
    result.extend(deferred)
    return result


def _expand_path(path: str) -> list[str]:
    if path == "-":
        return ["-"]
    if any(ch in path for ch in "*?["):
        matches = sorted(glob.glob(path))
        if not matches:
            raise FileNotFoundError(f"glob matched no files: {path}")
        return _order_paths(matches)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return [path]


def _is_mapping_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and (len(value) == 0 or isinstance(value[0], Mapping))
    )


def resolve_sources(
    sources: Source | Sequence[Source],
) -> list[str | Iterable[Mapping[str, Any]]]:
    """Expand globs and preserve concatenation order (handoff D3).

    A list/tuple of mappings is one in-memory source. A literal path that does
    not exist, or a glob that matches nothing, raises :class:`FileNotFoundError`.
    ``"-"`` is kept as-is.
    """
    if isinstance(sources, (str, os.PathLike)):
        return list(_expand_path(_as_path_str(sources)))

    if _is_mapping_sequence(sources):
        return [sources]  # type: ignore[list-item]

    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes, bytearray)):
        resolved: list[str | Iterable[Mapping[str, Any]]] = []
        for item in sources:
            if isinstance(item, (str, os.PathLike)):
                resolved.extend(_expand_path(_as_path_str(item)))
            elif _is_mapping_sequence(item):
                resolved.append(item)  # type: ignore[arg-type]
            else:
                # Generator or other iterable of mappings.
                resolved.append(item)  # type: ignore[arg-type]
        return resolved

    # Bare iterable (generator) of mappings.
    return [sources]  # type: ignore[list-item]


class Reader:
    """Stream records from files, stdin, or an in-memory iterable.

    Each yielded dict is a shallow copy of the parsed object with ``_id`` set.
    Blank lines are ignored. Non-JSON lines and JSON that is not an object are
    counted in :attr:`skipped_lines` and skipped.
    """

    def __init__(
        self,
        sources: Source | Sequence[Source],
        *,
        after: str | None = None,
        complete: bool = True,
    ) -> None:
        self._sources = resolve_sources(sources)
        self._after = after
        self._complete = complete
        self.skipped_lines = 0
        self.last_id: str | None = None
        self.warnings: list[str] = []
        self._after_source: str | None = None
        self._after_line: int | None = None
        if after is not None:
            self._after_source, self._after_line = parse_id(after)
            self._validate_cursor(after)

    def _validate_cursor(self, after: str) -> None:
        assert self._after_source is not None and self._after_line is not None
        if self._after_source == "mem":
            if not any(not isinstance(source, str) for source in self._sources):
                raise CursorError(
                    f"cursor source not in input set: {self._after_source}",
                    cursor=after,
                )
            return
        if self._after_source == "-":
            if "-" not in self._sources:
                raise CursorError(
                    f"cursor source not in input set: {self._after_source}",
                    cursor=after,
                )
            return
        if self._after_source not in self._sources:
            raise CursorError(
                f"cursor source not in input set: {self._after_source}",
                cursor=after,
            )
        total = _line_count(self._after_source)
        if self._after_line > total:
            raise CursorError(
                f"cursor line {self._after_line} past end of "
                f"{self._after_source} ({total} lines)",
                cursor=after,
            )

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.skipped_lines = 0
        self.last_id = None
        past_after = self._after is None
        for source in self._sources:
            if isinstance(source, str):
                if not past_after and source != self._after_source:
                    continue
                yield from self._iter_text_path(source)
                if source == self._after_source:
                    past_after = True
            else:
                if not past_after and self._after_source != "mem":
                    continue
                yield from self._iter_memory(source)
                if self._after_source == "mem":
                    past_after = True

    def _iter_text_path(self, path: str) -> Iterator[dict[str, Any]]:
        if path == "-":
            yield from self._iter_text_stream(sys.stdin, "-")
            return
        with open(path, encoding="utf-8") as handle:
            yield from self._iter_text_stream(handle, path)

    def _iter_text_stream(
        self,
        stream: Iterable[str],
        source_label: str,
    ) -> Iterator[dict[str, Any]]:
        line_no = 0
        pending: str | None = None
        for raw in stream:
            if pending is not None:
                raw = pending + raw
                pending = None
            if not raw.endswith("\n") and not self._complete:
                pending = raw
                break
            line_no += 1
            text = raw[:-1] if raw.endswith("\n") else raw
            if (
                source_label == self._after_source
                and self._after_line is not None
                and line_no <= self._after_line
            ):
                continue
            record = self._parse_line(text, source_label, line_no)
            if record is not None:
                self.last_id = record["_id"]
                yield record
        if pending is not None and self._complete:
            line_no += 1
            if not (
                source_label == self._after_source
                and self._after_line is not None
                and line_no <= self._after_line
            ):
                record = self._parse_line(pending, source_label, line_no)
                if record is not None:
                    self.last_id = record["_id"]
                    yield record

    def _iter_memory(
        self,
        records: Iterable[Mapping[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        for index, item in enumerate(records):
            if (
                self._after_source == "mem"
                and self._after_line is not None
                and index <= self._after_line
            ):
                continue
            if not isinstance(item, Mapping):
                self.skipped_lines += 1
                continue
            record = dict(item)
            record["_id"] = f"mem:{index}"
            self.last_id = record["_id"]
            yield record

    def _parse_line(
        self,
        text: str,
        source_label: str,
        line_no: int,
    ) -> dict[str, Any] | None:
        if not text.strip():
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self.skipped_lines += 1
            return None
        if not isinstance(data, dict):
            self.skipped_lines += 1
            return None
        record = dict(data)
        record["_id"] = f"{source_label}:{line_no}"
        return record
