"""Admission and allocation accounting shared by capture and later disk jobs."""

from __future__ import annotations

import math
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, ContextManager

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
        if any(type(value) is not int or value <= 0 for value in self.__dict__.values()):
            raise ValueError("resource limits must be positive integers")


@dataclass(frozen=True)
class ResourceUsage:
    disk_bytes: int
    reserved_disk_bytes: int
    ram_cache_bytes: int = 0
    catalog_reserve_bytes: int = 0

    @property
    def managed_disk_bytes(self) -> int:
        return self.disk_bytes + self.reserved_disk_bytes + self.catalog_reserve_bytes


@dataclass(frozen=True)
class ResourceConfiguration:
    """Effective session configuration after a validated runtime change."""

    limits: ResourceLimits
    cache_expiry_seconds: float | None
    usage: ResourceUsage


class SharedDiskBudget:
    """One total admission ledger for temporary owners participating in refresh."""

    def __init__(self, disk_bytes: int) -> None:
        self.disk_bytes = disk_bytes
        self._lock = threading.RLock()
        self._owners: dict[Path, tuple[int, int]] = {}

    @property
    def usage(self) -> ResourceUsage:
        with self._lock:
            return ResourceUsage(
                sum(value[0] for value in self._owners.values()),
                sum(value[1] for value in self._owners.values()),
            )

    def update(self, root: Path, actual: int, reserved: int, *, admit: bool = False) -> None:
        with self._lock:
            self._owners[root] = actual, reserved
            if admit and self.usage.managed_disk_bytes > self.disk_bytes:
                raise ToolError(
                    "resource_limit", "Combined active and replacement disk budget exhausted."
                )

    def remove(self, root: Path) -> None:
        with self._lock:
            self._owners.pop(root, None)


class ManagedStorage:
    """Session-owned files with admission before growth and allocation accounting.

    Every capture/index/result/spill file must be created here. Later persistent
    cache ownership adds cross-process admission; this object owns one session.
    """

    def __init__(
        self,
        parent: Path | None,
        limits: ResourceLimits,
        *,
        lease: CacheLease | None = None,
        disk_budget: SharedDiskBudget | None = None,
    ) -> None:
        if not hasattr(os, "statvfs"):
            raise ToolError(
                "platform_unsupported",
                "Investigation storage requires POSIX allocation accounting.",
            )
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        self._lease = lease
        self._disk_budget = disk_budget
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
        self._engine_paths: set[Path] = set()
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
            self._sync()
            return self._disk_budget.usage if self._disk_budget is not None else self._usage()

    def share_budget(self) -> SharedDiskBudget:
        """Attach this temporary owner once, preserving its observed allocation."""
        with self._lock:
            if self._lease is not None:
                raise ValueError("Durable storage already has a global admission owner.")
            if self._disk_budget is None:
                self._disk_budget = SharedDiskBudget(self.limits.disk_bytes)
                self._disk_budget.update(
                    self.root, sum(self._allocation.values()), self._reserved, admit=True
                )
            return self._disk_budget

    def _usage(self) -> ResourceUsage:
        return ResourceUsage(sum(self._allocation.values()), self._reserved)

    def _check(self) -> None:
        if self._disk_budget is not None:
            self._disk_budget.update(
                self.root, sum(self._allocation.values()), self._reserved, admit=True
            )
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
                self._sync()
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
            if set(paths).intersection(self._engine_paths) or any(
                set(paths).intersection(writer.paths) for writer in self._writers
            ):
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
            if path in self._engine_paths or any(
                path in writer._handles for writer in self._writers
            ):
                raise ValueError("managed file has an active writer")
            if byte_count < 0 or byte_count > path.stat().st_size:
                raise ValueError("truncate cannot grow a managed file")
            with path.open("r+b") as handle:
                handle.truncate(byte_count)
            self._reconcile(path)
            self._sync()

    def remove_file(self, path: Path) -> None:
        """Remove an owned file after all writer/database handles are closed."""
        with self._lock:
            if path.parent != self.root:
                raise ValueError("not a managed file")
            if self._closed:
                return
            if path in self._engine_paths or any(path in writer.paths for writer in self._writers):
                raise ToolError("storage_busy", "Managed file has an active writer.")
            path.unlink(missing_ok=True)
            self._allocation.pop(path, None)
            self._reconcile(self.root)
            self._sync()

    def _sync(self) -> None:
        if self._closed:
            return
        if self._disk_budget is not None:
            self._disk_budget.update(self.root, sum(self._allocation.values()), self._reserved)
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
            if set(paths).intersection(self._engine_paths) or any(
                set(paths).intersection(writer.paths) for writer in self._writers
            ):
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

    @contextmanager
    def sqlite_growth(self, path: Path, byte_count: int) -> Iterator[None]:
        """Keep an admitted engine grant while releasing the ledger lock in its body.

        The SQLite owner enforces max_page_count with journal/WAL disabled, and
        settles transactions before exit. A full outstanding grant remains
        conservative even when another reader reconciles already allocated growth.
        Never credit a different writer's growth or discard a live reservation.
        """
        with self._lock:
            if self._closed or path not in self._allocation:
                raise ToolError("session_closed", "Cannot grow outside active managed storage.")
            if byte_count < 0:
                raise ValueError("reservation must be nonnegative")
            if path in self._engine_paths or any(path in writer.paths for writer in self._writers):
                raise ToolError("storage_busy", "Managed file has an active writer.")
            self._reserved += byte_count
            try:
                self._check()
            except BaseException:
                self._reserved -= byte_count
                self._sync()
                raise
            self._engine_paths.add(path)
        try:
            yield
        finally:
            with self._lock:
                self._reserved -= byte_count
                self._engine_paths.remove(path)
                for owned in tuple(self._allocation):
                    self._reconcile(owned)
                for owned in self.root.iterdir():
                    if owned.is_file():
                        self._reconcile(owned)
                self._reconcile(self.root)
                self._check()

    def retain(self) -> None:
        """Retain a published immutable capture when its session closes."""
        self._retain = True
        self._retained_paths = set(self._allocation)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                if self._engine_paths:
                    raise ToolError("storage_busy", "Managed SQLite writer has not settled.")
                for writer in tuple(self._writers):
                    writer.close()
                if self._lease is None:
                    try:
                        shutil.rmtree(self.root)
                    except FileNotFoundError:
                        if self.root.exists():
                            raise
                    except BaseException:
                        for path in tuple(self._allocation):
                            self._reconcile(path)
                        self._sync()
                        raise
                    if self._disk_budget is not None:
                        self._disk_budget.remove(self.root)
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
                # Existing allocated+reserved capacity already covers these bytes.
                # Configuration publishes limit changes independently; only a
                # changed grant needs another durable/global admission update.
                if extra:
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


