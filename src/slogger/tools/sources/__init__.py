"""Finite source decoding and ordering, shared by execution adapters."""

from __future__ import annotations

import copy
import glob
import heapq
import json
import os
import re
import sys
from collections.abc import Generator, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Literal, cast

from ..core.runtime import RecordRow, SourceOrigin

Source = str | os.PathLike[str] | Iterable[Mapping[str, Any]]
Order = Literal["concat", "time"]
_ROTATION_SUFFIX = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)$")
_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)


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


def _resolve(sources: Source | Sequence[Source]) -> list[Source]:
    if isinstance(sources, (str, os.PathLike)):
        return list(_expand_path(os.fspath(sources)))
    if isinstance(sources, Sequence) and (not sources or isinstance(sources[0], Mapping)):
        return [cast(Iterable[Mapping[str, Any]], sources)]
    if isinstance(sources, Sequence):
        result: list[Source] = []
        for item in sources:
            if isinstance(item, (str, os.PathLike)):
                result.extend(_expand_path(os.fspath(item)))
            else:
                result.append(cast(Source, item))
        return result
    return [sources]


class Sources:
    """One execution's finite inputs; only owned file streams are closed."""

    def __init__(self, inputs: Source | Sequence[Source], *, order: Order) -> None:
        self.inputs = inputs
        self.order = order
        self.warnings: list[str] = []
        self.skipped_lines = 0
        self.consumed = 0
        self._iterator = self._rows()

    def __iter__(self) -> Generator[RecordRow, None, None]:
        return self._iterator

    def close(self) -> None:
        self._iterator.close()

    def _input(
        self, source: Source, label: str
    ) -> Generator[tuple[dict[str, Any], SourceOrigin], None, None]:
        if isinstance(source, (str, os.PathLike)):
            path = os.fspath(source)
            if path == "-":
                yield from self._text(sys.stdin, label, "stdin")
            else:
                with open(path, encoding="utf-8") as handle:
                    yield from self._text(handle, label, "file")
        else:
            for position, item in enumerate(source):
                if not isinstance(item, Mapping):
                    self.skipped_lines += 1
                    continue
                yield copy.deepcopy(dict(item)), SourceOrigin(label, position, "iterable")

    def _text(
        self, stream: Iterable[str], label: str, kind: str
    ) -> Generator[tuple[dict[str, Any], SourceOrigin], None, None]:
        for position, text in enumerate(stream, 1):
            if not text.strip():
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                self.skipped_lines += 1
                continue
            if not isinstance(record, dict):
                self.skipped_lines += 1
                continue
            yield record, SourceOrigin(label, position, kind)

    def _rows(self) -> Generator[RecordRow, None, None]:
        sources = _resolve(self.inputs)
        memory_index = 0
        inputs = []
        for source in sources:
            if isinstance(source, (str, os.PathLike)):
                label = os.fspath(source)
            else:
                label = "mem" if memory_index == 0 else f"mem{memory_index}"
                memory_index += 1
            inputs.append(self._input(source, label))
        pairs = (
            self._merge(inputs)
            if self.order == "time"
            else (pair for iterator in inputs for pair in iterator)
        )
        try:
            for record, origin in pairs:
                ordinal = self.consumed
                self.consumed += 1
                yield RecordRow(record, ordinal, origin)
        finally:
            pairs.close()
            for iterator in inputs:
                iterator.close()

    def _merge(
        self, inputs: list[Generator[tuple[dict[str, Any], SourceOrigin], None, None]]
    ) -> Generator[tuple[dict[str, Any], SourceOrigin], None, None]:
        heap: list[tuple[datetime, int, dict[str, Any], SourceOrigin]] = []
        previous: list[datetime | None] = [None] * len(inputs)
        counts: dict[tuple[str, str], int] = {}
        labels: dict[int, str] = {}

        def advance(index: int) -> None:
            try:
                record, origin = next(inputs[index])
            except StopIteration:
                return
            labels[index] = origin.source
            moment = parse_timestamp(record.get("timestamp"))
            if moment is None:
                key = (origin.source, "untimestamped")
                counts[key] = counts.get(key, 0) + 1
                moment = previous[index] or _DT_MIN
            heapq.heappush(heap, (moment, index, record, origin))

        try:
            for index in range(len(inputs)):
                advance(index)
            while heap:
                moment, index, record, origin = heapq.heappop(heap)
                prev = previous[index]
                if prev is not None and moment < prev:
                    key = (origin.source, "out_of_order")
                    counts[key] = counts.get(key, 0) + 1
                previous[index] = moment
                yield record, origin
                advance(index)
        finally:
            self.warnings = [
                f"{kind}:{label}:{counts[(label, kind)]}"
                for label in (labels[index] for index in sorted(labels))
                for kind in ("out_of_order", "untimestamped")
                if (label, kind) in counts
            ]
