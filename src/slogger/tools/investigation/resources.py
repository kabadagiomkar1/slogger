"""Admission and allocation accounting shared by capture and later disk jobs."""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from .cache import CacheLease

from ..errors import ToolError


@dataclass(frozen=True)
class ResourceLimits:
    """Configurable admission limits, not a total-process RSS guarantee."""

    disk_bytes: int = 10 * 1024**3
    ram_cache_bytes: int = 256 * 1024**2
    max_record_bytes: int = 8 * 1024**2
    working_memory_bytes: int = 64 * 1024**2
    page_memory_bytes: int = 16 * 1024**2
    max_page_records: int = 256

    def __post_init__(self) -> None:
        if any(value <= 0 for value in self.__dict__.values()):
            raise ValueError("resource limits must be positive")


@dataclass(frozen=True)
class ResourceUsage:
    disk_bytes: int
    reserved_disk_bytes: int
    ram_cache_bytes: int = 0

    @property
    def managed_disk_bytes(self) -> int:
        return self.disk_bytes + self.reserved_disk_bytes


class ManagedStorage:
    """Session-owned files with admission before growth and allocation accounting.

    Every capture/index/result/spill file must be created here. Later persistent
    cache ownership adds cross-process admission; this object owns one session.
    """

    def __init__(
        self, parent: Path | None, limits: ResourceLimits, *, lease: CacheLease | None = None
    ) -> None:
        if not hasattr(os, "statvfs"):
            raise ToolError(
                "platform_unsupported",
                "Investigation storage requires POSIX allocation accounting.",
            )
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        self._lease = lease
        self._retain = False
        self.root = (
            lease.root
            if lease
            else Path(tempfile.mkdtemp(prefix="slogger-investigation-", dir=parent))
        )
        self.limits = limits
        self._reserved = 0
        self._lock = threading.RLock()
        self._allocation: dict[Path, int] = {}
        self._writers: set[StorageWriter] = set()
        self._closed = False
        try:
            self._block = os.statvfs(self.root).f_frsize or 4096
            self._reconcile(self.root)
            if lease is not None:
                self._reconcile(self.root / ".lease")
            self._check()
        except (OSError, ToolError):
            self.close()
            raise

    def _reconcile(self, path: Path) -> None:
        try:
            info = path.stat()
        except FileNotFoundError:
            self._allocation.pop(path, None)
            return
        self._allocation[path] = max(info.st_size, getattr(info, "st_blocks", 0) * 512)

    @property
    def usage(self) -> ResourceUsage:
        with self._lock:
            if not self._closed:
                for path in tuple(self._allocation):
                    self._reconcile(path)
            return self._usage()

    def _usage(self) -> ResourceUsage:
        return ResourceUsage(sum(self._allocation.values()), self._reserved)

    def _check(self) -> None:
        if self._lease is not None:
            self._lease.owner.update(self.root, sum(self._allocation.values()), self._reserved)
        if self._usage().managed_disk_bytes > self.limits.disk_bytes:
            raise ToolError("resource_limit", "Managed disk budget exhausted; increase disk_bytes.")

    def create_file(self, name: str) -> Path:
        with self._lock:
            if self._closed:
                raise ToolError("session_closed", "Managed storage is closed.")
            if Path(name).name != name:
                raise ValueError("managed files require a single filename")
            path = self.root / name
            path.touch(exist_ok=False)
            try:
                self._reconcile(path)
                self._reconcile(self.root)
                self._check()
            except (OSError, ToolError):
                path.unlink()
                self._allocation.pop(path, None)
                self._reconcile(self.root)
                raise
            return path

    @contextmanager
    def reserve(self, byte_count: int) -> Iterator[None]:
        """Reserve disk growth before a job creates or allocates its output."""
        with self._lock:
            if self._closed:
                raise ToolError("session_closed", "Managed storage is closed.")
            if byte_count < 0:
                raise ValueError("reservation must be nonnegative")
            self._reserved += byte_count
            try:
                self._check()
                yield
            finally:
                self._reserved -= byte_count
                self._sync()

    def writer(self, *paths: Path) -> StorageWriter:
        """Open a bounded transactional writer for exclusively owned managed files.

        Stage reserves projected block growth without scanning files. Flush checks
        changed-file allocation and rolls every member back on any write failure.
        Consumers publish their row/count metadata only after a successful flush.
        """
        with self._lock:
            if len(set(paths)) != len(paths) or self.root in paths:
                raise ValueError("writer requires distinct managed files")
            if self._closed or any(path not in self._allocation for path in paths):
                raise ToolError("session_closed", "Cannot write outside active managed storage.")
            if any(set(paths).intersection(writer.paths) for writer in self._writers):
                raise ValueError("managed file already has an active writer")
            writer = StorageWriter(self, paths)
            self._writers.add(writer)
            return writer

    def append(self, path: Path, data: bytes) -> None:
        with self.writer(path) as writer:
            writer.stage({path: data})
            writer.flush()

    def truncate(self, path: Path, byte_count: int) -> None:
        with self._lock:
            if path not in self._allocation or path == self.root:
                raise ValueError("not a managed file")
            if any(path in writer.paths for writer in self._writers):
                raise ValueError("managed file has an active writer")
            if byte_count < 0 or byte_count > path.stat().st_size:
                raise ValueError("truncate cannot grow a managed file")
            with path.open("r+b") as handle:
                handle.truncate(byte_count)
            self._reconcile(path)

    def remove_file(self, path: Path) -> None:
        """Remove an owned file after all writer/database handles are closed."""
        with self._lock:
            if path.parent != self.root:
                raise ValueError("not a managed file")
            if self._closed:
                return
            if any(path in writer.paths for writer in self._writers):
                raise ToolError("storage_busy", "Managed file has an active writer.")
            path.unlink(missing_ok=True)
            self._allocation.pop(path, None)
            self._reconcile(self.root)
            self._sync()

    def _sync(self) -> None:
        if self._lease is not None:
            self._lease.owner.update(self.root, sum(self._allocation.values()), self._reserved)

    @contextmanager
    def external_growth(self, *paths: Path, byte_count: int) -> Iterator[None]:
        """Admit external database growth and reconcile files/sidecars on exit.

        The caller must enforce its engine's growth ceiling before writing and
        close database handles before deletion. Reservations are consumed before
        checking actual allocation, so committed growth is not charged twice.
        """
        with self._lock:
            if self._closed or any(path not in self._allocation for path in paths):
                raise ToolError("session_closed", "Cannot grow outside active managed storage.")
            if byte_count < 0:
                raise ValueError("reservation must be nonnegative")
            if any(set(paths).intersection(writer.paths) for writer in self._writers):
                raise ToolError("storage_busy", "Managed file has an active writer.")
            self._reserved += byte_count
            try:
                self._check()
                yield
            finally:
                self._reserved -= byte_count
                for path in tuple(self._allocation):
                    self._reconcile(path)
                for path in self.root.iterdir():
                    if path.is_file():
                        self._reconcile(path)
                self._reconcile(self.root)
                self._check()

    def retain(self) -> None:
        """Retain a published immutable capture when its session closes."""
        self._retain = True
        self._retained_paths = set(self._allocation)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                for writer in tuple(self._writers):
                    writer.close()
                if self._lease is None:
                    shutil.rmtree(self.root)
                elif self._retain:
                    for path in tuple(self._allocation):
                        if path not in self._retained_paths:
                            path.unlink(missing_ok=True)
                            self._allocation.pop(path, None)
                    self._reconcile(self.root)
                    self._reserved = 0
                    self._sync()
                    self._lease.close()
                else:
                    self._lease.owner.forget(self._lease)
                self._closed = True
                self._allocation.clear()