class SqliteBatch:
    """Bounded unpublished writes with reservation before every engine window.

    Queued callbacks retain at most 64 charged payloads, capped at 64 KiB or 1/16
    of execution memory. One larger, caller-admitted callback executes alone.
    The storage lock covers only a flush, never input reads or a whole dataset.
    Callers flush before dependent SQL reads and before publishing a result.
    """

    def __init__(
        self,
        storage: ManagedStorage,
        connection: sqlite3.Connection,
        path: Path,
        check: Callable[[], None],
        growth_factor: int,
    ) -> None:
        self.storage, self.connection, self.path = storage, connection, path
        self.check, self.growth_factor = check, growth_factor
        self._limit = min(65536, max(1, storage.limits.working_memory_bytes // 16))
        self._operations: list[tuple[Callable[[], object], int]] = []
        self._charged = 0
        self._closed = False

    def write(self, operation: Callable[[], object], payload: int = 0) -> None:
        if self._closed:
            raise ValueError("SQLite batch is closed")
        if payload < 0:
            raise ValueError("SQLite payload must be nonnegative")
        self.check()
        charge = payload + resident_size(getattr(operation, "__defaults__", ())) + 512
        # Count retained default references conservatively, even when shared.
        if self._operations and (
            len(self._operations) >= 64 or self._charged + charge > self._limit
        ):
            self.flush()
        self._operations.append((operation, payload))
        self._charged += charge
        if charge > self._limit:
            self.flush()

    def flush(self) -> None:
        if not self._operations:
            return
        self.check()
        pending, self._operations = self._operations, []
        self._charged = 0
        self._flush_range(pending, 0, len(pending))

    def _flush_range(
        self, pending: list[tuple[Callable[[], object], int]], start: int, end: int
    ) -> None:
        self.check()
        pages = self.connection.execute("PRAGMA page_count").fetchone()[0]
        payload = sum(pending[index][1] for index in range(start, end))
        allowance = (
            self.growth_factor * (end - start) * (max(1, pages).bit_length() + 2)
            + math.ceil(payload * 4 / 4096)
        ) * 4096
        entered = False
        try:
            with self.storage.external_growth(self.path, byte_count=allowance):
                entered = True
                self.connection.execute(f"PRAGMA max_page_count={pages + allowance // 4096}")
                with self.connection:
                    for index in range(start, end):
                        self.check()
                        pending[index][0]()
        except ToolError as error:
            # Only a refused grant before any engine activity permits subdivision.
            # Journal-OFF SQL/commit failures are never retried as if rolled back.
            if entered or error.code != "resource_limit" or end - start == 1:
                raise
            middle = (start + end) // 2
            self._flush_range(pending, start, middle)
            self._flush_range(pending, middle, end)

    def __enter__(self) -> SqliteBatch:
        return self

    def __exit__(self, kind: object, _error: object, _traceback: object) -> None:
        try:
            if kind is None:
                self.flush()
        finally:
            self._operations.clear()
            self._charged = 0
            self._closed = True


class SqliteGrantRefused(ToolError):
    """Internal proof that no engine activity occurred in a refused window."""

    def __init__(self, message: str) -> None:
        super().__init__("resource_limit", message)


class SqliteWindow:
    """Immediate exact SQL in bounded admitted windows with an unlocked body.

    At most 64 operations, 64KiB declared payload, or 50ms between worker checks share
    a grant. These are accounting checkpoints, not result caps or latency promises.
    Point reads on the sole writer connection see every preceding statement.
    Pre-write grant refusal downshifts to one operation; engine failure never retries.
    """

    def __init__(
        self,
        storage: ManagedStorage,
        connection: sqlite3.Connection,
        path: Path,
        check: Callable[[], None],
        growth_factor: int,
    ) -> None:
        self.storage, self.connection, self.path = storage, connection, path
        self.check, self.growth_factor = check, growth_factor
        self._limit = min(65536, max(1, storage.limits.working_memory_bytes // 16))
        self._grant: ContextManager[None] | None = None
        self._operations = self._payload = 0
        self._max_operations = self._payload_limit = 0
        self._started = 0.0

    def checkpoint_if_due(self) -> None:
        if self._grant is not None and time.monotonic() - self._started >= 0.05:
            self.checkpoint()

    def _open(self, payload: int) -> None:
        pages = self.connection.execute("PRAGMA page_count").fetchone()[0]
        operations = 1 if payload > self._limit else 64
        while True:
            payload_limit = (
                payload if operations == 1 else max(payload, self._limit * operations // 64)
            )
            allowance = (
                self.growth_factor * operations * (max(1, pages).bit_length() + 2)
                + math.ceil(payload_limit * 4 / 4096)
            ) * 4096
            grant = self.storage.sqlite_growth(self.path, allowance)
            try:
                grant.__enter__()
            except ToolError as error:
                if error.code != "resource_limit":
                    raise
                if operations == 1:
                    raise SqliteGrantRefused(str(error)) from error
                operations //= 2
                continue
            self._grant = grant
            self._max_operations, self._payload_limit = operations, max(1, payload_limit)
            self._operations = self._payload = 0
            self._started = time.monotonic()
            self.connection.execute(f"PRAGMA max_page_count={pages + allowance // 4096}")
            return

    def write(self, operation: Callable[[], object], payload: int = 0) -> None:
        if payload < 0:
            raise ValueError("SQLite payload must be nonnegative")
        self.check()
        self.checkpoint_if_due()
        if self._grant is not None and (
            self._operations >= self._max_operations
            or self._payload + payload > self._payload_limit
        ):
            self.checkpoint()
        if self._grant is None:
            self._open(payload)
        operation()
        self._operations += 1
        self._payload += payload
        if self._operations >= self._max_operations or self._payload >= self._payload_limit:
            self.checkpoint()

    def checkpoint(self, *, commit: bool = True) -> None:
        if self._grant is None:
            return
        grant, self._grant = self._grant, None
        try:
            if commit:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            grant.__exit__(None, None, None)

    def close(self) -> None:
        self.checkpoint()

    def abort(self) -> None:
        # The stage remains unpublished and is removed after engine close.
        self.checkpoint(commit=False)


def resident_size(value: object) -> int:
    """Conservative decoded-object size, counting repeated references separately."""
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(resident_size(k) + resident_size(v) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(resident_size(item) for item in value)
    return size
