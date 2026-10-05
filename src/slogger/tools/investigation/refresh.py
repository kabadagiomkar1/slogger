"""Staged owner replacement and verified source-occurrence restoration."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from ..errors import ToolError
from .models import Diagnostic, RecordIdentity

if TYPE_CHECKING:
    from ..core.runtime import SourceOrigin
    from .session import Investigation


@dataclass(frozen=True)
class RefreshScope:
    owner_id: str
    dataset_id: str
    request_id: str
    request_generation: int = 0


@dataclass(frozen=True)
class RefreshStatus:
    phase: Literal["pending", "capturing", "ready", "committed", "failed", "canceled", "closed"]
    diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class RecordRestoration:
    identity: RecordIdentity | None = None
    origin: SourceOrigin | None = None
    diagnostic: Diagnostic | None = None


class RefreshJob:
    """Stage a separate owner; the caller commits only after required scopes are ready."""

    def __init__(self, session: Investigation, background: bool, request_generation: int):
        self.session = session
        self.scope = RefreshScope(
            session.owner_id, session.dataset_id, uuid.uuid4().hex, request_generation
        )
        self.status = RefreshStatus("pending")
        self.replacement: Investigation | None = None
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._lock = threading.RLock()
        self._committed = False
        self._disk_budget = session.storage.share_budget() if session.cache_store is None else None
        session.register_view(self)
        with session._lifecycle_lock:
            session._refreshes.add(self)
        if background:
            self._worker = threading.Thread(
                target=self._run, name=f"slogger-refresh-{self.scope.request_id}", daemon=True
            )
            try:
                self._worker.start()
            except BaseException:
                self._done.set()
                self.status = RefreshStatus("failed")
                with session._lifecycle_lock:
                    session._refreshes.discard(self)
                raise
        else:
            self._run()

    @property
    def _closed(self) -> bool:
        return self.status.phase in ("failed", "canceled", "closed", "committed")

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        with self._lock:
            if not self._committed:
                self._cancel.set()
                if self.status.phase == "ready":
                    self.status = RefreshStatus(
                        "canceled",
                        Diagnostic("operation_canceled", "Refresh canceled; prior owner retained."),
                    )
                if self.replacement is not None:
                    self.replacement.cancel()

    def wait(self, timeout: float | None = None) -> Investigation | None:
        if not self._done.wait(timeout):
            raise TimeoutError("Refresh capture is still running.")
        return self.replacement if self.status.phase in ("ready", "committed") else None

    def result(self) -> Investigation:
        result = self.wait(0)
        if result is None:
            raise ToolError("refresh_not_ready", "Refresh replacement is not ready.")
        return result

    def commit(self) -> Investigation:
        with self._lock, self.session._lifecycle_lock:
            self.session.require_ready("refresh publication")
            if self._cancel.is_set():
                raise ToolError("operation_canceled", "Refresh was canceled.")
            replacement = self.result()
            replacement.require_ready("refresh publication")
            self._committed = True
            self.status = replace(self.status, phase="committed")
            self.session._refreshes.discard(self)
            return replacement

    def close(self) -> None:
        self.cancel()
        self._done.wait()
        with self._lock:
            if not self._committed and self.replacement is not None:
                try:
                    self.replacement.close()
                except Exception as error:
                    self.status = RefreshStatus("failed", Diagnostic("cleanup_failed", str(error)))
                    raise ToolError("cleanup_failed", str(error)) from error
                self.replacement = None
            self.status = replace(self.status, phase="closed")
            with self.session._lifecycle_lock:
                self.session._refreshes.discard(self)

    def _run(self) -> None:
        from .session import Investigation

        try:
            self.status = RefreshStatus("capturing")
            self.replacement = Investigation.open(
                [source.source for source in self.session.sources],
                storage_dir=self.session.storage.root.parent,
                limits=self.session.limits,
                background=True,
                _disk_budget=self._disk_budget,
                _configuration_group=self.session._configuration_group,
                _cache_store=self.session.cache_store,
                cache_dir=self.session.cache_store.root if self.session.cache_store else None,
                cache_expiry_seconds=self.session.cache_store.expiry_seconds
                if self.session.cache_store
                else 0,
            )
            replacement = self.replacement
            while not replacement._done.wait(0.05):
                if self._cancel.is_set():
                    replacement.cancel()
            with self._lock:
                if self._cancel.is_set():
                    raise ToolError("operation_canceled", "Refresh canceled; prior owner retained.")
                if not replacement.status.complete:
                    diagnostic = replacement.diagnostics.terminal
                    raise ToolError(
                        diagnostic.code if diagnostic else "refresh_failed",
                        diagnostic.message if diagnostic else "Replacement capture failed.",
                    )
                self.session.require_ready("refresh readiness")
                self.status = RefreshStatus("ready")
        except Exception as error:
            code = error.code if isinstance(error, ToolError) else "refresh_failed"
            self.status = RefreshStatus(
                "canceled" if code == "operation_canceled" else "failed",
                Diagnostic(code, str(error)),
            )
            if self.replacement is not None:
                try:
                    self.replacement.close()
                    self.replacement = None
                except Exception as cleanup:
                    self.status = RefreshStatus(
                        "failed", Diagnostic("cleanup_failed", str(cleanup))
                    )
        finally:
            if self.replacement is None:
                with self.session._lifecycle_lock:
                    self.session._refreshes.discard(self)
            self._done.set()
