"""Native staging policy over reusable headless owner replacement."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.bindings import GroupBinding
from ..core.ixr import Expression
from ..errors import ToolError
from ..investigation import (
    AggregateResult,
    Investigation,
    RecordIdentity,
    RecordPage,
    RecordRestoration,
    RecordView,
    RefreshJob,
)
from ..investigation.discovery import DiscoveryIndex, DiscoveryJob
from ..investigation.search import SearchOptions, SearchResult
from ..investigation.tree import TraceTree

if TYPE_CHECKING:
    from .app import InvestigationApp


@dataclass(frozen=True)
class RefreshPlan:
    main_expression: Expression
    main_filtered: bool
    detached_expression: Expression
    follows_main: bool
    search_options: SearchOptions
    field: tuple[str, ...] | None
    metrics: tuple[str, ...] | None
    grouping: tuple[GroupBinding, ...]
    tree: bool
    tree_generation: int
    selected: RecordIdentity | None
    pinned: RecordIdentity | None
    console_anchor: RecordIdentity | None
    tree_revealed_record: RecordIdentity | None
    tree_focus_record: RecordIdentity | None
    tree_top_record: RecordIdentity | None
    tree_focus_node: str | None
    tree_top_node: str | None
    expanded_default: bool
    folds: tuple[str, ...]


class StagedState:
    """One bounded staging worker; an obsolete plan settles before its successor."""

    def __init__(
        self,
        replacement: Investigation,
        previous: Investigation,
        plan: RefreshPlan,
        obsolete: StagedState | None = None,
    ):
        self.session, self.previous, self.plan = replacement, previous, plan
        self.main: RecordView | None = None
        self.detached: RecordView | None = None
        self.search: SearchResult | None = None
        self.tree: TraceTree | None = None
        self.discovery: DiscoveryIndex | None = None
        self.aggregate: AggregateResult | None = None
        self.selected: RecordIdentity | None = None
        self.pinned: RecordIdentity | None = None
        self.discovery_job: DiscoveryJob | None = None
        self.obsolete = obsolete
        self.folds: set[int] = set()
        self.fold_identities: dict[int, str] = {}
        self.console_anchor: RecordIdentity | None = None
        self.tree_revealed_record: RecordIdentity | None = None
        self.tree_focus_record: RecordIdentity | None = None
        self.tree_top_record: RecordIdentity | None = None
        self.tree_focus_key = self.tree_top_key = None
        self.selected_page: RecordPage | None = None
        self.pinned_page: RecordPage | None = None
        self.selected_position = 0
        self.console_anchor_position: int | None = None
        self.diagnostics: list[str] = []
        self.error: str | None = None
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self._active: Any = None
        self._handles: list[Any] = []
        self.worker = threading.Thread(target=self._run, name="slogger-refresh-scopes", daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _check(self) -> None:
        if self.cancel_event.is_set():
            raise ToolError("operation_canceled", "Replacement staging canceled.")

    def _wait(self, job: Any, *, indexed: bool = False) -> Any:
        self._active = job
        while not job.done:
            if self.cancel_event.wait(0.05):
                job.cancel()
        result = job.result() if indexed and job.status.phase == "complete" else job.wait(0)
        if indexed and job.status.phase != "complete":
            result = None
        if result is None:
            diagnostic = getattr(job.status, "diagnostic", None)
            diagnostics = getattr(job, "diagnostics", ())
            raise ToolError(
                diagnostic.code if diagnostic else "refresh_stage_failed",
                diagnostic.message
                if diagnostic
                else (
                    diagnostics[0].message if diagnostics else "Required replacement scope failed."
                ),
            )
        self._handles.append(result)
        self._check()
        self._active = None
        return result

    def _run(self) -> None:
        try:
            if self.obsolete is not None:
                self.obsolete.dispose()
                self.obsolete = None
            p, session = self.plan, self.session
            if p.main_filtered:
                self.main = self._wait(session.filter(p.main_expression))
            if not p.follows_main:
                self.detached = self._wait(session.filter(p.detached_expression))
            if p.search_options.text:
                self.search = self._wait(session.search(p.search_options, input_view=self.main))
            if p.tree:
                self.tree = self._wait(
                    session.build_tree(input_view=self.main, request_generation=p.tree_generation),
                    indexed=True,
                )
                for identity in p.folds:
                    self._check()
                    key = self.tree.node_for_identity(identity, delivered_only=False)
                    if key is not None:
                        self.folds.add(key)
                        self.fold_identities[key] = identity
            self.discovery_job = session.discover()
            self.discovery = self._wait(self.discovery_job, indexed=True)
            if p.field is not None:
                arguments = dict(
                    grouping=p.grouping, input_view=self.main if p.follows_main else self.detached
                )
                job = (
                    session.count_values(p.field, **arguments)
                    if p.metrics is None
                    else session.summarize_values(p.field, metrics=p.metrics, **arguments)
                )
                self.aggregate = self._wait(job)
            restorations: dict[RecordIdentity, RecordRestoration] = {}
            for name, identity in (
                ("selected", p.selected),
                ("pinned", p.pinned),
                ("console_anchor", p.console_anchor),
                ("tree_revealed_record", p.tree_revealed_record),
                ("tree_focus_record", p.tree_focus_record),
                ("tree_top_record", p.tree_top_record),
            ):
                self._check()
                if identity is None:
                    continue
                restored = restorations.get(identity)
                if restored is None:
                    restored = session.restore_record(
                        self.previous, identity, cancel_event=self.cancel_event
                    )
                    restorations[identity] = restored
                setattr(self, name, restored.identity)
                if restored.diagnostic:
                    self.diagnostics.append(
                        f"{name}: {restored.diagnostic.code}: {restored.diagnostic.message}"
                    )
            if (
                self.selected is not None
                and self.main is not None
                and self.main.position_of(self.selected.ordinal) is None
            ):
                self.selected = None
                self.diagnostics.append(
                    "selected: record_outside_scope · first applied Main record selected"
                )
            if self.tree is not None:
                for name in ("tree_focus", "tree_top"):
                    node = getattr(p, name + "_node")
                    record = getattr(self, name + "_record")
                    key = self.tree.node_for_identity(node) if node is not None else None
                    if record is not None and (
                        self.main is None or self.main.position_of(record.ordinal) is not None
                    ):
                        key = -(record.ordinal + 1)
                    setattr(self, name + "_key", key)
            if self.selected is not None and self.main is not None:
                position = self.main.position_of(self.selected.ordinal)
                self.selected_position = position if position is not None else 0
            population = (
                self.main.record_count if self.main is not None else session.status.record_count
            )
            if population:
                self.selected_page = (
                    self.main.page(self.selected_position, 1)
                    if self.main is not None
                    else session.page(self.selected.ordinal if self.selected is not None else 0, 1)
                )
                if not self.selected_page.records:
                    raise ToolError(
                        "refresh_stage_failed", "Initial replacement record is unavailable."
                    )
            if self.pinned is not None:
                self.pinned_page = session.page(self.pinned.ordinal, 1)
                if not self.pinned_page.records:
                    raise ToolError(
                        "refresh_stage_failed", "Pinned replacement record is unavailable."
                    )
            if self.console_anchor is not None:
                self.console_anchor_position = (
                    self.main.position_of(self.console_anchor.ordinal)
                    if self.main is not None
                    else self.console_anchor.ordinal
                )
            self._check()
        except Exception as error:
            self.error = str(error)
            try:
                self.dispose()
            except Exception as cleanup:
                self.error += f"; cleanup_failed: {cleanup}"
        finally:
            self.done.set()

    def close(self) -> None:
        self.cancel()
        self.worker.join()
        self.dispose()

    def dispose(self) -> None:
        """Called only after the sole reader has settled, or by that reader itself."""
        if self.obsolete is not None:
            self.obsolete.dispose()
            self.obsolete = None
        for handle in self._handles:
            handle.close()
        self._handles.clear()


class RetiredOwner:
    """Strong ownership of old results until all completion and operation readers settle."""

    def __init__(self, session: Investigation, handles: tuple[Any, ...]):
        self.session, self.handles = session, handles

    def close(self) -> None:
        self.session.close()
        self.handles = ()


class RefreshController:
    def __init__(self, app: InvestigationApp):
        self.app = app
        self.job: RefreshJob | None = None
        self.stage: StagedState | None = None
        self.generation = 0
        self.status = ""
        self._cancel = False
        self._cleanup: threading.Thread | None = None
        self._cleanup_error: str | None = None
        self._leftovers: tuple[Any, ...] = ()
        self._cleanup_done = threading.Event()

    @property
    def busy(self) -> bool:
        return self.job is not None or self._cleanup is not None or bool(self._leftovers)

    def start(self) -> None:
        if self._leftovers and self._cleanup is None:
            self._clean(self._leftovers)
            self.status = "Refresh retrying accounted cleanup"
            return
        if self.busy:
            self.status = "Refresh already running · Esc cancel"
            return
        self.generation += 1
        self._cancel = False
        try:
            self.job = self.app.session.refresh(request_generation=self.generation)
        except (ToolError, OSError) as error:
            self.status = f"Refresh unavailable: {error}"
        else:
            self.status = "Refresh capturing · current investigation remains usable · Esc cancel"

    def cancel(self) -> None:
        if self.job is not None:
            self._cancel = True
            self.job.cancel()
            if self.stage is not None:
                self.stage.cancel()
            self.status = "Refresh canceling · current investigation retained"

    def _clean(self, owners: tuple[Any, ...], readers: tuple[threading.Thread, ...] = ()) -> None:
        self._leftovers = owners
        self._cleanup_error = None
        self._cleanup_done.clear()

        def close() -> None:
            try:
                for reader in readers:
                    reader.join()
                for owner in owners:
                    owner.close()
            except Exception as error:
                self._cleanup_error = str(error)
            else:
                self._leftovers = ()
            finally:
                self._cleanup_done.set()

        self._cleanup = threading.Thread(target=close, name="slogger-refresh-cleanup", daemon=True)
        try:
            self._cleanup.start()
        except Exception as error:
            self._cleanup = None
            self._cleanup_error = str(error)
            self.status += f" · cleanup_failed: {error}; leftovers remain accounted"
            self._cleanup_done.set()

    def poll(self) -> None:
        if not self.app.is_running:
            return
        if self._cleanup is not None and self._cleanup_done.is_set():
            self._cleanup.join()
            self._cleanup = None
            self.app._origin_status()
            if not self._cleanup_error and self.status == "Refresh retrying accounted cleanup":
                self.status = "Refresh cleanup complete · current investigation retained"
            if self._cleanup_error:
                self.status += (
                    f" · cleanup_failed: {self._cleanup_error}; leftovers remain accounted"
                )
                self.app.notify(self.status, markup=False)
        job = self.job
        if job is None or not job.done:
            return
        if job.session is not self.app.session or job.scope.request_generation != self.generation:
            self._cancel = True
        if self.stage is not None and not self.stage.done.is_set():
            if self._cancel or self.stage.plan != self.app.refresh_plan():
                self.stage.cancel()
            return
        if self._cancel or job.status.phase != "ready":
            reason = job.status.diagnostic.message if job.status.diagnostic else "Canceled"
            self.status = f"Refresh {reason} · current investigation retained"
            stage = self.stage
            self.stage = None
            self.job = None
            self._clean((job, stage) if stage is not None else (job,))
            return
        plan = self.app.refresh_plan()
        obsolete = None
        if self.stage is not None and self.stage.plan != plan:
            obsolete = self.stage
            self.stage = None
        if self.stage is None:
            try:
                self.stage = StagedState(job.result(), job.session, plan, obsolete)
            except Exception as error:
                self.status = (
                    f"Refresh staging unavailable: {error} · current investigation retained"
                )
                self.job = None
                self._clean((job, obsolete) if obsolete is not None else (job,))
                return
            self.status = (
                "Refresh staging latest applied scopes · current investigation remains usable"
            )
            return
        if self.stage.error:
            self.status = (
                f"Refresh staging failed: {self.stage.error} · current investigation retained"
            )
            stage = self.stage
            self.stage = None
            self.job = None
            self._clean((job, stage) if stage is not None else (job,))
            return
        stage = self.stage
        try:
            replacement = job.commit()
        except (ToolError, OSError) as error:
            self.status = f"Refresh publication failed: {error} · current investigation retained"
            self.job = self.stage = None
            self._clean((job, stage))
            return
        readers, handles = self.app.adopt_refresh(replacement, stage)
        self.stage = self.job = None
        self.status = "Refresh complete · " + (
            "; ".join(stage.diagnostics) or "verified selection restored"
        )
        # Retain handles until old session close has settled; WeakSets are not ownership.
        self._clean((RetiredOwner(job.session, handles), job), readers)

    def close(self) -> None:
        self.cancel()
        if self.stage is not None:
            self.stage.worker.join()
        if self.job is not None:
            self.job.close()
            self.job = None
        if self._cleanup is not None:
            self._cleanup.join()
            self._cleanup = None
        for owner in self._leftovers:
            owner.close()
        self._leftovers = ()
