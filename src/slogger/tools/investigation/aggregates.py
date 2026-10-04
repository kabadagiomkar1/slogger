"""Exact selected-field counts and original-sequence numeric replay."""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from ..backends.python.aggregation import _key, checked_numeric_metric, scalar_group_identity
from ..core.bindings import FieldBinding
from ..core.builders import Field
from ..core.fields import _MISSING
from ..core.filter_language import format_field_path
from ..core.ixr import Expression
from ..errors import ToolError
from .filters import OperationStatus, RecordView, ViewScope
from .models import Diagnostic
from .resources import resident_size

if TYPE_CHECKING:
    from .session import Investigation

_MEMBER = struct.Struct("<Q")


@dataclass(frozen=True)
class AggregateScope:
    input_scope: ViewScope
    selected_field: FieldBinding
    presence: Expression
    request_generation: int = 0
    metrics: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AggregatePage:
    scope: AggregateScope
    offset: int
    records: list[dict[str, Any]]
    origins: list[None]
    next_offset: int
    has_more: bool


class AggregateResult:
    """Immutable complete derived rows; input/selected-field scope stays attached."""

    def __init__(self, session: Investigation, path: Path, count: int, scope: AggregateScope):
        self.session = session
        self.scope = scope
        self.record_count = count
        self._path = path
        self._closed = False
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA query_only=ON")
        self._db.execute("PRAGMA mmap_size=0")
        self._db.execute(
            f"PRAGMA cache_size=-{max(1, session.limits.working_memory_bytes // 8192)}"
        )
        try:
            session.register_view(self)
        except BaseException:
            self._db.close()
            raise

    def page(self, offset: int = 0, limit: int = 100) -> AggregatePage:
        with self._lock:
            if self._closed or self.session.status.phase == "closed":
                raise ToolError("result_closed", "Aggregate result is closed.")
            if offset < 0 or limit < 0 or limit > self.session.limits.max_page_records:
                raise ValueError("aggregate page exceeds the page contract")
            records: list[dict[str, Any]] = []
            size = 0
            # Dense insertion IDs provide first-appearance order without OFFSET scans or sorting.
            cursor = self._db.execute(
                "SELECT payload,count FROM groups WHERE id>=? ORDER BY id LIMIT ?", (offset, limit)
            )
            for payload, count in cursor:
                record = (
                    _decode_numeric_row(payload)
                    if self.scope.metrics is not None
                    else {"value": json.loads(payload), "count": count}
                )
                cost = resident_size(record) + 128
                if size + cost > self.session.limits.page_memory_bytes:
                    if not records:
                        raise ToolError(
                            "resource_limit", "Aggregate row exceeds page memory admission."
                        )
                    break
                records.append(record)
                size += cost
            next_offset = offset + len(records)
            return AggregatePage(
                self.scope,
                offset,
                records,
                [None] * len(records),
                next_offset,
                next_offset < self.record_count,
            )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
                self.session.storage.remove_file(self._path)


