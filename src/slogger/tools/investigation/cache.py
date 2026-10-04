"""Explicit POSIX durable cache ownership, leases, and global allocation admission."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO

from ..errors import ToolError
from .resources import ResourceLimits, ResourceUsage

CACHE_VERSION = 1
DEFAULT_EXPIRY_SECONDS = 7 * 24 * 60 * 60


def _flock(handle: BinaryIO, *, exclusive: bool = False, nonblocking: bool = False) -> None:
    # Keep base/Python tooling importable on platforms without POSIX locking.
    try:
        import fcntl
    except ImportError as error:
        raise ToolError(
            "platform_unsupported", "Durable cache requires POSIX file leases."
        ) from error
    flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if nonblocking:
        flags |= fcntl.LOCK_NB
    fcntl.flock(handle, flags)


def default_cache_dir() -> Path:
    """Select a durable location without touching the filesystem."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "slogger" / "investigation-v1"
    return (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "slogger"
        / "investigation-v1"
    )


def allocation(path: Path) -> int:
    info = path.stat()
    return max(info.st_size, getattr(info, "st_blocks", 0) * 512)


def directory_allocation(root: Path) -> int:
    total = allocation(root)
    for path in root.iterdir():
        try:
            total += allocation(path)
        except FileNotFoundError:
            # External database sidecars may disappear between list and stat.
            continue
    return total


@dataclass(frozen=True)
class CacheClearResult:
    removed_entries: int
    protected_entries: int
    reclaimed_bytes: int
    usage: ResourceUsage


class CacheLease:
    def __init__(self, owner: CacheStore, root: Path, handle: BinaryIO) -> None:
        self.owner = owner
        self.root = root
        self.handle = handle
        self.closed = False
        self.manifest_digest: str | None = None

    def close(self) -> None:
        if not self.closed:
            try:
                self.owner.touch(self.root)
            finally:
                self.handle.close()
                self.closed = True


