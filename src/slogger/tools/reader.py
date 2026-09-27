"""Iterate JSONL log sources with stable ``_id`` cursors."""

from __future__ import annotations

import glob
import heapq
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Literal

from slogger.tools.errors import CursorError

# TimedRotatingFileHandler(when="midnight", utc=True) suffix / extMatch.
_ROTATION_SUFFIX = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)$")
_MEMORY_LABEL = re.compile(r"^mem(\d*)$")
_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)

Source = str | os.PathLike[str] | Iterable[Mapping[str, Any]]
Order = Literal["concat", "time"]


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


def memory_label(index: int) -> str:
    """Label for the ``index``-th in-memory source (``mem``, ``mem1``, …)."""
    return "mem" if index == 0 else f"mem{index}"


def is_memory_label(label: str) -> bool:
    return bool(_MEMORY_LABEL.fullmatch(label))


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


def _materialise_records(iterable: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list(iterable)


def resolve_sources(
    sources: Source | Sequence[Source],
) -> list[str | list[Mapping[str, Any]]]:
    """Expand globs and preserve concatenation order.

    A list/tuple of mappings is one in-memory source. Non-sequence iterables
    (generators) are materialised into a list so two-pass tools can re-read them.
    A literal path that does not exist, or a glob that matches nothing, raises
    :class:`FileNotFoundError`. ``"-"`` is kept as-is.
    """
    if isinstance(sources, (str, os.PathLike)):
        return list(_expand_path(_as_path_str(sources)))

    if _is_mapping_sequence(sources):
        return [list(sources)]  # type: ignore[arg-type]

    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes, bytearray)):
        resolved: list[str | list[Mapping[str, Any]]] = []
        for item in sources:
            if isinstance(item, (str, os.PathLike)):
                resolved.extend(_expand_path(_as_path_str(item)))
            elif _is_mapping_sequence(item):
                resolved.append(list(item))  # type: ignore[arg-type]
            else:
                resolved.append(_materialise_records(item))  # type: ignore[arg-type]
        return resolved

    # Bare iterable (generator) of mappings.
    return [_materialise_records(sources)]  # type: ignore[arg-type]


def _source_labels(sources: Sequence[str | list[Mapping[str, Any]]]) -> list[str]:
    labels: list[str] = []
    mem_index = 0
    for source in sources:
        if isinstance(source, str):
            labels.append(source)
        else:
            labels.append(memory_label(mem_index))
            mem_index += 1
    return labels