class AggregateJob:
    """One owned count/summary request, independent of consumer follow/Main state."""

    def __init__(
        self,
        session: Investigation,
        path: tuple[str, ...],
        input_view: RecordView | None,
        request_generation: int,
        *,
        metrics: tuple[str, ...] | None = None,
    ):
        session.require_ready("field aggregates")
        binding = FieldBinding(path)
        if metrics is not None and (
            not isinstance(metrics, tuple)
            or not metrics
            or any(metric not in ("count", "sum", "mean", "min", "max") for metric in metrics)
            or len(set(metrics)) != len(metrics)
        ):
            raise ValueError("metrics must be a nonempty unique tuple of count/sum/mean/min/max")
        if input_view is not None and input_view.session is not session:
            raise ToolError("scope_mismatch", "Input view belongs to a different investigation.")
        self.session = session
        self.scope = AggregateScope(
            input_view.view_scope
            if input_view
            else ViewScope(session.dataset_id, session.dataset_id),
            binding,
            Field(*binding.path).exists(),
            request_generation,
            metrics,
        )
        self.status = OperationStatus(
            "pending",
            total_records=(input_view.record_count if input_view else session.status.record_count),
        )
        self.diagnostics: tuple[Diagnostic, ...] = ()
        self.result: AggregateResult | None = None
        self._input = input_view
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._lock = threading.RLock()
        if resident_size(binding.path) > session.limits.working_memory_bytes // 4:
            raise ToolError("resource_limit", "Selected field exceeds working memory admission.")
        self._spill_path: Path | None = None
        if input_view:
            input_view._acquire()
        try:
            self._path = session.storage.create_file("aggregate-" + uuid.uuid4().hex + ".sqlite")
            self._spill_path = (
                session.storage.create_file("numeric-" + uuid.uuid4().hex + ".ordinals")
                if metrics is not None
                else None
            )
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        except BaseException:
            if hasattr(self, "_path"):
                session.storage.remove_file(self._path)
            if self._spill_path is not None:
                session.storage.remove_file(self._spill_path)
            if input_view:
                input_view._release()
            raise

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> AggregateResult | None:
        if not self._done.wait(timeout):
            raise TimeoutError("Aggregate is still running.")
        return self.result

    def _check(self) -> None:
        if self._cancel.is_set():
            raise ToolError("operation_cancelled", "Field aggregate canceled.")
        self.session.require_ready("field aggregates")

    def _write(self, db: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        self._check()
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        payload = sum(len(value) for value in parameters if isinstance(value, (bytes, str)))
        # Bound B-tree splits and key/payload overflow before changing the unpublished database.
        allowance = (16 * (max(1, pages).bit_length() + 2) + math.ceil(payload * 4 / 4096)) * 4096
        with self.session.storage.external_growth(self._path, byte_count=allowance):
            db.execute(f"PRAGMA max_page_count={pages + allowance // 4096}")
            with db:
                db.execute(sql, parameters)

    def _run(self) -> None:
        db = None
        members = None
        writer = None
        try:
            self.status = replace(self.status, phase="running")
            db = sqlite3.connect(self._path)
            db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("PRAGMA mmap_size=0")
            db.execute(
                f"PRAGMA cache_size=-{max(1, self.session.limits.working_memory_bytes // 8192)}"
            )
            db.execute("PRAGMA temp_store=MEMORY")
            self._write(
                db,
                "CREATE TABLE groups(id INTEGER PRIMARY KEY, identity BLOB UNIQUE, "
                "payload TEXT, count INTEGER)",
            )
            if self.scope.metrics is not None:
                assert self._spill_path is not None
                writer = self.session.storage.writer(self._spill_path)
            if self._input:
                members = self._input._path.open("rb")
            label = format_field_path(self.scope.selected_field.path)
            groups = 0
            numeric_count = present_count = 0
            has_float = False
            for position in range(self.status.total_records):
                self._check()
                ordinal = _MEMBER.unpack(members.read(_MEMBER.size))[0] if members else position
                record = self.session.page(ordinal, 1).records[0]
                value = self.scope.selected_field.resolve(record)
                # Presence precedes value validation and aggregate working/disk admission.
                if value is not _MISSING and self.scope.metrics is not None:
                    present_count += 1
                    numeric_metric = next((op for op in self.scope.metrics if op != "count"), None)
                    if value is not None and numeric_metric is not None:
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or (isinstance(value, float) and not math.isfinite(value))
                        ):
                            raise ToolError(
                                "data_incompatible",
                                "numeric aggregate requires finite numbers",
                                field=list(self.scope.selected_field.path),
                                aggregate=numeric_metric,
                            )
                        if (
                            resident_size(record) + resident_size(value) * 8 + 4096
                            > self.session.limits.working_memory_bytes * 7 // 8
                        ):
                            raise ToolError(
                                "resource_limit", "Numeric value exceeds working memory admission."
                            )
                        assert writer is not None and self._spill_path is not None
                        writer.stage({self._spill_path: _MEMBER.pack(ordinal)})
                        if writer.pending_bytes >= min(
                            65536, self.session.limits.working_memory_bytes // 16
                        ):
                            writer.flush()
                        numeric_count += 1
                        has_float = has_float or isinstance(value, float)
                elif value is not _MISSING:
                    _key(value, label)
                    # Admit serialization after presence, before constructing spill payloads.
                    if (
                        resident_size(record) + resident_size(value) * 8 + 4096
                        > self.session.limits.working_memory_bytes * 7 // 8
                    ):
                        raise ToolError(
                            "resource_limit",
                            "Selected value exceeds aggregate working memory admission.",
                        )
                    identity = scalar_group_identity(value, label)
                    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if (
                        resident_size(record)
                        + resident_size(identity)
                        + resident_size(payload)
                        + 4096
                        > self.session.limits.working_memory_bytes * 7 // 8
                    ):
                        raise ToolError(
                            "resource_limit",
                            "Selected value exceeds aggregate working memory admission.",
                        )
                    found = db.execute(
                        "SELECT id FROM groups WHERE identity=?", (identity,)
                    ).fetchone()
                    if found is None:
                        self._write(
                            db, "INSERT INTO groups VALUES(?,?,?,1)", (groups, identity, payload)
                        )
                        groups += 1
                    else:
                        self._write(db, "UPDATE groups SET count=count+1 WHERE id=?", (found[0],))
                self.status = replace(
                    self.status, processed_records=position + 1, result_records=groups
                )
            if self.scope.metrics is not None:
                assert writer is not None and self._spill_path is not None
                writer.flush()
                writer.close()
                writer = None
                output = {}
                # Validate the complete input first. Replay each metric in configured
                # order so a later domain error wins over a provisional overflow.
                for metric in self.scope.metrics:
                    self._check()
                    output[metric] = (
                        present_count
                        if metric == "count"
                        else self._reduce_numeric(metric, numeric_count, has_float)
                    )
                if (
                    resident_size(output) * 8 + 4096
                    > self.session.limits.working_memory_bytes * 7 // 8
                ):
                    raise ToolError(
                        "resource_limit", "Numeric output exceeds working memory admission."
                    )
                self._write(
                    db,
                    "INSERT INTO groups VALUES(?,?,?,?)",
                    (0, b"numeric", _encode_numeric_row(output), 0),
                )
                groups = 1
                self.session.storage.remove_file(self._spill_path)
                self._spill_path = None
            if members:
                members.close()
                members = None
            db.close()
            db = None
            # Release borrowed membership before announcing a successful result.
            input_view, self._input = self._input, None
            if input_view is not None:
                input_view._release()
            with self._lock, self.session._lifecycle_lock:
                self._check()
                self.result = AggregateResult(self.session, self._path, groups, self.scope)
                self.status = replace(self.status, phase="complete")
        except Exception as error:
            code = error.code if isinstance(error, ToolError) else "execution_failed"
            if isinstance(error, sqlite3.Error) and (
                getattr(error, "sqlite_errorcode", None) == getattr(sqlite3, "SQLITE_FULL", 13)
                or "database or disk is full" in str(error)
            ):
                code = "resource_limit"
            self.diagnostics = (Diagnostic(code, str(error)),)
            self.status = replace(
                self.status, phase="cancelled" if self._cancel.is_set() else "failed"
            )
        finally:
            # Every release settles independently; an OS cleanup error must not
            # strand the operation in running state or prevent session close.
            closed = True
            for handle in (members, db, writer):
                if handle is not None:
                    try:
                        handle.close()
                    except Exception as error:
                        closed = False
                        self._cleanup_failed(error)
            try:
                if self.result is None and closed:
                    try:
                        self.session.storage.remove_file(self._path)
                    except Exception as error:
                        self._cleanup_failed(error)
                if self._spill_path is not None and closed:
                    try:
                        self.session.storage.remove_file(self._spill_path)
                    except Exception as error:
                        self._cleanup_failed(error)
                if self._input:
                    try:
                        self._input._release()
                    except Exception as error:
                        self._cleanup_failed(error)
                    self._input = None
            finally:
                self._done.set()

    def _reduce_numeric(self, metric: str, count: int, has_float: bool) -> Any:
        assert self._spill_path is not None
        with self._spill_path.open("rb") as contributions:
            return checked_numeric_metric(
                metric, self._numeric_values(contributions), count, has_float
            )

    def _numeric_values(self, contributions: BinaryIO):
        """Replay immutable contribution records; no subtotals or decoded list."""
        while encoded := contributions.read(_MEMBER.size):
            self._check()
            ordinal = _MEMBER.unpack(encoded)[0]
            record = self.session.page(ordinal, 1).records[0]
            yield self.scope.selected_field.resolve(record)

    def _cleanup_failed(self, error: Exception) -> None:
        self.diagnostics = (*self.diagnostics, Diagnostic("cleanup_failed", str(error)))
        self.status = replace(self.status, phase="failed")


def _encode_numeric_row(record: dict[str, Any]) -> str:
    # Internal tagged scalars bypass decimal int conversion limits while retaining
    # exact Python values. These tags never enter the returned application row.
    encoded: list[tuple[str, str, str | None]] = []
    for name, value in record.items():
        if isinstance(value, int):
            encoded.append((name, "int", format(value, "x")))
        elif isinstance(value, float):
            encoded.append((name, "float", value.hex()))
        else:
            encoded.append((name, "null", None))
    return json.dumps(encoded, separators=(",", ":"))


def _decode_numeric_row(payload: str) -> dict[str, Any]:
    return {
        name: int(value, 16) if kind == "int" else float.fromhex(value) if kind == "float" else None
        for name, kind, value in json.loads(payload)
    }
