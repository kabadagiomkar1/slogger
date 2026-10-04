"""Cancelable reference IXR filtering with complete disk-backed membership."""

from __future__ import annotations

import json
import multiprocessing
import struct
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..backends.python.expressions import compile_expression
from ..core.ixr import Expression, _boolean
from ..errors import ToolError
from .models import Diagnostic, RecordPage
from .resources import resident_size

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from .session import Investigation

_MEMBER = struct.Struct("<Q")
_INDEX = struct.Struct("<QQQQ")


@dataclass(frozen=True)
class ViewScope:
    dataset_id: str
    view_id: str


@dataclass(frozen=True)
class FilterScope:
    input_scope: ViewScope
    expression: Expression
    request_generation: int = 0
    backend: Literal["python"] = "python"


@dataclass(frozen=True)
class OperationStatus:
    phase: Literal["pending", "running", "complete", "cancelled", "failed"]
    processed_records: int = 0
    total_records: int = 0
    result_records: int = 0


class RecordView:
    """Immutable successful membership; positions differ from dataset ordinals.

    Close releases this handle. A running dependent operation keeps its own lease.
    Session close releases all handles and cancels workers before removing storage.
    """

    def __init__(self, session: Investigation, path: Path, count: int, scope: FilterScope):
        self.session = session
        self.scope = scope
        self.view_scope = ViewScope(session.dataset_id, uuid.uuid4().hex)
        self.record_count = count
        self._path = path
        self._closed = False
        self._leases = 0
        self._lock = threading.RLock()

    def _acquire(self) -> None:
        with self._lock:
            self._check()
            self._leases += 1

    def _release(self) -> None:
        with self._lock:
            self._leases -= 1
            if self._closed and not self._leases:
                self._path.unlink(missing_ok=True)

    def _check(self) -> None:
        if self._closed or self.session.status.phase == "closed":
            raise ToolError("view_closed", "Filtered view is closed.")

    def page(self, offset: int = 0, limit: int = 100) -> RecordPage:
        with self._lock:
            self._check()
            if offset < 0 or limit < 0 or limit > self.session.limits.max_page_records:
                raise ValueError("page offset/limit exceed the page contract")
            records, origins, identities = [], [], []
            size = 0
            with self._path.open("rb") as members:
                members.seek(offset * _MEMBER.size)
                for _ in range(min(limit, max(0, self.record_count - offset))):
                    ordinal = _MEMBER.unpack(members.read(_MEMBER.size))[0]
                    page = self.session.page(ordinal, 1)
                    cost = resident_size(page.records[0]) + 128
                    if size + cost > self.session.limits.page_memory_bytes:
                        break
                    size += cost
                    records.extend(page.records)
                    origins.extend(page.origins)
                    identities.extend(page.identities)
            return RecordPage(
                self.session.dataset_id,
                offset,
                records,
                origins,
                identities,
                offset + len(records),
                True,
            )

    def position_of(self, ordinal: int) -> int | None:
        """Find the displayed position for a dataset ordinal without a RAM index."""
        with self._lock:
            self._check()
            with self._path.open("rb") as members:
                for position in range(self.record_count):
                    current = _MEMBER.unpack(members.read(_MEMBER.size))[0]
                    if current == ordinal:
                        return position
                    if current > ordinal:
                        break
            return None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if not self._leases:
                self._path.unlink(missing_ok=True)


def _filter_worker(
    connection: Connection,
    data_path: str,
    index_path: str,
    membership_path: str | None,
    count: int,
    expression: Expression,
) -> None:
    """Worker only reads capture; bounded messages leave allocation to the owner."""
    try:
        matcher = compile_expression(expression)
        with Path(data_path).open("rb") as data, Path(index_path).open("rb") as index:
            members = Path(membership_path).open("rb") if membership_path else None
            try:
                output = bytearray()
                for position in range(count):
                    ordinal = _MEMBER.unpack(members.read(_MEMBER.size))[0] if members else position
                    index.seek(ordinal * _INDEX.size)
                    start, length, _, _ = _INDEX.unpack(index.read(_INDEX.size))
                    data.seek(start)
                    record = json.loads(data.read(length))
                    if matcher(record):
                        output.extend(_MEMBER.pack(ordinal))
                    if (position + 1) % 128 == 0:
                        connection.send(("batch", position + 1, bytes(output)))
                        output.clear()
                connection.send(("batch", count, bytes(output)))
                connection.send(("complete",))
            finally:
                if members:
                    members.close()
    except Exception as error:
        code = error.code if isinstance(error, ToolError) else "execution_failed"
        connection.send(("failed", code, str(error)))
    finally:
        connection.close()