class Reader:
    """Stream records from files, stdin, or an in-memory iterable.

    Each yielded dict is a shallow copy of the parsed object with ``_id`` set.
    Blank lines are ignored. Non-JSON lines and JSON that is not an object are
    counted in :attr:`skipped_lines` and skipped.

    ``order="time"`` performs a streaming k-way merge by timestamp (see D2).
    """

    def __init__(
        self,
        sources: Source | Sequence[Source],
        *,
        after: str | None = None,
        complete: bool = True,
        order: Order = "concat",
    ) -> None:
        if order not in ("concat", "time"):
            raise ValueError(f"invalid order: {order!r}")
        self._sources = resolve_sources(sources)
        self._labels = _source_labels(self._sources)
        self._after = after
        self._complete = complete
        self._order: Order = order
        self.skipped_lines = 0
        self.last_id: str | None = None
        self.warnings: list[str] = []
        self._after_source: str | None = None
        self._after_line: int | None = None
        self._time_after: list[int] | None = None
        self._positions: list[int] = [0] * len(self._labels)
        if order == "time":
            for label in self._labels:
                if ";" in label:
                    raise ValueError(f"source label contains ';': {label}")
        if after is not None:
            if after.startswith("time;"):
                if order != "time":
                    raise CursorError(
                        "time cursor requires order='time'",
                        cursor=after,
                    )
                self._parse_time_cursor(after)
            else:
                if order == "time":
                    raise CursorError(
                        "concat cursor cannot be used with order='time'",
                        cursor=after,
                    )
                self._after_source, self._after_line = parse_id(after)
                self._validate_cursor(after)

    def _parse_time_cursor(self, after: str) -> None:
        body = after[len("time;") :]
        if body == "":
            raise CursorError("malformed time cursor", cursor=after)
        parts = body.split(";")
        if len(parts) != len(self._labels):
            raise CursorError(
                f"time cursor has {len(parts)} sources, expected {len(self._labels)}",
                cursor=after,
            )
        positions: list[int] = []
        for index, token in enumerate(parts):
            try:
                source, line = parse_id(token)
            except ValueError as exc:
                raise CursorError(f"malformed time cursor id: {token!r}", cursor=after) from exc
            if source != self._labels[index]:
                raise CursorError(
                    f"cursor source mismatch at index {index}: "
                    f"expected {self._labels[index]!r}, got {source!r}",
                    cursor=after,
                )
            self._validate_time_position(index, line, after)
            positions.append(line)
        self._time_after = positions
        self._positions = list(positions)

    def _validate_time_position(self, index: int, line: int, after: str) -> None:
        source = self._sources[index]
        label = self._labels[index]
        if isinstance(source, str):
            if source == "-":
                return
            total = _line_count(source)
            if line < 0 or line > total:
                raise CursorError(
                    f"cursor line {line} past end of {label} ({total} lines)",
                    cursor=after,
                )
            return
        # Memory time-cursor positions are consumed counts (0 = nothing).
        total = len(source)
        if line < 0 or line > total:
            raise CursorError(
                f"cursor line {line} past end of {label} ({total} records)",
                cursor=after,
            )

    def _validate_cursor(self, after: str) -> None:
        assert self._after_source is not None and self._after_line is not None
        if self._after_source not in self._labels:
            raise CursorError(
                f"cursor source not in input set: {self._after_source}",
                cursor=after,
            )
        index = self._labels.index(self._after_source)
        source = self._sources[index]
        if isinstance(source, str):
            if source == "-":
                return
            total = _line_count(source)
            if self._after_line > total:
                raise CursorError(
                    f"cursor line {self._after_line} past end of "
                    f"{self._after_source} ({total} lines)",
                    cursor=after,
                )
            return
        total = len(source)
        if self._after_line > total - 1 and total > 0:
            # Memory ids are 0-based indexes; after=mem:0 skips index 0.
            # Allow after at last index (skip all). Reject past last index.
            if self._after_line >= total:
                raise CursorError(
                    f"cursor line {self._after_line} past end of "
                    f"{self._after_source} ({total} records)",
                    cursor=after,
                )
        elif total == 0 and self._after_line > 0:
            raise CursorError(
                f"cursor line {self._after_line} past end of "
                f"{self._after_source} (0 records)",
                cursor=after,
            )

    def cursor(self) -> str:
        """Return a resume cursor for the current merge/concat position."""
        if self._order == "time":
            parts = [
                f"{label}:{pos}" for label, pos in zip(self._labels, self._positions, strict=True)
            ]
            return "time;" + ";".join(parts)
        return self.last_id or ""

    def _finalize_warnings(self, ooo: dict[str, int], unts: dict[str, int]) -> None:
        warnings: list[str] = []
        for label in self._labels:
            if label in ooo:
                warnings.append(f"out_of_order:{label}:{ooo[label]}")
            if label in unts:
                warnings.append(f"untimestamped:{label}:{unts[label]}")
        self.warnings = warnings

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.skipped_lines = 0
        self.last_id = None
        self.warnings = []
        if self._order == "time":
            yield from self._iter_merged()
            return
        past_after = self._after is None
        for source, label in zip(self._sources, self._labels, strict=True):
            if not past_after and label != self._after_source:
                continue
            if isinstance(source, str):
                yield from self._iter_text_path(source)
            else:
                yield from self._iter_memory(source, label)
            if label == self._after_source:
                past_after = True

    def _iter_merged(self) -> Iterator[dict[str, Any]]:
        ooo: dict[str, int] = {}
        unts: dict[str, int] = {}
        if self._time_after is not None:
            self._positions = list(self._time_after)
        else:
            self._positions = [0] * len(self._labels)

        sub_readers: list[Reader] = []
        iterators: list[Iterator[dict[str, Any]]] = []
        for index, source in enumerate(self._sources):
            label = self._labels[index]
            after: str | None = None
            if self._time_after is not None:
                pos = self._time_after[index]
                if pos > 0:
                    if isinstance(source, str):
                        after = f"{label}:{pos}"
                    else:
                        after = f"mem:{pos - 1}"
            sub = Reader(source, after=after, complete=self._complete, order="concat")
            sub_readers.append(sub)
            iterators.append(iter(sub))

        heap: list[tuple[datetime, int, int, dict[str, Any]]] = []
        last_ts: list[datetime | None] = [None] * len(self._sources)

        def push_next(source_index: int) -> None:
            try:
                record = next(iterators[source_index])
            except StopIteration:
                return
            label = self._labels[source_index]
            moment = parse_timestamp(record.get("timestamp"))
            prev = last_ts[source_index]
            if moment is None:
                unts[label] = unts.get(label, 0) + 1
                ts_key: datetime = prev if prev is not None else _DT_MIN
            else:
                ts_key = moment
            _, line_no = parse_id(record["_id"])
            heapq.heappush(heap, (ts_key, source_index, line_no, record))

        for index in range(len(self._sources)):
            push_next(index)

        try:
            while heap:
                ts_key, source_index, line_no, record = heapq.heappop(heap)
                label = self._labels[source_index]
                prev = last_ts[source_index]
                if prev is not None and ts_key < prev:
                    ooo[label] = ooo.get(label, 0) + 1
                last_ts[source_index] = ts_key

                # Rewrite memory _id to the outer label (mem, mem1, …).
                if not isinstance(self._sources[source_index], str):
                    inner_line = parse_id(record["_id"])[1]
                    record = dict(record)
                    record["_id"] = f"{label}:{inner_line}"
                    self._positions[source_index] = inner_line + 1
                else:
                    self._positions[source_index] = line_no

                self.last_id = record["_id"]
                yield record
                push_next(source_index)
        finally:
            self.skipped_lines = sum(sub.skipped_lines for sub in sub_readers)
            self._finalize_warnings(ooo, unts)

    def iter_lines(self) -> Iterator[tuple[str, int, str]]:
        """Yield ``(source_label, line_no, text)`` for every non-blank physical line.

        Blank lines are skipped. ``complete=False`` holds back an unterminated
        final line, matching record iteration. No JSON parsing is performed.
        """
        past_after = self._after is None
        for source, label in zip(self._sources, self._labels, strict=True):
            if not past_after and label != self._after_source:
                continue
            if isinstance(source, str):
                yield from self._iter_raw_path(source, label)
            else:
                for index, item in enumerate(source):
                    if (
                        label == self._after_source
                        and self._after_line is not None
                        and index <= self._after_line
                    ):
                        continue
                    text = item if isinstance(item, str) else json.dumps(item, default=str)
                    if not str(text).strip():
                        continue
                    yield label, index, str(text)
            if label == self._after_source:
                past_after = True

    def _iter_text_path(self, path: str) -> Iterator[dict[str, Any]]:
        if path == "-":
            yield from self._iter_text_stream(sys.stdin, "-")
            return
        with open(path, encoding="utf-8") as handle:
            yield from self._iter_text_stream(handle, path)

    def _iter_raw_path(
        self,
        path: str,
        label: str,
    ) -> Iterator[tuple[str, int, str]]:
        if path == "-":
            yield from self._iter_raw_stream(sys.stdin, label)
            return
        with open(path, encoding="utf-8") as handle:
            yield from self._iter_raw_stream(handle, label)

    def _iter_text_stream(
        self,
        stream: Iterable[str],
        source_label: str,
    ) -> Iterator[dict[str, Any]]:
        for line_no, text in self._physical_lines(stream, source_label):
            record = self._parse_line(text, source_label, line_no)
            if record is not None:
                self.last_id = record["_id"]
                yield record

    def _iter_raw_stream(
        self,
        stream: Iterable[str],
        source_label: str,
    ) -> Iterator[tuple[str, int, str]]:
        for line_no, text in self._physical_lines(stream, source_label):
            if not text.strip():
                continue
            yield source_label, line_no, text

    def _physical_lines(
        self,
        stream: Iterable[str],
        source_label: str,
    ) -> Iterator[tuple[int, str]]:
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
            yield line_no, text
        if pending is not None and self._complete:
            line_no += 1
            if not (
                source_label == self._after_source
                and self._after_line is not None
                and line_no <= self._after_line
            ):
                yield line_no, pending

    def _iter_memory(
        self,
        records: Iterable[Mapping[str, Any]],
        label: str,
    ) -> Iterator[dict[str, Any]]:
        for index, item in enumerate(records):
            if (
                label == self._after_source
                and self._after_line is not None
                and index <= self._after_line
            ):
                continue
            if not isinstance(item, Mapping):
                self.skipped_lines += 1
                continue
            record = dict(item)
            record["_id"] = f"{label}:{index}"
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
