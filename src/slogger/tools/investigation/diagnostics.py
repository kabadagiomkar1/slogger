"""Complete, disk-backed capture diagnostics with bounded read delivery."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator, Sequence
from dataclasses import asdict
from typing import overload

from ..core.runtime import SourceOrigin
from .models import Diagnostic
from .resources import ManagedStorage

_INDEX = struct.Struct("<QQ")


class DiagnosticLog(Sequence[Diagnostic]):
    """Iterates one diagnostic at a time; slices are deliberately page bounded."""

    def __init__(self, storage: ManagedStorage) -> None:
        self.storage = storage
        self._data = storage.create_file("diagnostics.jsonl")
        self._index = storage.create_file("diagnostics.index")
        self._count = 0
        self.terminal: Diagnostic | None = None

    def append(self, diagnostic: Diagnostic) -> None:
        raw = json.dumps(asdict(diagnostic), ensure_ascii=False).encode("utf-8")
        offset = self._data.stat().st_size
        self.storage.append(self._data, raw)
        try:
            self.storage.append(self._index, _INDEX.pack(offset, len(raw)))
        except Exception:
            self.storage.truncate(self._data, offset)
            raise
        self._count += 1

    def __len__(self) -> int:
        return self._count + (self.terminal is not None)

    @overload
    def __getitem__(self, key: int) -> Diagnostic: ...
    @overload
    def __getitem__(self, key: slice) -> list[Diagnostic]: ...

    def __getitem__(self, key: int | slice) -> Diagnostic | list[Diagnostic]:
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if len(range(start, stop, step)) > self.storage.limits.max_page_records:
                raise ValueError("diagnostic slice exceeds max_page_records")
            return [self[position] for position in range(start, stop, step)]
        if key < 0:
            key += len(self)
        if not 0 <= key < len(self):
            raise IndexError(key)
        if key == self._count and self.terminal is not None:
            return self.terminal
        with self._index.open("rb") as index, self._data.open("rb") as data:
            index.seek(key * _INDEX.size)
            offset, length = _INDEX.unpack(index.read(_INDEX.size))
            data.seek(offset)
            value = json.loads(data.read(length))
        return Diagnostic(
            value["code"],
            value["message"],
            SourceOrigin(**value["origin"]) if value["origin"] else None,
            value["input_occurrence"],
        )

    def __iter__(self) -> Iterator[Diagnostic]:
        for index in range(len(self)):
            yield self[index]