class FilterJob:
    """One explicit request. No global current view or editor policy is stored here."""

    def __init__(
        self,
        session: Investigation,
        expression: Expression,
        input_view: RecordView | None,
        request_generation: int,
    ):
        session.require_ready("filter")
        if not _boolean(expression):
            raise TypeError("filter requires a boolean IXR expression")
        if input_view is not None and input_view.session is not session:
            raise ToolError("scope_mismatch", "Input view belongs to a different investigation.")
        self.session = session
        self.scope = FilterScope(
            input_view.view_scope
            if input_view
            else ViewScope(session.dataset_id, session.dataset_id),
            expression,
            request_generation,
        )
        count = input_view.record_count if input_view else session.status.record_count
        self.status = OperationStatus("pending", total_records=count)
        self.diagnostics: tuple[Diagnostic, ...] = ()
        self.view: RecordView | None = None
        self._input = input_view
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._path = session.storage.create_file("filter-" + uuid.uuid4().hex + ".members")
        context = multiprocessing.get_context("spawn")
        self._read, send = context.Pipe(duplex=False)
        if input_view:
            input_view._acquire()
        self._process = context.Process(
            target=_filter_worker,
            args=(
                send,
                str(session._data),
                str(session._index),
                str(input_view._path) if input_view else None,
                count,
                expression,
            ),
            daemon=True,
        )
        try:
            self._process.start()
        except BaseException:
            send.close()
            self._read.close()
            self._path.unlink(missing_ok=True)
            if input_view:
                input_view._release()
            raise
        send.close()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def _monitor(self) -> None:
        self.status = replace(self.status, phase="running")
        try:
            while not self._cancel.is_set():
                if not self._read.poll(0.05):
                    if not self._process.is_alive():
                        raise ToolError(
                            "execution_failed", "Filter worker exited without a result."
                        )
                    continue
                message = self._read.recv()
                if message[0] == "batch":
                    self.session.storage.append(self._path, message[2])
                    self.status = replace(
                        self.status,
                        processed_records=message[1],
                        result_records=self._path.stat().st_size // _MEMBER.size,
                    )
                elif message[0] == "failed":
                    raise ToolError(message[1], message[2])
                elif message[0] == "complete":
                    with self._lock:
                        if not self._cancel.is_set():
                            self.view = RecordView(
                                self.session, self._path, self.status.result_records, self.scope
                            )
                            self.status = replace(self.status, phase="complete")
                    break
        except Exception as error:
            if not self._cancel.is_set():
                code = error.code if isinstance(error, ToolError) else "execution_failed"
                self.diagnostics = (Diagnostic(code, str(error)),)
                self.status = replace(self.status, phase="failed")
        finally:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join()
            self._read.close()
            with self._lock:
                if self._cancel.is_set() and self.status.phase != "complete":
                    self.status = replace(self.status, phase="cancelled")
                if self.view is None:
                    self._path.unlink(missing_ok=True)
            if self._input:
                self._input._release()
            self._done.set()

    def cancel(self) -> None:
        """Request termination; wait() observes completed cleanup and cancellation."""
        with self._lock:
            if not self._done.is_set() and self.status.phase != "complete":
                self._cancel.set()

    def wait(self, timeout: float | None = None) -> RecordView | None:
        """Wait for cleanup; timeout raises TimeoutError without canceling work."""
        if not self._done.wait(timeout):
            raise TimeoutError("Filter is still running.")
        return self.view
