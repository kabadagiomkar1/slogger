"""Stable finite-file capture and genuinely paged record access."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import sys
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.runtime import SourceOrigin
from ..errors import ToolError
from ..sources import decode_line
from .capture import bounded_lines
from .diagnostics import DiagnosticLog
from .models import CaptureStatus, Diagnostic, RecordIdentity, RecordPage, SourceBoundary
from .resources import ManagedStorage, ResourceLimits, ResourceUsage, resident_size

_INDEX = struct.Struct("<QQQQ")


class Investigation:
    """One stable disk dataset. Open explicitly; close releases owned storage."""

    def __init__(self, storage: ManagedStorage) -> None:
        self.storage = storage
        self.limits = storage.limits
        self.dataset_id = uuid.uuid4().hex
        self.sources: tuple[SourceBoundary, ...] = ()
        self.status = CaptureStatus("capturing")
        self.diagnostics = DiagnosticLog(storage)
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._cache_bytes = 0
        self._data = storage.create_file("records.jsonl")
        self._index = storage.create_file("records.index")

    @classmethod
    def open(
        cls,
        paths: Sequence[str | os.PathLike[str]],
        *,
        storage_dir: str | os.PathLike[str] | None = None,
        limits: ResourceLimits | None = None,
    ) -> Investigation:
        """Capture regular files in supplied order, including repeated occurrences.

        Errors produce a failed, non-ready session with diagnostic context. Invalid
        resource configuration raises ValueError; storage setup failures raise ToolError.
        """
        try:
            storage = ManagedStorage(
                Path(storage_dir) if storage_dir is not None else None, limits or ResourceLimits()
            )
        except OSError as error:
            raise ToolError(
                "storage_failed", f"Cannot create investigation storage: {error}"
            ) from error
        try:
            session = cls(storage)
        except Exception:
            storage.close()
            raise
        try:
            session._capture(paths)
        except BaseException:
            storage.close()
            raise
        return session

    @property
    def resources(self) -> ResourceUsage:
        return replace(self.storage.usage, ram_cache_bytes=self._cache_bytes)

    def _capture(self, paths: Sequence[str | os.PathLike[str]]) -> None:
        active_origin = None
        active_source = None
        occurrence = None
        try:
            with ExitStack() as stack:
                inputs = []
                boundaries = []
                for occurrence, path in enumerate(paths):
                    label = os.fspath(path)
                    handle = stack.enter_context(
                        open(
                            label,
                            "rb",
                            opener=lambda path, flags: os.open(
                                path, flags | getattr(os, "O_NONBLOCK", 0)
                            ),
                        )
                    )
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise ToolError(
                            "source_invalid", f"Input must be a finite regular file: {label}"
                        )
                    boundaries.append(
                        SourceBoundary(label, occurrence, info.st_size, info.st_dev, info.st_ino)
                    )
                    inputs.append(handle)
                self.sources = tuple(boundaries)
                self.status = replace(
                    self.status, total_bytes=sum(b.byte_length for b in boundaries)
                )
                digests = []
                for boundary, handle in zip(boundaries, inputs, strict=True):
                    occurrence = boundary.input_occurrence
                    active_source = boundary.source
                    active_origin = None
                    digest = hashlib.sha256()
                    for line, raw in enumerate(
                        bounded_lines(handle, boundary.byte_length, self.limits.max_record_bytes), 1
                    ):
                        origin = SourceOrigin(boundary.source, line, "file")
                        active_origin = origin
                        digest.update(raw)
                        record, reason = decode_line(raw.decode("utf-8"))
                        self.status = replace(
                            self.status, captured_bytes=self.status.captured_bytes + len(raw)
                        )
                        if reason is not None:
                            self.diagnostics.append(
                                Diagnostic(
                                    reason,
                                    f"Skipped {reason} line.",
                                    origin,
                                    boundary.input_occurrence,
                                )
                            )
                            self.status = replace(
                                self.status, skipped_lines=self.status.skipped_lines + 1
                            )
                        elif record is not None:
                            size = resident_size(record)
                            pretty = json.dumps(record, indent=2, ensure_ascii=False)
                            pretty_size = sys.getsizeof(pretty) + resident_size(pretty.splitlines())
                            if (
                                size + pretty_size + 4 * len(raw) > self.limits.working_memory_bytes
                                or size + 128 > self.limits.page_memory_bytes
                            ):
                                raise ToolError(
                                    "record_too_large",
                                    f"Decoded record exceeds working/page memory admission: "
                                    f"{boundary.source}:{line}",
                                )
                            offset = self._data.stat().st_size
                            self.storage.append(self._data, raw)
                            try:
                                self.storage.append(
                                    self._index,
                                    _INDEX.pack(offset, len(raw), boundary.input_occurrence, line),
                                )
                            except Exception:
                                self.storage.truncate(self._data, offset)
                                raise
                            self.status = replace(
                                self.status, record_count=self.status.record_count + 1
                            )
                    digests.append(digest.digest())
                for boundary, handle, captured_digest in zip(
                    boundaries, inputs, digests, strict=True
                ):
                    occurrence = boundary.input_occurrence
                    active_source = boundary.source
                    active_origin = None
                    info = os.stat(boundary.source)
                    if (info.st_dev, info.st_ino) != (boundary.device, boundary.inode):
                        raise ToolError("source_changed", f"Source replaced: {boundary.source}")
                    handle.seek(0)
                    verified = hashlib.sha256()
                    remaining = boundary.byte_length
                    while remaining:
                        chunk = handle.read(min(remaining, 64 * 1024))
                        if not chunk:
                            raise ToolError(
                                "source_changed", f"Source truncated: {boundary.source}"
                            )
                        verified.update(chunk)
                        remaining -= len(chunk)
                    info = os.stat(boundary.source)
                    if (info.st_dev, info.st_ino) != (
                        boundary.device,
                        boundary.inode,
                    ) or verified.digest() != captured_digest:
                        raise ToolError("source_changed", f"Source mutated: {boundary.source}")
                self.status = replace(self.status, phase="complete")
        except (OSError, UnicodeError, ToolError, RecursionError, ValueError) as error:
            code = error.code if isinstance(error, ToolError) else "capture_failed"
            if (
                active_source is not None
                and isinstance(error, ToolError)
                and isinstance(error.extra.get("position"), int)
            ):
                active_origin = SourceOrigin(active_source, error.extra["position"], "file")
            self.diagnostics.terminal = Diagnostic(code, str(error), active_origin, occurrence)
            self.status = replace(self.status, phase="failed")

    def require_ready(self, operation: str) -> None:
        """Shared gate used before every complete-dataset operation."""
        if not self.status.complete:
            raise ToolError(
                "dataset_incomplete",
                f"{operation} requires a complete dataset.",
                dataset_id=self.dataset_id,
                phase=self.status.phase,
            )

    def page(self, offset: int = 0, limit: int = 100) -> RecordPage:
        if self.status.phase == "closed":
            raise ToolError("session_closed", "Investigation is closed.")
        if offset < 0 or limit < 0 or limit > self.limits.max_page_records:
            raise ValueError("page offset/limit must be nonnegative and limit <= max_page_records")
        records: list[dict[str, Any]] = []
        origins = []
        identities = []
        page_bytes = 0
        with self._index.open("rb") as index, self._data.open("rb") as data:
            index.seek(offset * _INDEX.size)
            for ordinal in range(offset, min(offset + limit, self.status.record_count)):
                start, length, occurrence, line = _INDEX.unpack(index.read(_INDEX.size))
                raw = self._cache.get(ordinal)
                if raw is None:
                    data.seek(start)
                    raw = data.read(length)
                    cache_cost = sys.getsizeof(raw) + 128
                    if cache_cost <= self.limits.ram_cache_bytes:
                        while self._cache_bytes + cache_cost > self.limits.ram_cache_bytes:
                            _, old = self._cache.popitem(last=False)
                            self._cache_bytes -= sys.getsizeof(old) + 128
                        self._cache[ordinal] = raw
                        self._cache_bytes += cache_cost
                else:
                    self._cache.move_to_end(ordinal)
                record = json.loads(raw)
                cost = resident_size(record) + 128
                if page_bytes + cost > self.limits.page_memory_bytes:
                    break
                page_bytes += cost
                records.append(record)
                origins.append(SourceOrigin(self.sources[occurrence].source, line, "file"))
                identities.append(RecordIdentity(self.dataset_id, ordinal, occurrence))
        return RecordPage(
            self.dataset_id,
            offset,
            records,
            origins,
            identities,
            offset + len(records),
            self.status.complete,
        )

    def diagnostic_page(self, offset: int = 0, limit: int = 100) -> list[Diagnostic]:
        if self.status.phase == "closed":
            raise ToolError("session_closed", "Investigation is closed.")
        if offset < 0 or limit < 0 or limit > self.limits.max_page_records:
            raise ValueError("diagnostic offset/limit exceed the page contract")
        return self.diagnostics[offset : offset + limit]

    def close(self) -> None:
        self._cache.clear()
        self._cache_bytes = 0
        self.storage.close()
        self.status = replace(self.status, phase="closed")

    def __enter__(self) -> Investigation:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