class CacheStore:
    """One explicit cache; global catalog lock and kernel-released entry leases.

    Each writable workspace has one owner. Reused capture files are immutable;
    every new session receives a separate workspace for its operation results.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        limits: ResourceLimits | None = None,
        expiry_seconds: float = DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        if expiry_seconds < 0:
            raise ValueError("cache expiry must be nonnegative")
        self.root = Path(root).absolute()
        self.limits = limits or ResourceLimits()
        self.expiry_seconds = expiry_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self.entries = self.root / "entries"
        self.entries.mkdir(exist_ok=True)
        self._catalog = self.root / "catalog.sqlite"
        with self._guard() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, key TEXT, "
                "state TEXT, bytes INTEGER, reserved INTEGER, touched REAL, manifest TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS cache_key ON entries(key, state, touched)")
        self.clear(expired_only=True)
        self._check_usage(self.usage)

    @contextmanager
    def _guard(self) -> Iterator[sqlite3.Connection]:
        with (self.root / ".catalog.lock").open("a+b") as lock:
            _flock(lock, exclusive=True)
            db = sqlite3.connect(self._catalog, isolation_level=None)
            try:
                db.execute("PRAGMA mmap_size=0")
                db.execute("PRAGMA cache_size=-256")
                yield db
            except sqlite3.Error as error:
                code = (
                    "storage_failed"
                    if isinstance(error, sqlite3.OperationalError)
                    else "cache_corrupt"
                )
                raise ToolError(
                    code,
                    "Durable cache catalog failed; use another cache_dir or temporary "
                    f"storage (--no-cache): {error}",
                ) from error
            finally:
                db.close()

    def _usage(self, db: sqlite3.Connection) -> ResourceUsage:
        row = db.execute(
            "SELECT COALESCE(SUM(bytes),0), COALESCE(SUM(reserved),0) FROM entries"
        ).fetchone()
        overhead = allocation(self.root) + allocation(self.entries)
        overhead += sum(allocation(path) for path in self.root.iterdir() if path.is_file())
        # SQLite rollback journals can cover the old catalog plus record/header
        # overhead. Keep twice that allocation and 64 KiB of catalog/directory
        # growth headroom admitted across every transaction, including recovery.
        catalog_reserve = 2 * allocation(self._catalog) + 64 * 1024
        return ResourceUsage(row[0] + overhead, row[1], catalog_reserve_bytes=catalog_reserve)

    def _check_usage(self, usage: ResourceUsage) -> None:
        if usage.managed_disk_bytes > self.limits.disk_bytes:
            raise ToolError(
                "resource_limit",
                "Global managed cache disk budget exhausted; "
                "clear unused entries or increase disk_bytes.",
            )

    @property
    def usage(self) -> ResourceUsage:
        with self._guard() as db:
            disk_adjustment = reservation_adjustment = 0
            for name, recorded, reserved in db.execute("SELECT id,bytes,reserved FROM entries"):
                root = self.entries / name
                if not root.is_dir():
                    continue
                actual = directory_allocation(root)
                with (root / ".lease").open("a+b") as lease:
                    try:
                        _flock(lease, exclusive=True, nonblocking=True)
                    except BlockingIOError:
                        # Keep an active owner's admission ceiling unchanged in
                        # the catalog. Report observed growth as consuming that
                        # ceiling, instead of charging actual + original reserve.
                        disk_adjustment += actual - recorded
                        reservation_adjustment += max(0, recorded + reserved - actual) - reserved
                    else:
                        db.execute(
                            "UPDATE entries SET bytes=?,reserved=0 WHERE id=?", (actual, name)
                        )
            usage = self._usage(db)
            return replace(
                usage,
                disk_bytes=usage.disk_bytes + disk_adjustment,
                reserved_disk_bytes=usage.reserved_disk_bytes + reservation_adjustment,
            )

    def new_workspace(self) -> CacheLease:
        with self._guard() as db:
            root = self.entries / uuid.uuid4().hex
            root.mkdir()
            handle = (root / ".lease").open("a+b")
            _flock(handle)
            db.execute(
                "INSERT INTO entries VALUES (?,NULL,'staging',?,0,?,NULL)",
                (root.name, directory_allocation(root), time.time()),
            )
            try:
                self._check_usage(self._usage(db))
            except BaseException:
                handle.close()
                shutil.rmtree(root)
                db.execute("DELETE FROM entries WHERE id=?", (root.name,))
                raise
            return CacheLease(self, root, handle)

    def update(self, root: Path, byte_count: int, reserved: int) -> None:
        with self._guard() as db:
            old = db.execute(
                "SELECT bytes,reserved FROM entries WHERE id=?", (root.name,)
            ).fetchone()
            if old is None:
                raise ToolError("storage_failed", "Managed cache ownership disappeared.")
            db.execute(
                "UPDATE entries SET bytes=?,reserved=? WHERE id=?",
                (byte_count, reserved, root.name),
            )
            try:
                # Releases must succeed after another opener raises its budget.
                if byte_count + reserved > old[0] + old[1]:
                    self._check_usage(self._usage(db))
            except BaseException:
                db.execute("UPDATE entries SET bytes=?,reserved=? WHERE id=?", (*old, root.name))
                raise

    def touch(self, root: Path) -> None:
        with self._guard() as db:
            db.execute("UPDATE entries SET touched=? WHERE id=?", (time.time(), root.name))

    @staticmethod
    def key(paths: list[str]) -> str:
        return hashlib.sha256(json.dumps(paths, ensure_ascii=False).encode()).hexdigest()

    def candidate(self, paths: list[str]) -> CacheLease | None:
        with self._guard() as db:
            for name, digest in db.execute(
                "SELECT id,manifest FROM entries WHERE key=? AND state='complete' "
                "ORDER BY touched DESC",
                (self.key(paths),),
            ):
                root = self.entries / name
                if not root.is_dir():
                    continue
                handle = (root / ".lease").open("a+b")
                _flock(handle)
                lease = CacheLease(self, root, handle)
                lease.manifest_digest = digest
                return lease
        return None

    def publish(self, root: Path, paths: list[str]) -> None:
        with self._guard() as db:
            db.execute(
                "UPDATE entries SET key=?,state='complete',bytes=?,reserved=0,touched=?,"
                "manifest=? WHERE id=?",
                (
                    self.key(paths),
                    directory_allocation(root),
                    time.time(),
                    hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                    root.name,
                ),
            )
            self._check_usage(self._usage(db))

    def forget(self, lease: CacheLease) -> None:
        with self._guard() as db:
            lease.handle.close()
            lease.closed = True
            shutil.rmtree(lease.root)
            db.execute("DELETE FROM entries WHERE id=?", (lease.root.name,))

    def clear(self, *, expired_only: bool = False) -> CacheClearResult:
        """Remove only unlocked owned entries; abandoned staging ignores expiry."""
        removed = protected = reclaimed = 0
        with self._guard() as db:
            # Recover directories allocated before a crashed owner registered them.
            for root in self.entries.iterdir():
                if (
                    root.is_symlink()
                    or not root.is_dir()
                    or len(root.name) != 32
                    or any(char not in "0123456789abcdef" for char in root.name)
                ):
                    continue
                if db.execute("SELECT 1 FROM entries WHERE id=?", (root.name,)).fetchone() is None:
                    db.execute(
                        "INSERT INTO entries VALUES (?,NULL,'staging',?,0,0,NULL)",
                        (root.name, directory_allocation(root)),
                    )
            # Cursor iteration stays bounded even for a large cache catalog.
            for name, state, touched, _byte_count in db.execute(
                "SELECT id,state,touched,bytes FROM entries"
            ):
                root = self.entries / name
                if not root.is_dir():
                    db.execute("DELETE FROM entries WHERE id=?", (name,))
                    continue
                with (root / ".lease").open("a+b") as handle:
                    try:
                        _flock(handle, exclusive=True, nonblocking=True)
                    except BlockingIOError:
                        protected += 1
                        continue
                    if (
                        expired_only
                        and state == "complete"
                        and time.time() - touched < self.expiry_seconds
                    ):
                        # A dead owner may have left jobs/reservations beside a
                        # completed capture. Only its fixed capture inventory stays.
                        manifest = root / "manifest.json"
                        expected = db.execute(
                            "SELECT manifest FROM entries WHERE id=?", (name,)
                        ).fetchone()[0]
                        if (
                            manifest.is_file()
                            and not manifest.is_symlink()
                            and manifest.stat().st_size <= 1024 * 1024
                            and hashlib.sha256(manifest.read_bytes()).hexdigest() == expected
                        ):
                            before = directory_allocation(root)
                            retained = {
                                ".lease",
                                "manifest.json",
                                "records.jsonl",
                                "records.index",
                                "diagnostics.jsonl",
                                "diagnostics.index",
                            }
                            for path in root.iterdir():
                                if path.name not in retained and path.is_file():
                                    path.unlink()
                            after = directory_allocation(root)
                            reclaimed += before - after
                            db.execute(
                                "UPDATE entries SET bytes=?,reserved=0 WHERE id=?", (after, name)
                            )
                        continue
                    reclaimed += directory_allocation(root)
                    shutil.rmtree(root)
                    db.execute("DELETE FROM entries WHERE id=?", (name,))
                    removed += 1
            usage = self._usage(db)
        return CacheClearResult(removed, protected, reclaimed, usage)