class StorageWriter:
    """One bounded batch, persistent handles, and atomic data/index rollback."""

    def __init__(self, storage: ManagedStorage, paths: tuple[Path, ...]) -> None:
        self.storage = storage
        self.paths = paths
        self._handles: dict[Path, BinaryIO] = {}
        self._pending = {path: bytearray() for path in paths}
        self._offsets: dict[Path, int] = {}
        self._reserved = 0
        self._closed = False
        try:
            for path in paths:
                handle = path.open("r+b", buffering=0)
                self._handles[path] = handle
                self._offsets[path] = handle.seek(0, os.SEEK_END)
        except BaseException:
            for handle in self._handles.values():
                handle.close()
            raise

    @property
    def pending_bytes(self) -> int:
        return sum(len(buffer) for buffer in self._pending.values())

    def offset(self, path: Path) -> int:
        return self._offsets[path] + len(self._pending[path])

    def stage(self, chunks: dict[Path, bytes]) -> None:
        """Admit a pair/batch without publishing it; caller bounds buffered memory."""
        with self.storage._lock:
            if self._closed:
                raise ToolError("session_closed", "Managed writer is closed.")
            if any(path not in self._pending for path in chunks):
                raise ValueError("not a writer-owned file")
            if self.pending_bytes + sum(map(len, chunks.values())) > (
                self.storage.limits.working_memory_bytes // 4
            ):
                raise ToolError("resource_limit", "Managed write batch exceeds working memory.")
            reserved = 0
            for path in self.paths:
                length = self.offset(path) + len(chunks.get(path, b""))
                predicted = math.ceil(length / self.storage._block) * self.storage._block
                reserved += max(0, predicted - self.storage._allocation[path])
            extra = reserved - self._reserved
            self.storage._reserved += extra
            try:
                self.storage._check()
                for path, chunk in chunks.items():
                    self._pending[path].extend(chunk)
            except BaseException:
                self.storage._reserved -= extra
                self.storage._sync()
                raise
            self._reserved = reserved

    def flush(self) -> None:
        with self.storage._lock:
            if self._closed:
                raise ToolError("session_closed", "Managed writer is closed.")
            changed = [path for path in self.paths if self._pending[path]]
            self.storage._reserved -= self._reserved
            self._reserved = 0
            try:
                for path in changed:
                    handle = self._handles[path]
                    buffer = memoryview(self._pending[path])
                    try:
                        while buffer:
                            written = handle.write(buffer)
                            if not written:
                                raise OSError("Managed write made no progress.")
                            buffer = buffer[written:]
                    finally:
                        buffer.release()
                    self.storage._reconcile(path)
                self.storage._check()
            except BaseException:
                for path in changed:
                    handle = self._handles[path]
                    handle.truncate(self._offsets[path])
                    handle.seek(self._offsets[path])
                    self.storage._reconcile(path)
                raise
            else:
                for path in changed:
                    self._offsets[path] += len(self._pending[path])
            finally:
                for path in changed:
                    self._pending[path].clear()
                self.storage._sync()

    def close(self) -> None:
        with self.storage._lock:
            if not self._closed:
                self.storage._reserved -= self._reserved
                self._reserved = 0
                for handle in self._handles.values():
                    handle.close()
                for buffer in self._pending.values():
                    buffer.clear()
                self.storage._writers.discard(self)
                self.storage._sync()
                self._closed = True

    def __enter__(self) -> StorageWriter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def resident_size(value: object) -> int:
    """Conservative decoded-object size, counting repeated references separately."""
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(resident_size(k) + resident_size(v) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(resident_size(item) for item in value)
    return size
