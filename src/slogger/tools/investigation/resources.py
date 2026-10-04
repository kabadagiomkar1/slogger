"""Admission and allocation accounting shared by capture and later disk jobs."""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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

    def __init__(self, parent: Path | None, limits: ResourceLimits) -> None:
        if not hasattr(os, "statvfs"):
            raise ToolError(
                "platform_unsupported",
                "Investigation storage requires POSIX allocation accounting.",
            )
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="slogger-investigation-", dir=parent))
        self.limits = limits
        self._reserved = 0
        self._closed = False
        try:
            self._block = os.statvfs(self.root).f_frsize or 4096
            self._check()
        except (OSError, ToolError):
            self.close()
            raise

    @property
    def usage(self) -> ResourceUsage:
        allocated = 0
        if not self._closed:
            for path in (self.root, *self.root.iterdir()):
                info = path.stat()
                allocated += max(info.st_size, getattr(info, "st_blocks", 0) * 512)
        return ResourceUsage(allocated, self._reserved)

    def _check(self) -> None:
        if self.usage.managed_disk_bytes > self.limits.disk_bytes:
            raise ToolError("resource_limit", "Managed disk budget exhausted; increase disk_bytes.")

    def create_file(self, name: str) -> Path:
        if self._closed:
            raise ToolError("session_closed", "Managed storage is closed.")
        if Path(name).name != name:
            raise ValueError("managed files require a single filename")
        path = self.root / name
        path.touch(exist_ok=False)
        try:
            self._check()
        except ToolError:
            path.unlink()
            raise
        return path

    @contextmanager
    def reserve(self, byte_count: int) -> Iterator[None]:
        """Reserve disk growth before a job creates or allocates its output."""
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

    def append(self, path: Path, data: bytes) -> None:
        if self._closed or path.parent != self.root:
            raise ToolError("session_closed", "Cannot write outside active managed storage.")
        previous = path.stat()
        allocated = max(previous.st_size, getattr(previous, "st_blocks", 0) * 512)
        predicted = math.ceil((previous.st_size + len(data)) / self._block) * self._block
        with self.reserve(max(0, predicted - allocated)):
            with path.open("ab") as handle:
                handle.write(data)
        try:
            self._check()
        except ToolError:
            self.truncate(path, previous.st_size)
            raise

    def truncate(self, path: Path, byte_count: int) -> None:
        if path.parent != self.root:
            raise ValueError("not a managed file")
        with path.open("r+b") as handle:
            handle.truncate(byte_count)

    def close(self) -> None:
        if not self._closed:
            shutil.rmtree(self.root)
            self._closed = True


def resident_size(value: object) -> int:
    """Conservative decoded-object size, counting repeated references separately."""
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(resident_size(k) + resident_size(v) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(resident_size(item) for item in value)
    return size
