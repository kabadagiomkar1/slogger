"""Stable finite-file capture and genuinely paged record access."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import sys
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol
from weakref import WeakSet

from ..core.ixr import Expression
from ..core.runtime import SourceOrigin
from ..errors import ToolError
from ..sources import decode_line
from .cache import CACHE_VERSION, DEFAULT_EXPIRY_SECONDS, CacheLease, CacheStore
from .capture import bounded_lines
from .diagnostics import DiagnosticLog
from .filters import FilterJob, RecordView
from .models import CaptureStatus, Diagnostic, RecordIdentity, RecordPage, SourceBoundary
from .resources import ManagedStorage, ResourceLimits, ResourceUsage, resident_size

if TYPE_CHECKING:
    from .aggregates import AggregateJob
    from .search import SearchJob, SearchOptions
    from .tree import TreeJob


class InvestigationOperation(Protocol):
    def cancel(self) -> None: ...
    def wait(self, timeout: float | None = None) -> object: ...


class InvestigationView(Protocol):
    def close(self) -> None: ...


_INDEX = struct.Struct("<QQQQ")


class Investigation:
    """One stable disk dataset. Open explicitly; close releases owned storage."""

    def __init__(self, storage: ManagedStorage) -> None:
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._boundaries_ready = threading.Event()
        self._done = threading.Event()
        self._worker: threading.Thread | None = None
        self.cache_store: CacheStore | None = None
        self._cache_lease: CacheLease | None = None
        self._admission = {"raw": 0, "working": 0, "page": 0}
        self.storage = storage
        self.limits = storage.limits
        self.dataset_id = uuid.uuid4().hex
        self.sources: tuple[SourceBoundary, ...] = ()
        self.status = CaptureStatus("capturing")
        self.diagnostics = DiagnosticLog(storage)
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._cache_bytes = 0
        self._lifecycle_lock = threading.RLock()
        self._closing = False
        self._operations: WeakSet[InvestigationOperation] = WeakSet()
        self._views: WeakSet[InvestigationView] = WeakSet()
        self._data = storage.create_file("records.jsonl")
        self._index = storage.create_file("records.index")

    @classmethod
    def open(
        cls,
        paths: Sequence[str | os.PathLike[str]],
        *,
        storage_dir: str | os.PathLike[str] | None = None,
        limits: ResourceLimits | None = None,
        background: bool = False,
        cache_dir: str | os.PathLike[str] | None = None,
        cache_expiry_seconds: float = DEFAULT_EXPIRY_SECONDS,
    ) -> Investigation:
        """Capture regular files in supplied order, including repeated occurrences.

        Errors produce a failed, non-ready session with diagnostic context. Invalid
        resource configuration raises ValueError; storage setup failures raise ToolError.
        """
        try:
            configured = limits or ResourceLimits()
            cache = (
                CacheStore(cache_dir, limits=configured, expiry_seconds=cache_expiry_seconds)
                if cache_dir is not None
                else None
            )
            storage = ManagedStorage(
                Path(storage_dir) if storage_dir is not None else None,
                configured,
                lease=cache.new_workspace() if cache is not None else None,
            )
        except OSError as error:
            raise ToolError(
                "storage_failed", f"Cannot create investigation storage: {error}"
            ) from error
        try:
            session = cls(storage)
            session.cache_store = cache
            if cache is not None:
                session.status = replace(session.status, cache_state="miss")
        except Exception:
            storage.close()
            raise
        try:
            if background:
                session._worker = threading.Thread(
                    target=session._run_capture,
                    args=(tuple(paths),),
                    name=f"slogger-capture-{session.dataset_id}",
                    daemon=True,
                )
                session._worker.start()
                session._boundaries_ready.wait()
            else:
                session._run_capture(tuple(paths))
        except BaseException:
            storage.close()
            raise
        return session

    def _run_capture(self, paths: Sequence[str | os.PathLike[str]]) -> None:
        try:
            self._capture(paths)
        finally:
            self._boundaries_ready.set()
            self._done.set()

    def cancel(self) -> None:
        """Request cancellation; wait() observes settled retained-prefix state."""
        with self._lock:
            if self.status.phase in ("capturing", "verifying", "verifying_cache"):
                self._cancel.set()

    def _check_canceled(self) -> None:
        if self._cancel.is_set():
            raise ToolError(
                "capture_canceled", "Opening canceled; captured prefix remains incomplete."
            )

    def wait(self, timeout: float | None = None) -> CaptureStatus:
        """Wait for capture to settle; timeout returns its current status."""
        self._done.wait(timeout)
        return self.status

    @property
    def resources(self) -> ResourceUsage:
        with self._lock:
            usage = self.cache_store.usage if self.cache_store is not None else self.storage.usage
            return replace(usage, ram_cache_bytes=self._cache_bytes)

    def _capture(self, paths: Sequence[str | os.PathLike[str]]) -> None:
        active_origin = None
        active_source = None
        occurrence = None
        try:
            with ExitStack() as stack:
                inputs = []
                boundaries = []
                for occurrence, path in enumerate(paths):
                    self._check_canceled()
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
                self._boundaries_ready.set()
                if self._try_reuse(boundaries, inputs):
                    return
                digests = []
                with self.storage.writer(
                    self._data, self._index, self.diagnostics._data, self.diagnostics._index
                ) as writer:
                    pending_records = pending_bytes = pending_skips = pending_diagnostics = 0
                    pending_lines = 0
                    last_publication = time.monotonic()
                    buffer_limit = min(64 * 1024, max(1, self.limits.working_memory_bytes // 8))

                    def publish() -> None:
                        nonlocal pending_records, pending_bytes, pending_skips
                        nonlocal pending_diagnostics, pending_lines, last_publication
                        with self._lock:
                            try:
                                writer.flush()
                            except BaseException:
                                pending_records = pending_bytes = 0
                                pending_skips = pending_diagnostics = 0
                                pending_lines = 0
                                raise
                            self.diagnostics.publish(pending_diagnostics)
                            self.status = replace(
                                self.status,
                                record_count=self.status.record_count + pending_records,
                                captured_bytes=self.status.captured_bytes + pending_bytes,
                                skipped_lines=self.status.skipped_lines + pending_skips,
                            )
                        pending_records = pending_bytes = pending_skips = pending_diagnostics = 0
                        pending_lines = 0
                        last_publication = time.monotonic()

                    try:
                        for boundary, handle in zip(boundaries, inputs, strict=True):
                            occurrence = boundary.input_occurrence
                            active_source = boundary.source
                            active_origin = None
                            digest = hashlib.sha256()
                            for line, raw in enumerate(
                                bounded_lines(
                                    handle, boundary.byte_length, self.limits.max_record_bytes
                                ),
                                1,
                            ):
                                self._check_canceled()
                                origin = SourceOrigin(boundary.source, line, "file")
                                active_origin = origin
                                digest.update(raw)
                                self._admission["raw"] = max(self._admission["raw"], len(raw))
                                record, reason = decode_line(raw.decode("utf-8"))
                                if writer.pending_bytes + len(raw) + 256 > buffer_limit:
                                    publish()
                                pretty = ""
                                if record is not None:
                                    size = resident_size(record)
                                    pretty = json.dumps(record, indent=2, ensure_ascii=False)
                                    pretty_size = sys.getsizeof(pretty) + resident_size(
                                        pretty.splitlines()
                                    )
                                    self._admission["working"] = max(
                                        self._admission["working"],
                                        size + pretty_size + 5 * len(raw) + _INDEX.size,
                                    )
                                    self._admission["page"] = max(
                                        self._admission["page"], size + 128
                                    )
                                    if (
                                        size + pretty_size + 4 * len(raw) + writer.pending_bytes
                                        > self.limits.working_memory_bytes
                                        or size + 128 > self.limits.page_memory_bytes
                                    ):
                                        raise ToolError(
                                            "record_too_large",
                                            f"Decoded record exceeds memory admission: "
                                            f"{boundary.source}:{line}",
                                        )
                                # On admission failure, first publish previously admitted rows.
                                # Retry this row against reconciled allocation; never omit it.
                                for attempt in range(2):
                                    try:
                                        if reason is not None:
                                            self.diagnostics.stage(
                                                Diagnostic(
                                                    reason,
                                                    f"Skipped {reason} line.",
                                                    origin,
                                                    occurrence,
                                                ),
                                                writer,
                                            )
                                        elif record is not None:
                                            writer.stage(
                                                {
                                                    self._data: raw,
                                                    self._index: _INDEX.pack(
                                                        writer.offset(self._data),
                                                        len(raw),
                                                        occurrence,
                                                        line,
                                                    ),
                                                }
                                            )
                                        break
                                    except ToolError:
                                        if attempt or not pending_lines:
                                            raise
                                        publish()
                                # Do not retain decoded/pretty objects across the next parse.
                                is_record = record is not None
                                del pretty, record
                                pending_bytes += len(raw)
                                pending_lines += 1
                                pending_records += is_record
                                pending_skips += reason is not None
                                pending_diagnostics += reason is not None
                                if (
                                    self.status.record_count == 0
                                    and pending_records
                                    or writer.pending_bytes >= buffer_limit
                                    or pending_lines >= 256
                                    or time.monotonic() - last_publication >= 0.05
                                ):
                                    publish()
                            digests.append(digest.digest())
                            publish()
                    except BaseException:
                        if pending_lines:
                            publish()
                        raise
                self.status = replace(self.status, phase="verifying")
                for boundary, handle, captured_digest in zip(
                    boundaries, inputs, digests, strict=True
                ):
                    occurrence = boundary.input_occurrence
                    active_source = boundary.source
                    active_origin = None
                    self._check_canceled()
                    info = os.stat(boundary.source)
                    if (info.st_dev, info.st_ino) != (boundary.device, boundary.inode):
                        raise ToolError("source_changed", f"Source replaced: {boundary.source}")
                    handle.seek(0)
                    verified = hashlib.sha256()
                    remaining = boundary.byte_length
                    while remaining:
                        self._check_canceled()
                        chunk = handle.read(min(remaining, 64 * 1024))
                        if not chunk:
                            raise ToolError(
                                "source_changed", f"Source truncated: {boundary.source}"
                            )
                        verified.update(chunk)
                        remaining -= len(chunk)
                        self.status = replace(
                            self.status, verified_bytes=self.status.verified_bytes + len(chunk)
                        )
                    info = os.stat(boundary.source)
                    if (info.st_dev, info.st_ino) != (
                        boundary.device,
                        boundary.inode,
                    ) or verified.digest() != captured_digest:
                        raise ToolError("source_changed", f"Source mutated: {boundary.source}")
                self._persist(digests)
                with self._lock:
                    self._check_canceled()
                    if self.cache_store is not None:
                        self.cache_store.publish(
                            self.storage.root, [source.source for source in self.sources]
                        )
                        self.storage.retain()
                        self.status = replace(self.status, cache_state="stored")
                    self.status = replace(self.status, phase="complete")
        except Exception as error:
            code = error.code if isinstance(error, ToolError) else "capture_failed"
            if (
                active_source is not None
                and isinstance(error, ToolError)
                and isinstance(error.extra.get("position"), int)
            ):
                active_origin = SourceOrigin(active_source, error.extra["position"], "file")
            self.diagnostics.terminal = Diagnostic(code, str(error), active_origin, occurrence)
            self.status = replace(
                self.status, phase="canceled" if code == "capture_canceled" else "failed"
            )

    def _hash_file(self, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(
                min(64 * 1024, max(1, self.limits.working_memory_bytes // 8))
            ):
                self._check_canceled()
                digest.update(chunk)
                size += len(chunk)
                if self.status.phase == "verifying_cache":
                    self.status = replace(
                        self.status,
                        cache_verified_bytes=self.status.cache_verified_bytes + len(chunk),
                    )
        return {"bytes": size, "sha256": digest.hexdigest()}

    def _persist(self, digests: list[bytes]) -> None:
        if self.cache_store is None:
            return
        files = (self._data, self._index, self.diagnostics._data, self.diagnostics._index)
        manifest = {
            "version": CACHE_VERSION,
            "dataset_id": self.dataset_id,
            "sources": [asdict(source) for source in self.sources],
            "source_hashes": [digest.hex() for digest in digests],
            "status": asdict(self.status),
            "diagnostics": len(self.diagnostics),
            "admission": self._admission,
            "files": {path.name: self._hash_file(path) for path in files},
        }
        raw = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        if len(raw) > min(1024 * 1024, self.limits.working_memory_bytes // 4):
            raise ToolError("resource_limit", "Capture manifest exceeds working memory admission.")
        path = self.storage.create_file("manifest.json")
        self.storage.append(path, raw)

    def _try_reuse(self, boundaries: list[SourceBoundary], inputs: Sequence[BinaryIO]) -> bool:
        if self.cache_store is None:
            return False
        lease = self.cache_store.candidate([source.source for source in boundaries])
        if lease is None:
            return False
        try:
            self.status = replace(self.status, phase="verifying_cache", cache_state="verifying")
            path = lease.root / "manifest.json"
            if path.stat().st_size > min(1024 * 1024, self.limits.working_memory_bytes // 4):
                raise ValueError("manifest exceeds current working admission")
            raw_manifest = path.read_bytes()
            if hashlib.sha256(raw_manifest).hexdigest() != lease.manifest_digest:
                raise ValueError("corrupt capture manifest")
            manifest = json.loads(raw_manifest)
            if manifest["version"] != CACHE_VERSION:
                raise ValueError("incompatible capture version")
            if manifest["sources"] != [asdict(source) for source in boundaries]:
                raise ValueError("current source identity or opening extent changed")
            files = manifest["files"]
            if set(files) != {
                "records.jsonl",
                "records.index",
                "diagnostics.jsonl",
                "diagnostics.index",
            }:
                raise ValueError("invalid captured file inventory")
            self.status = replace(
                self.status, cache_total_bytes=sum(value["bytes"] for value in files.values())
            )
            for name, expected in files.items():
                if self._hash_file(lease.root / name) != expected:
                    raise ValueError(f"corrupt capture file: {name}")
            if len(manifest["source_hashes"]) != len(boundaries):
                raise ValueError("invalid source hash inventory")
            for boundary, handle, expected in zip(
                boundaries, inputs, manifest["source_hashes"], strict=True
            ):
                digest = hashlib.sha256()
                remaining = boundary.byte_length
                while remaining:
                    self._check_canceled()
                    chunk = handle.read(
                        min(remaining, 64 * 1024, max(1, self.limits.working_memory_bytes // 8))
                    )
                    if not chunk:
                        raise ValueError("source truncated during verification")
                    digest.update(chunk)
                    remaining -= len(chunk)
                    self.status = replace(
                        self.status, verified_bytes=self.status.verified_bytes + len(chunk)
                    )
                info = os.stat(boundary.source)
                if (info.st_dev, info.st_ino) != (
                    boundary.device,
                    boundary.inode,
                ) or digest.hexdigest() != expected:
                    raise ValueError("source content changed")
            admission = manifest["admission"]
            if (
                admission["raw"] > self.limits.max_record_bytes
                or admission["working"] > self.limits.working_memory_bytes
                or admission["page"] > self.limits.page_memory_bytes
            ):
                raise ToolError(
                    "record_too_large",
                    "Cached records exceed current record/working/page memory admission.",
                )
            saved = manifest["status"]
            if (
                files["records.index"]["bytes"] != saved["record_count"] * _INDEX.size
                or files["diagnostics.index"]["bytes"] != manifest["diagnostics"] * 16
            ):
                raise ValueError("invalid capture counts")
            with self._lock:
                self._check_canceled()
                for old in (
                    self._data,
                    self._index,
                    self.diagnostics._data,
                    self.diagnostics._index,
                ):
                    self.storage.remove_file(old)
                self.dataset_id = manifest["dataset_id"]
                self._data = lease.root / "records.jsonl"
                self._index = lease.root / "records.index"
                self.diagnostics._data = lease.root / "diagnostics.jsonl"
                self.diagnostics._index = lease.root / "diagnostics.index"
                self.diagnostics._count = manifest["diagnostics"]
                self._cache_lease = lease
                self._admission = admission
                self.status = replace(
                    self.status,
                    phase="complete",
                    cache_state="reused",
                    record_count=saved["record_count"],
                    captured_bytes=saved["captured_bytes"],
                    skipped_lines=saved["skipped_lines"],
                )
            return True
        except ToolError:
            lease.close()
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            lease.close()
            self.status = replace(
                self.status,
                phase="capturing",
                cache_state="rejected",
                cache_reason=str(error),
                verified_bytes=0,
                cache_verified_bytes=0,
                cache_total_bytes=0,
            )
            for handle in inputs:
                handle.seek(0)
            return False

    def require_ready(self, operation: str) -> None:
        """Shared gate used before every complete-dataset operation."""
        if self._closing:
            raise ToolError("session_closed", "Investigation is closing or closed.")
        if not self.status.complete:
            raise ToolError(
                "dataset_incomplete",
                f"{operation} requires a complete dataset.",
                dataset_id=self.dataset_id,
                phase=self.status.phase,
            )

    def page(self, offset: int = 0, limit: int = 100) -> RecordPage:
        with self._lock:
            return self._page(offset, limit)

    def _page(self, offset: int, limit: int) -> RecordPage:
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

    def filter(
        self,
        expression: Expression,
        *,
        input_view: RecordView | None = None,
        request_generation: int = 0,
    ) -> FilterJob:
        """Start complete reference filtering over the dataset or an explicit view."""
        with self._lifecycle_lock:
            self.require_ready("filter")
            job = FilterJob(self, expression, input_view, request_generation)
            self.register_operation(job)
            return job

    def search(
        self,
        options: SearchOptions,
        *,
        input_view: RecordView | None = None,
        request_generation: int = 0,
    ) -> SearchJob:
        """Search complete decoded records in an explicit dataset/view scope."""
        from .search import SearchJob

        with self._lifecycle_lock:
            self.require_ready("search")
            job = SearchJob(self, options, input_view, request_generation)
            self.register_operation(job)
            return job

    def count_values(
        self,
        path: tuple[str, ...],
        *,
        input_view: RecordView | None = None,
        request_generation: int = 0,
    ) -> AggregateJob:
        """Count complete scalar values where the selected exact field path exists."""
        from .aggregates import AggregateJob

        with self._lifecycle_lock:
            self.require_ready("value counts")
            job = AggregateJob(self, path, input_view, request_generation)
            self.register_operation(job)
            return job

    def register_operation(self, operation: InvestigationOperation) -> None:
        """Retain active lifecycle ownership without accumulating completed jobs."""
        with self._lifecycle_lock:
            if self._closing:
                raise ToolError("session_closed", "Investigation is closing or closed.")
            self._operations.add(operation)

    def register_view(self, view: InvestigationView) -> None:
        """Close successful handles before releasing this session's storage."""
        with self._lifecycle_lock:
            if self._closing:
                raise ToolError("session_closed", "Investigation is closing or closed.")
            self._views.add(view)

    def diagnostic_page(self, offset: int = 0, limit: int = 100) -> list[Diagnostic]:
        with self._lock:
            return self._diagnostic_page(offset, limit)

    def _diagnostic_page(self, offset: int, limit: int) -> list[Diagnostic]:
        if self.status.phase == "closed":
            raise ToolError("session_closed", "Investigation is closed.")
        if offset < 0 or limit < 0 or limit > self.limits.max_page_records:
            raise ValueError("diagnostic offset/limit exceed the page contract")
        return self.diagnostics[offset : offset + limit]

    def build_tree(self, *, background: bool = True) -> TreeJob:
        """Reconstruct complete unfiltered trace evidence outside rendering."""
        from .tree import TreeJob

        with self._lifecycle_lock:
            self.require_ready("trace reconstruction")
            job = TreeJob(self, background)
            self.register_operation(job)
            return job

    def close(self) -> None:
        with self._lifecycle_lock:
            if self.status.phase == "closed":
                return
            self._closing = True
            operations = tuple(self._operations)
        self.cancel()
        if self._worker is not None:
            self._worker.join()
        for operation in operations:
            operation.cancel()
        for operation in operations:
            operation.wait()
        for view in tuple(self._views):
            view.close()
        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0
            self.storage.close()
            if self._cache_lease is not None:
                self._cache_lease.close()
            self.status = replace(self.status, phase="closed")

    def __enter__(self) -> Investigation:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
