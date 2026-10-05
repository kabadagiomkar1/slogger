"""Optional native split view. Shared Investigation operations stay headless."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from ..core.bindings import FieldBinding, GroupBinding
from ..core.filter_language import format_field_path
from ..core.runtime import SourceOrigin
from ..errors import ToolError
from ..investigation import (
    AggregateJob,
    AggregateResult,
    FilterJob,
    Investigation,
    RecordIdentity,
    RecordView,
)
from ..investigation.discovery import DiscoveryJob
from ..investigation.filters import ViewScope
from ..investigation.search import SearchResult
from ..investigation.tree import TraceTree, TreeJob
from .aggregates import AggregatePane, AggregateViewport, format_grouping
from .console import ConsoleViewport
from .filter_editor import FilterEditor
from .inspector import JSONInspector
from .preferences import NativePreferences, PreferencesStore
from .refresh import RefreshController, RefreshPlan, StagedState
from .search import SearchBar, SearchController
from .settings import SettingsScreen
from .text import visible_text
from .tree import TreeViewport


@dataclass(frozen=True)
class AggregateRequest:
    """Consumer-owned queued scope and presentation for one replacement request."""

    path: tuple[str, ...]
    generation: int
    label: str
    input_view: RecordView | None
    metrics: tuple[str, ...] | None
    grouping: tuple[GroupBinding, ...]


class InvestigationApp(App[None]):
    """Native consumer of a progressively published captured prefix."""

    TITLE = "slogger investigation"
    BINDINGS = [
        Binding("f", "focus_filter(True)", "Filter"),
        Binding("/", "focus_search(True)", "Search"),
        Binding("a", "focus_aggregate(True)", "Aggregate"),
        Binding("m", "focus_metrics(True)", "Metrics"),
        Binding("n", "next_match(True)", "Next match", show=False),
        Binding("N,shift+n", "previous_match(True)", "Previous match", show=False),
        Binding("comma", "settings(True)", "Settings"),
        Binding("b", "tree", "Flat / tree"),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("escape", "cancel_capture", "Cancel work"),
        Binding("tab", "next_pane", "Switch pane", priority=True),
        Binding("shift+tab", "previous_pane", "Previous pane", show=False, priority=True),
        Binding("ctrl+tab", "next_pane(True)", "Switch pane", priority=True),
        Binding(
            "ctrl+shift+tab", "previous_pane(True)", "Previous pane", show=False, priority=True
        ),
        Binding("alt+1", "focus_console", "Console", show=False, priority=True),
        Binding("alt+2", "focus_inspector", "JSON", show=False, priority=True),
        Binding("alt+3", "focus_counts", "Aggregates", show=False, priority=True),
        Binding("i", "inspector", "JSON"),
        Binding("[", "inspector_width(-5)", "Narrower", show=False),
        Binding("]", "inspector_width(5)", "Wider", show=False),
        Binding("f2", "focus_inspector", "Focus JSON", show=False),
        Binding("f3", "focus_console", "Focus console", show=False),
        Binding("f4", "focus_filter", "Main filter", show=False),
        Binding("f10", "settings", "Settings", show=False),
        Binding("f5", "focus_aggregate", "Field aggregate", show=False),
        Binding("f6", "focus_counts", "Focus aggregate", show=False),
        Binding("f7", "focus_search", "Search", show=False),
        Binding("f8", "next_match", "Next match", show=False),
        Binding("shift+f8", "previous_match", "Previous match", show=False),
        Binding("f9", "focus_metrics", "Metrics", show=False),
        Binding("ctrl+d", "focus_aggregate_filter", "Aggregate scope", show=False, priority=True),
        Binding("ctrl+a", "toggle_aggregate", "Aggregate pane", show=False),
        Binding("ctrl+j", "focus_inspector", "Focus JSON", show=False),
        Binding("ctrl+k", "focus_console", "Focus console", show=False),
        Binding("p", "pin", "Pin JSON"),
        Binding("c", "copy_record", "Copy JSON"),
    ]
    CSS = """
    Screen { background: $background; }
    #heading { height: auto; min-height: 1; max-height: 6; padding: 0 1; color: $text-muted; }
    #split { height: 1fr; }
    #stream { width: 1fr; }
    #inspector { width: 33%; min-width: 25; border-left: solid $primary-muted; }
    .pane-heading { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    .pane-heading.active-pane { background: $primary-muted; color: $text; text-style: bold; }
    #console, #json, #tree { height: 1fr; }
    #inspector-status { height: auto; max-height: 3; padding: 0 1; color: $text-muted; }
    #origin { height: auto; max-height: 6; padding: 0 1; color: $text-muted; }
    """

    def __init__(
        self,
        session: Investigation,
        *,
        clipboard_writer: Callable[[str], None] | None = None,
        preferences: NativePreferences | None = None,
        preferences_path: str | os.PathLike[str] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self._replacement_generation = 0
        self.refresh_controller = RefreshController(self)
        self.preferences_store = PreferencesStore(preferences_path)
        self._preferences = preferences or NativePreferences(
            limits=session.limits,
            cache_expiry_seconds=session.cache_store.expiry_seconds
            if session.cache_store
            else 7 * 86400,
        )
        self.theme = "textual-dark" if self._preferences.theme == "dark" else "textual-light"
        self._clipboard_writer = clipboard_writer
        self.copy_status = ""
        self.inspector_visible = self._preferences.inspector_visible
        self.inspector_percent = self._preferences.inspector_percent
        self._narrow_inspector = False
        self.selected_ordinal = 0
        self.selected_position = 0
        self.main_filter = FilterEditor()
        self.aggregate_filter = FilterEditor(
            id="aggregate-editor", input_id="aggregate-filter", label="Scope", edit_key="Ctrl+D"
        )
        self.main_filter.bind_owner(session.owner_id, 0)
        self.aggregate_filter.bind_owner(session.owner_id, 0)
        self.aggregate_follows_main = True
        self.detached_view: RecordView | None = None
        self.pending_detached_filter: FilterJob | None = None
        self._queued_detached_filter: FilterEditor.ApplyRequested | None = None
        self._detached_filter_text = ""
        self._aggregate_waiting_for_filter = False
        self.discovery_job: DiscoveryJob | None = None
        self.search_bar = SearchBar()
        self.search = SearchController(self)
        self.filtered_view: RecordView | None = None
        self.pending_filter: FilterJob | None = None
        self._filter_text = ""
        self._queued_filter: FilterEditor.ApplyRequested | None = None
        self.selected_identity: RecordIdentity | None = None
        self.selected_record: dict[str, object] | None = None
        self.selected_origin: SourceOrigin | None = None
        self.pinned_identity: RecordIdentity | None = None
        self.inspected_identity: RecordIdentity | None = None
        self.inspected_origin: SourceOrigin | None = None
        self.inspected_record: dict[str, object] | None = None
        self.requested_field: tuple[str, ...] | None = None
        self.aggregate_metrics: tuple[str, ...] | None = None
        self.aggregate_grouping: tuple[GroupBinding, ...] = ()
        self.aggregate_result: AggregateResult | None = None
        self._retired_handles: list[AggregateResult | RecordView] = []
        self._retirement_status = ""
        self.pending_aggregate: AggregateJob | None = None
        self._aggregate_generation = 0
        self._aggregate_label = ""
        self._queued_aggregate: AggregateRequest | None = None
        self._capture_status = session.status
        self.tree_mode = False
        self.tree_status = ""
        self._tree_requested = False
        self._tree_job: TreeJob | None = None
        self._tree_result: TraceTree | None = None
        self._tree_generation = 0

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(
            visible_text(self.capture_heading(), multiline=True), id="heading", markup=False
        )
        yield self.main_filter
        yield self.search_bar
        with Horizontal(id="split"):
            with Vertical(id="stream"):
                yield Static(
                    "CONSOLE · pan · time · duration off",
                    id="console-heading",
                    classes="pane-heading",
                )
                yield ConsoleViewport(self.session, self._preferences.console)
                tree = TreeViewport()
                tree.display = False
                yield tree
                aggregate = AggregatePane(self.aggregate_filter)
                aggregate.display = self._preferences.aggregate_visible
                yield aggregate
            with Vertical(id="inspector"):
                yield Static(
                    "JSON · parsed record" if status.record_count else "JSON · no record selected",
                    classes="pane-heading",
                    id="inspector-heading",
                    markup=False,
                )
                yield Static("Complete JSON", id="inspector-status", markup=False)
                inspector = JSONInspector()
                inspector.line_numbers = self._preferences.json_line_numbers
                yield inspector
        yield Static(id="origin", markup=False)
        yield Footer()

    def capture_heading(self) -> str:
        status = self.session.status
        state = status.phase if status.complete else f"{status.phase} · incomplete"
        progress = f"{status.captured_bytes:,}/{status.total_bytes:,} bytes captured"
        if status.phase in ("verifying", "verifying_cache") or status.cache_state == "reused":
            progress = f"{status.verified_bytes:,}/{status.total_bytes:,} bytes verified"
        if status.phase == "verifying_cache":
            progress += (
                f" · {status.cache_verified_bytes:,}/{status.cache_total_bytes:,}"
                " cache bytes verified"
            )
        if status.cache_state == "reused":
            state += " · verified cache reuse"
        text = (
            f"IXR · {status.record_count:,} records · {state} · {progress} · "
            f"{status.skipped_lines:,} skipped lines"
        )
        if status.cache_reason:
            text += f"\nCache rejected: {status.cache_reason}"
        if status.phase in ("failed", "canceled") and self.session.diagnostics.terminal:
            diagnostic = self.session.diagnostics.terminal
            location = (
                f"{diagnostic.origin.source}:{diagnostic.origin.position} · "
                if diagnostic.origin is not None
                else ""
            )
            text += f"\n{diagnostic.code}: {location}{diagnostic.message}"
        if self.tree_status:
            text += f"\n{self.tree_status}"
        if self.refresh_controller.status:
            text += f"\n{self.refresh_controller.status}"
        if self._retirement_status:
            text += f"\n{self._retirement_status}"
        return text

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Refresh sources",
            "Ctrl+R · Keep current investigation until replacement scopes are ready",
            self.action_refresh,
        )
        yield SystemCommand(
            "Retry cleanup",
            "Retry deleting retired results; failed allocations remain accounted",
            self.action_retry_cleanup,
        )
        yield SystemCommand(
            "Settings", ", · Session options and explicit saved defaults", self.action_settings
        )
        yield SystemCommand(
            "Flat / tree", "B · Explore Main records and ancestor context", self.action_tree
        )
        yield SystemCommand(
            "Fold tree node",
            "Space or Enter in tree · Toggle focused node",
            self.query_one(TreeViewport).action_fold,
        )
        yield SystemCommand(
            "Fold / expand all",
            "Shift+Space in tree · Toggle every node",
            self.query_one(TreeViewport).action_fold_all,
        )
        yield SystemCommand(
            "Retry field discovery",
            "Rebuild canceled or failed whole-dataset choices",
            self.action_discovery,
        )
        yield SystemCommand(
            "Search records",
            "/ · Literal text; Enter next, Shift+Enter previous",
            self.action_focus_search,
        )
        yield SystemCommand(
            "Next search match", "N · Navigate complete matching records", self.action_next_match
        )
        yield SystemCommand(
            "Previous search match", "Shift+N · Navigate backward", self.action_previous_match
        )
        yield SystemCommand(
            "Edit Main filter", "F · Infix IXR; Enter applies", self.action_focus_filter
        )
        yield SystemCommand(
            "Cancel filter/loading", "Escape · Keep the successful view", self.action_cancel_capture
        )
        yield SystemCommand(
            "Summarize selected field",
            "A · Exact values following Main",
            self.action_focus_aggregate,
        )
        yield SystemCommand(
            "Edit independent aggregate filter",
            "Ctrl+D · Copy applied Main on detach; Enter applies",
            self.action_focus_aggregate_filter,
        )
        yield SystemCommand(
            "Reattach aggregate to Main",
            "Resume following the latest applied Main filter",
            self.action_reattach_aggregate,
        )
        yield SystemCommand(
            "Focus aggregate", "Alt+3 · Browse every group", self.action_focus_counts
        )
        yield SystemCommand(
            "Toggle aggregate pane", "Ctrl+A · Show / hide lower pane", self.action_toggle_aggregate
        )
        yield SystemCommand(
            "Edit aggregate metrics", "M · Values or numeric metrics", self.action_focus_metrics
        )
        yield SystemCommand(
            "Edit aggregate grouping",
            "Exact paths, comma-separated; optional as name",
            self.action_focus_grouping,
        )
        yield SystemCommand("Toggle JSON", "I · Hide or show the inspector", self.action_inspector)
        yield SystemCommand(
            "Focus JSON",
            "Alt+2 · Inspect JSON, including narrow screens",
            self.action_focus_inspector,
        )
        yield SystemCommand(
            "Focus console", "Alt+1 · Return to the stream", self.action_focus_console
        )
        yield SystemCommand("Pin JSON", "P · Pin or unpin the inspected record", self.action_pin)
        yield SystemCommand(
            "Copy JSON", "C · Send complete JSON to the terminal clipboard", self.action_copy_record
        )
        yield SystemCommand(
            "Narrower JSON", "[ · Reduce inspector width", lambda: self.action_inspector_width(-5)
        )
        yield SystemCommand(
            "Wider JSON", "] · Increase inspector width", lambda: self.action_inspector_width(5)
        )
        yield SystemCommand(
            "JSON line numbers",
            "L in JSON · Toggle line numbers",
            self.query_one(JSONInspector).action_line_numbers,
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.focused, Input) and action in (
            "tree",
            "quit",
            "inspector",
            "inspector_width",
            "pin",
            "copy_record",
        ):
            return False
        if parameters == (True,) and isinstance(self.focused, Input):
            if action not in ("next_pane", "previous_pane"):
                return False
        if action in ("next_pane", "previous_pane"):
            if parameters == (True,):
                return True
            return isinstance(
                self.focused, (ConsoleViewport, JSONInspector, TreeViewport, AggregateViewport)
            )
        return super().check_action(action, parameters)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._refresh_focus()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self._refresh_focus()

    def _focus_name(self) -> str:
        focused = self.focused
        labels = {
            "console": "Console",
            "tree": "Tree",
            "json": "JSON",
            "main-filter": "Main filter",
            "record-search": "Search",
            "aggregate-results": "Aggregates",
            "aggregate-field": "Aggregate field",
            "aggregate-metrics": "Aggregate metrics",
            "aggregate-grouping": "Aggregate grouping",
            "aggregate-filter": "Aggregate filter",
        }
        return labels.get((focused.id or "") if focused is not None else "", "Controls")

    def _refresh_focus(self) -> None:
        # Descendant focus messages can remain queued after the screen is removed.
        if not self.is_mounted or not self.screen_stack:
            return
        focused = self.focused
        self.query_one("#console-heading").set_class(
            isinstance(focused, (ConsoleViewport, TreeViewport)), "active-pane"
        )
        self.query_one("#inspector-heading").set_class(
            isinstance(focused, JSONInspector), "active-pane"
        )
        aggregate = self.query_one(AggregatePane)
        self.query_one("#aggregate-mode").set_class(
            focused is not None and aggregate in focused.ancestors, "active-pane"
        )
        self._origin_status()

    def on_mount(self) -> None:
        self.query_one(JSONInspector).binding = self.session.owner_id, self._replacement_generation
        self.query_one(AggregatePane).binding = self.session.owner_id, self._replacement_generation
        self.show_record(0)
        self.on_console_viewport_options_changed(
            ConsoleViewport.OptionsChanged(self._preferences.console)
        )
        self._layout_inspector()
        self.set_interval(0.05, self.refresh_replacement)
        self.set_interval(0.1, self.refresh_capture)
        self.set_interval(0.05, self.refresh_filter)
        self.set_interval(0.05, self.search.refresh)
        self.set_interval(0.05, self.refresh_detached_filter)
        self.set_interval(0.05, self.refresh_aggregate)
        self.set_interval(0.1, self.refresh_discovery)
        self.refresh_discovery()

    def _current_binding(self, message: object) -> bool:
        binding = getattr(message, "binding", (None, 0))
        return binding == (None, 0) or binding == (
            self.session.owner_id,
            self._replacement_generation,
        )

    def _retire_handle(self, handle: AggregateResult | RecordView, *, report: bool = True) -> None:
        """Keep a failed retired allocation owned independently of current publication."""
        if handle not in self._retired_handles:
            self._retired_handles.append(handle)
        try:
            handle.close()
        except (ToolError, OSError) as error:
            self._retirement_status = (
                f"cleanup_failed: {error}; retired allocation remains accounted · Retry cleanup"
            )
            if report and self.is_running:
                self.notify(visible_text(self._retirement_status), markup=False)
                self.query_one("#heading", Static).update(
                    visible_text(self.capture_heading(), multiline=True)
                )
        else:
            self._retired_handles.remove(handle)
            if not self._retired_handles:
                self._retirement_status = ""

    def action_retry_cleanup(self) -> None:
        # Each handle gets its own attempt; one failed deletion must not strand another lease.
        for handle in tuple(self._retired_handles):
            self._retire_handle(handle)
        if self.is_running:
            self.query_one("#heading", Static).update(
                visible_text(self.capture_heading(), multiline=True)
            )

    def action_refresh(self) -> None:
        self.refresh_controller.start()
        self.query_one("#heading", Static).update(
            visible_text(self.capture_heading(), multiline=True)
        )

    def refresh_replacement(self) -> None:
        self.refresh_controller.poll()
        if self.is_running and self.refresh_controller.status:
            self.query_one("#heading", Static).update(
                visible_text(self.capture_heading(), multiline=True)
            )

    def refresh_plan(self) -> RefreshPlan:
        tree = self.query_one(TreeViewport)
        console = self.query_one(ConsoleViewport)

        def leaf(key):
            return self.session.identity_at(-key - 1) if key is not None and key < 0 else None

        def node(key):
            return (
                tree.trace_tree.node_identity(key)
                if tree.trace_tree is not None and key is not None and key > 0
                else None
            )

        anchor = None
        if 0 <= console._top[0] < console.record_count:
            source = console.view if console.view is not None else self.session
            anchor = source.identity_at(console._top[0])
        return RefreshPlan(
            self.main_filter.applied_expression,
            self.filtered_view is not None,
            self.main_filter.pending_generation,
            self.aggregate_filter.applied_expression,
            self.aggregate_follows_main,
            self.search.options(),
            self.requested_field,
            self.aggregate_metrics,
            self.aggregate_grouping,
            self.tree_mode or self._tree_requested,
            self._tree_generation + 1,
            self.selected_identity,
            self.pinned_identity,
            anchor,
            leaf(-(tree._revealed_ordinal + 1)) if tree._revealed_ordinal is not None else None,
            leaf(tree.focused_key),
            leaf(tree._top),
            node(tree.focused_key),
            node(tree._top),
            tree.expanded_default,
            tuple(tree._exception_identities.values()),
        )

    def adopt_refresh(self, session: Investigation, stage: StagedState):
        """One UI turn publishes every required binding; no event can see a half-swap."""

        def pending(editor, queued, job, text):
            if editor.pending_generation is None:
                return None
            if queued is not None:
                return queued.text, queued.expression, queued.generation
            if job is not None:
                return text, job.scope.expression, editor.pending_generation
            return None

        main_pending = pending(
            self.main_filter, self._queued_filter, self.pending_filter, self._filter_text
        )
        detached_pending = pending(
            self.aggregate_filter,
            self._queued_detached_filter,
            self.pending_detached_filter,
            self._detached_filter_text,
        )
        inspector = self.query_one(JSONInspector)
        selected_path, inspector_scroll = inspector.selected_path, inspector.scroll_offset
        was_inspected = self.inspected_identity
        console = self.query_one(ConsoleViewport)
        console_scroll, console_line = console.scroll_offset.x, console._top[1]
        tree = self.query_one(TreeViewport)
        tree_scroll, tree_line = tree.scroll_offset.x, tree._top_line
        aggregate_viewport = self.query_one(AggregateViewport)
        aggregate_position = (
            aggregate_viewport.selected,
            aggregate_viewport.top,
            aggregate_viewport.scroll_offset.x,
        )
        focus = self.focused
        handles = tuple(
            item
            for item in (
                self.filtered_view,
                self.detached_view,
                self.search.result,
                self.search.pending,
                self.pending_filter,
                self.pending_detached_filter,
                self.pending_aggregate,
                self.aggregate_result,
                self.discovery_job,
                self._tree_job,
                self._tree_result,
                *self._retired_handles,
            )
            if item is not None
        )
        self._retired_handles = []
        self._retirement_status = ""
        for job in (
            self.pending_filter,
            self.pending_detached_filter,
            self.pending_aggregate,
            self.search.pending,
            self._tree_job,
        ):
            if job is not None:
                job.cancel()
        self._replacement_generation += 1
        readers = tuple(
            reader
            for editor in (self.main_filter, self.aggregate_filter)
            if (reader := editor.bind_owner(session.owner_id, self._replacement_generation))
            is not None
        )
        self.session = session
        self._capture_status = session.status
        self.filtered_view, self.detached_view = stage.main, stage.detached
        self.pending_filter = self.pending_detached_filter = self.pending_aggregate = None
        self._queued_filter = self._queued_detached_filter = self._queued_aggregate = None
        self._aggregate_waiting_for_filter = False
        self.search.pending = None
        self.search.generation += 1
        self.search._dirty_at = None
        self.search._blocked = main_pending is not None
        self.search.result = stage.search if main_pending is None else None
        options = stage.plan.search_options if stage.plan.search_options.text else None
        console.bind_owner(
            session, stage.main, stage.selected_position, self._replacement_generation
        )
        inspector.binding = console.binding
        self.query_one(AggregatePane).binding = console.binding
        self.selected_identity = self.selected_record = self.selected_origin = None
        self.pinned_identity = stage.pinned
        self.selected_position = stage.selected_position
        self.selected_ordinal = 0
        page = stage.selected_page
        if page is not None:
            self.selected_identity, self.selected_origin, self.selected_record = (
                page.identities[0],
                page.origins[0],
                page.records[0],
            )
            self.selected_ordinal = page.identities[0].ordinal
        if stage.pinned is not None:
            page = stage.pinned_page
            assert page is not None
            self.inspected_identity, self.inspected_origin, self.inspected_record = (
                page.identities[0],
                page.origins[0],
                page.records[0],
            )
            inspector.set_record(self.inspected_record)
        else:
            self._show_selection()
        same_inspected = (was_inspected == stage.plan.pinned and stage.pinned is not None) or (
            was_inspected == stage.plan.selected
            and stage.selected is not None
            and stage.plan.pinned is None
        )
        if same_inspected:
            inspector.selected_target = (
                next(
                    (target for target in inspector.key_targets if target.path == selected_path),
                    None,
                )
                if selected_path is not None
                else None
            )
            inspector.scroll_to(x=inspector_scroll.x, y=inspector_scroll.y, animate=False)
        console.set_search(options)
        inspector.set_search(options)
        self._tree_job = None
        self._tree_result = stage.tree
        self._tree_generation = stage.plan.tree_generation
        self._tree_requested = False
        tree.clear_tree()
        self.tree_mode = stage.tree is not None
        tree.display, console.display = self.tree_mode, not self.tree_mode
        if stage.tree is not None:
            tree.bind_owner(stage.tree, stage.tree_initial_key, console.options)
            tree._revealed_ordinal = (
                stage.tree_revealed_record.ordinal
                if stage.tree_revealed_record is not None
                else None
            )
            tree.expanded_default = stage.plan.expanded_default
            tree._exceptions = stage.folds
            tree._exception_identities = stage.fold_identities
            tree._fold_bytes = sum(
                256 + len(identity.encode("utf-8")) * 4
                for identity in stage.fold_identities.values()
            )
            if stage.tree_focus_key is not None:
                tree.focused_key = stage.tree_focus_key
            if stage.tree_top_key is not None:
                tree._top = stage.tree_top_key
            tree._top_line = tree_line if stage.selected is not None else 0
            tree.scroll_to(x=tree_scroll, animate=False)
            self.tree_status = (
                "TREE · refreshed applied Main + ancestor context"
                if stage.main
                else "TREE · refreshed unfiltered"
            )
        else:
            self.tree_status = ""
        tree.set_search(options)
        if stage.console_anchor_position is not None:
            console._top = stage.console_anchor_position, console_line
            console.scroll_to(x=console_scroll, animate=False)
        self.discovery_job = stage.discovery_job
        for editor in (self.main_filter, self.aggregate_filter):
            editor.set_discovery(stage.discovery)
        self.aggregate_result = stage.aggregate
        self._aggregate_generation += 1
        pane = self.query_one(AggregatePane)
        if stage.aggregate is not None:
            mode = "follows Main" if self.aggregate_follows_main else "independent"
            editor = self.main_filter if self.aggregate_follows_main else self.aggregate_filter
            path = stage.plan.field
            assert path is not None
            metric_label = ", ".join(self.aggregate_metrics) if self.aggregate_metrics else "values"
            group_label = (
                f"group by {format_grouping(self.aggregate_grouping)} · "
                if self.aggregate_grouping
                else ""
            )
            label = (
                f"{format_field_path(path)} · {metric_label} · {group_label}"
                f"{mode}: {editor.applied_text or 'all records'}"
            )
            pane.begin(
                path,
                label,
                self._aggregate_generation,
                update_field=False,
                reveal=False,
                metrics=self.aggregate_metrics,
                grouping=self.aggregate_grouping,
            )
            pane.publish(stage.aggregate, label, self._aggregate_generation)
            aggregate_viewport.selected = min(
                aggregate_position[0], max(0, stage.aggregate.record_count - 1)
            )
            aggregate_viewport.top = min(
                aggregate_position[1], max(0, stage.aggregate.record_count - 1)
            )
            aggregate_viewport.scroll_to(x=aggregate_position[2], animate=False)
        else:
            pane.query_one(AggregateViewport).result = None
        if self.search.result is not None:
            self.search_bar.show_status(
                f"{self.search.result.record_count:,} matching records · "
                "refreshed applied Main scope"
            )
        elif main_pending is not None:
            self.search_bar.show_status("Main filter requeued · previous match scope invalid")
        else:
            self.search_bar.show_status("Empty")
        for editor, request in (
            (self.main_filter, main_pending),
            (self.aggregate_filter, detached_pending),
        ):
            if request is not None:
                self.on_filter_editor_apply_requested(FilterEditor.ApplyRequested(editor, *request))
        self._inspector_heading()
        self._origin_status(stage.resource_usage)
        self.query_one("#console-heading", Static).update(
            f"{'TREE' if self.tree_mode else 'CONSOLE'} · refreshed applied Main"
        )
        if focus is not None:
            focus.focus()
        return readers, handles

    def action_discovery(self) -> None:
        if self.discovery_job is not None and self.discovery_job.status.phase in (
            "pending",
            "building",
            "complete",
        ):
            return
        self.discovery_job = None
        self.refresh_discovery()

    def refresh_discovery(self) -> None:
        if not self.is_running:
            return
        editors = (self.main_filter, self.aggregate_filter)
        if self.discovery_job is None and self.session.status.complete:
            try:
                self.discovery_job = self.session.discover()
            except ToolError as error:
                for editor in editors:
                    editor.discovery_status = str(error)
                    editor.render_status()
                return
        job = self.discovery_job
        if job is None:
            status = "Dataset choices require complete capture"
        elif job.status.phase == "complete":
            status = "Whole dataset choices ready"
            index = job.result()
            for editor in editors:
                if editor.discovery_index is None:
                    editor.set_discovery(index)
        elif job.status.phase in ("failed", "canceled", "closed"):
            reason = job.status.diagnostic.message if job.status.diagnostic else job.status.phase
            status = "Discovery unavailable: " + reason
        else:
            status = (
                f"Discovering {job.status.processed_records:,}/{job.status.total_records:,} records"
            )
        for editor in editors:
            editor.discovery_status = status
            editor.render_status()

    @property
    def preferences(self) -> NativePreferences:
        """Current effective values, including keyboard presentation adjustments."""
        if not self.is_mounted:
            return self._preferences
        return replace(
            self._preferences,
            theme="dark" if self.current_theme.dark else "light",
            console=self.query_one(ConsoleViewport).options,
            json_line_numbers=self.query_one(JSONInspector).line_numbers,
            inspector_visible=self.inspector_visible,
            inspector_percent=self.inspector_percent,
            aggregate_visible=self.query_one(AggregatePane).display,
            limits=self.session.limits,
            cache_expiry_seconds=self.session.cache_store.expiry_seconds
            if self.session.cache_store
            else self._preferences.cache_expiry_seconds,
        )

    def apply_preferences(self, preferences: NativePreferences) -> None:
        """Validate resource changes before publishing any presentation change."""
        self.session.configure_resources(
            limits=preferences.limits, cache_expiry_seconds=preferences.cache_expiry_seconds
        )
        self._preferences = preferences
        self.theme = "textual-dark" if preferences.theme == "dark" else "textual-light"
        self.inspector_visible = preferences.inspector_visible
        self.inspector_percent = preferences.inspector_percent
        console = self.query_one(ConsoleViewport)
        console.set_options(preferences.console)
        tree = self.query_one(TreeViewport)
        tree.set_options(preferences.console)
        inspector = self.query_one(JSONInspector)
        if inspector.line_numbers != preferences.json_line_numbers:
            inspector.action_line_numbers()
        inspector.refresh()
        self.query_one(AggregatePane).display = preferences.aggregate_visible
        self._layout_inspector()
        self._origin_status()

    def action_settings(self, from_pane: bool = False) -> None:
        if not isinstance(self.screen, SettingsScreen):
            self.push_screen(SettingsScreen(self))

    def refresh_capture(self) -> None:
        if not self.is_running:
            return
        self.refresh_tree()
        status = self.session.status
        if status == self._capture_status:
            return
        became_complete = status.complete and not self._capture_status.complete
        self._capture_status = status
        if became_complete and self.search_bar.text:
            self.search.update()
        self.query_one("#heading", Static).update(
            visible_text(self.capture_heading(), multiline=True)
        )
        console = self.query_one(ConsoleViewport)
        console.capture_updated()
        if self.selected_identity is None and status.record_count:
            self.show_record(0)
        else:
            self._origin_status()

    @property
    def search_result(self) -> SearchResult | None:
        return self.search.result

    def action_focus_search(self, from_pane: bool = False) -> None:
        self.search_bar.query_one(Input).focus()

    def on_search_bar_changed(self) -> None:
        self.search.update()

    def on_search_bar_navigate(self, message: SearchBar.Navigate) -> None:
        self.search.navigate(message.previous)
        if self.search_bar.query_one(Input).has_focus:
            self.action_focus_console()

    def action_next_match(self, from_pane: bool = False) -> None:
        self.search.navigate()

    def action_previous_match(self, from_pane: bool = False) -> None:
        self.search.navigate(True)

    def action_focus_filter(self, from_pane: bool = False) -> None:
        self.main_filter.query_one(Input).focus()

    def on_filter_editor_apply_requested(self, message: FilterEditor.ApplyRequested) -> None:
        if message.binding != (self.session.owner_id, self._replacement_generation):
            return
        if message.editor is self.aggregate_filter:
            if not self.aggregate_follows_main:
                self._apply_detached_filter(message)
                if message.editor.query_one(Input).has_focus:
                    self.action_focus_counts()
            return
        if message.editor is not self.main_filter:
            return
        self.search.update("Main filter pending", blocked=True)
        self.main_filter.begin(message.text, message.generation)
        self._queued_filter = message
        if self.pending_filter is not None:
            self.pending_filter.cancel()
        self.refresh_filter()
        if message.editor.query_one(Input).has_focus:
            self.action_focus_console()

    def refresh_filter(self) -> None:
        if not self.is_running:
            return
        job = self.pending_filter
        if job is not None and job.done:
            view = job.wait(0)
            generation = job.scope.request_generation
            if (
                view is not None
                and job.session is self.session
                and self._queued_filter is None
                and self.main_filter.publish(self._filter_text, job.scope.expression, generation)
            ):
                previous = self.filtered_view
                self.filtered_view = view
                self.invalidate_tree()
                console = self.query_one(ConsoleViewport)
                console.set_view(view, self.selected_ordinal if self.selected_identity else None)
                if view.record_count:
                    page = console.page(console.selected, 1)
                    self.selected_position = console.selected
                    self.show_record(page.identities[0].ordinal)
                else:
                    self.selected_position = 0
                    self.selected_identity = None
                    self.selected_record = None
                    self.selected_origin = None
                    if self.pinned_identity is None:
                        self._show_selection()
                    self._origin_status()
                if self.aggregate_follows_main and self.requested_field is not None:
                    self.request_aggregate(
                        self.requested_field, update_field=False, reveal=False, infer_metrics=False
                    )
                if previous is not None:
                    self._retire_handle(previous)
            else:
                if view is not None:
                    self._retire_handle(view)
                reason = (
                    "Canceled"
                    if job.status.phase == "cancelled"
                    else (job.diagnostics[0].message if job.diagnostics else "Filter failed")
                )
                self.main_filter.fail(generation, reason)
            self.pending_filter = None
            if self._queued_filter is None:
                self.search.update()
        if self.pending_filter is None and self._queued_filter is not None:
            request = self._queued_filter
            self._queued_filter = None
            try:
                self.pending_filter = self.session.filter(
                    request.expression, request_generation=request.generation
                )
            except (ToolError, OSError) as error:
                self.main_filter.fail(request.generation, str(error))
                self.search.update()
            else:
                self._filter_text = request.text

    def action_cancel_capture(self) -> None:
        if self.refresh_controller.job is not None:
            self.refresh_controller.cancel()
            return
        self.search.cancel()
        if self.main_filter.pending_generation is not None:
            self.main_filter.fail(self.main_filter.pending_generation, "Canceled")
        self._queued_filter = None
        if self.pending_filter is not None:
            self.pending_filter.cancel()
        if self.aggregate_filter.pending_generation is not None:
            self.aggregate_filter.fail(self.aggregate_filter.pending_generation, "Canceled")
        self._queued_detached_filter = None
        self._aggregate_waiting_for_filter = False
        if self.pending_detached_filter is not None:
            self.pending_detached_filter.cancel()
        self._aggregate_generation += 1
        self._queued_aggregate = None
        if self.pending_aggregate is not None:
            self.pending_aggregate.cancel()
        pane = self.query_one(AggregatePane)
        if pane.pending_scope:
            pane.fail(pane.generation, "Canceled")
        self.session.cancel()
        if self.discovery_job is not None and self.discovery_job.status.phase in (
            "pending",
            "building",
        ):
            self.discovery_job.cancel()
        if self._tree_job is not None and self._tree_job.status.phase in ("pending", "building"):
            self._tree_requested = False
            self._tree_generation += 1
            self._tree_job.cancel()
            self.tree_status = "Tree canceled; console retained."
            self.query_one("#heading", Static).update(
                visible_text(self.capture_heading(), multiline=True)
            )

    def _stream_widget(self) -> ConsoleViewport | TreeViewport:
        return self.query_one(TreeViewport) if self.tree_mode else self.query_one(ConsoleViewport)

    @property
    def tree_input_scope(self) -> ViewScope:
        return (
            self.filtered_view.view_scope
            if self.filtered_view is not None
            else ViewScope(self.session.dataset_id, self.session.dataset_id)
        )

    def invalidate_tree(self) -> None:
        """Invalidate membership while preserving the user's desired representation."""
        wanted = self.tree_mode or self._tree_requested
        self._tree_generation += 1
        self._tree_requested = wanted
        if self._tree_job is not None and not self._tree_job.done:
            self._tree_job.cancel()
        previous = self._tree_result
        self._tree_result = None
        self.tree_mode = False
        viewport = self.query_one(TreeViewport)
        viewport.display = False
        viewport.clear_tree()
        self.query_one(ConsoleViewport).display = True
        if previous is not None:
            try:
                previous.close()
            except (ToolError, OSError) as error:
                self.notify(visible_text(f"Tree cleanup failed: {error}"), markup=False)

    def _start_tree(self) -> None:
        if self._tree_job is not None or self.main_filter.pending_generation is not None:
            return
        try:
            self._tree_job = self.session.build_tree(
                input_view=self.filtered_view, request_generation=self._tree_generation
            )
        except (ToolError, OSError) as error:
            self._tree_requested = False
            self.tree_status = str(error)
        else:
            self.tree_status = "Tree building · applied Main scope · Esc cancel"

    def action_tree(self) -> None:
        if self.tree_mode or self._tree_requested:
            self._tree_requested = False
            if self._tree_job is not None and not self._tree_job.done:
                self._tree_generation += 1
                self._tree_job.cancel()
            self.tree_mode = False
            self.query_one(TreeViewport).display = False
            console = self.query_one(ConsoleViewport)
            console.display = True
            position = (
                self.filtered_view.position_of(self.selected_ordinal)
                if self.filtered_view
                else self.selected_ordinal
            )
            if position is not None:
                console.select(position)
            self.on_console_viewport_options_changed(
                ConsoleViewport.OptionsChanged(console.options)
            )
            self.tree_status = ""
            self._stream_widget().focus()
        elif self.main_filter.pending_generation is not None:
            self.tree_status = "Tree unavailable while the Main filter is pending."
        elif self._tree_result is not None:
            self._show_tree()
        else:
            self._tree_requested = True
            self._start_tree()
        self.query_one("#heading", Static).update(
            visible_text(self.capture_heading(), multiline=True)
        )

    def refresh_tree(self) -> None:
        if not self.is_running:
            return
        job = self._tree_job
        if job is not None and job.done:
            self._tree_job = None
            current = (
                job.session is self.session
                and job.scope.request_generation == self._tree_generation
                and job.scope.input_scope == self.tree_input_scope
            )
            if job.status.phase == "complete" and current and self._tree_requested:
                self._tree_result = job.result()
                if self.main_filter.pending_generation is None:
                    self._show_tree()
            else:
                try:
                    job.close()
                except (ToolError, OSError) as error:
                    self.notify(visible_text(f"Tree cleanup failed: {error}"), markup=False)
                if current and self._tree_requested:
                    self._tree_requested = False
                    diagnostic = job.status.diagnostic
                    self.tree_status = (
                        f"Tree unavailable: {diagnostic.message if diagnostic else 'Canceled'}"
                    )
        if self._tree_requested and self._tree_job is None:
            if self._tree_result is not None and self.main_filter.pending_generation is None:
                self._show_tree()
            else:
                self._start_tree()
        job = self._tree_job
        if job is not None and self._tree_requested:
            self.tree_status = (
                f"Tree building · {job.status.processed_records:,}/{job.status.total_records:,} "
                "evidence records · applied Main scope · Esc cancel"
            )
        self.query_one("#heading", Static).update(
            visible_text(self.capture_heading(), multiline=True)
        )

    def _show_tree(self) -> None:
        assert self._tree_result is not None
        self._tree_requested = False
        self.tree_mode = True
        population = (
            "filtered + Ancestor context" if self.filtered_view is not None else "unfiltered"
        )
        self.tree_status = (
            f"TREE · {population} · ← collapse/parent · → expand/child · "
            "Space fold · Shift+Space all · Shift+←/→ pan"
        )
        self._narrow_inspector = False
        self._layout_inspector()
        console = self.query_one(ConsoleViewport)
        console.display = False
        viewport = self.query_one(TreeViewport)
        viewport.display = True
        viewport.set_tree(
            self._tree_result,
            self.selected_ordinal if self.selected_identity else None,
            console.options,
        )
        self.query_one("#console-heading", Static).update(f"TREE · {population}")
        viewport.focus()

    def on_tree_viewport_selected(self, message: TreeViewport.Selected) -> None:
        viewport = self.query_one(TreeViewport)
        if (
            not self.tree_mode
            or message.tree is not viewport.trace_tree
            or message.tree.session is not self.session
        ):
            return
        if (
            message.tree.scope.request_generation != self._tree_generation
            or message.tree.scope.input_scope != self.tree_input_scope
        ):
            return
        position = (
            self.filtered_view.position_of(message.ordinal)
            if self.filtered_view
            else message.ordinal
        )
        if position is not None:
            self.selected_position = position
            self.show_record(message.ordinal)

    def on_console_viewport_options_changed(self, message: ConsoleViewport.OptionsChanged) -> None:
        if not self._current_binding(message):
            return
        options = message.options
        self.query_one(TreeViewport).set_options(options)
        self.search.update()
        mode = "TREE" if self.tree_mode else "CONSOLE"
        self.query_one("#console-heading", Static).update(
            f"{mode} · {'wrap' if options.wrap else 'pan'} · {options.timestamp_mode} · "
            f"duration {'on' if options.show_duration else 'off'}"
        )

    def on_console_viewport_selected(self, message: ConsoleViewport.Selected) -> None:
        if self.tree_mode:
            return
        if (
            message.identity.owner_id != self.session.owner_id
            or message.view_scope != self.query_one(ConsoleViewport).view_scope
        ):
            return
        self.selected_position = message.position
        self.show_record(message.ordinal)

    def on_console_viewport_field_selected(self, message: ConsoleViewport.FieldSelected) -> None:
        if not self._current_binding(message):
            return
        self.query_one("#console-heading", Static).update(
            f"CONSOLE · field {format_field_path(message.path)}"
        )

    def on_console_viewport_field_requested(self, message: ConsoleViewport.FieldRequested) -> None:
        if (
            self._current_binding(message)
            and message.view_scope == self.query_one(ConsoleViewport).view_scope
        ):
            self.request_aggregate(message.path)

    def on_json_inspector_key_selected(self, message: JSONInspector.KeySelected) -> None:
        if not self._current_binding(message):
            return
        target = message.target
        self._inspector_heading()
        self.query_one("#inspector-status", Static).update(
            visible_text(target.guidance or target.label)
        )

    def on_json_inspector_field_requested(self, message: JSONInspector.FieldRequested) -> None:
        if not self._current_binding(message):
            return
        self.request_aggregate(message.path)

    def on_aggregate_pane_field_requested(self, message: AggregatePane.FieldRequested) -> None:
        if not self._current_binding(message):
            return
        if not message.infer_metrics and message.grouping is None:
            self.aggregate_metrics = message.metrics
        self.request_aggregate(
            message.path,
            infer_metrics=message.infer_metrics,
            update_field=message.infer_metrics,
            grouping=message.grouping,
        )
        if isinstance(self.focused, Input) and self.focused.id in (
            "aggregate-field",
            "aggregate-metrics",
            "aggregate-grouping",
        ):
            self.action_focus_counts()

    def on_aggregate_pane_detach_requested(self, message: AggregatePane.DetachRequested) -> None:
        if not self._current_binding(message):
            return
        self.action_focus_aggregate_filter()

    def on_aggregate_pane_reattach_requested(
        self, message: AggregatePane.ReattachRequested
    ) -> None:
        if not self._current_binding(message):
            return
        self.action_reattach_aggregate()

    def action_focus_aggregate_filter(self) -> None:
        self._narrow_inspector = False
        self._layout_inspector()
        pane = self.query_one(AggregatePane)
        pane.display = True
        if self.aggregate_follows_main:
            self.aggregate_follows_main = False
            pane.set_following(False)
            editor = self.aggregate_filter
            text = self.main_filter.applied_text
            expression = self.main_filter.applied_expression
            # This is a copy of applied Main, independent of its draft or pending job.
            editor.seed(text, expression)
            editor.generation += 1
            self._apply_detached_filter(
                FilterEditor.ApplyRequested(editor, text, expression, editor.generation)
            )
        self.aggregate_filter.query_one(Input).focus()

    def action_reattach_aggregate(self) -> None:
        if self.aggregate_follows_main:
            return
        self.aggregate_follows_main = True
        self._queued_detached_filter = None
        self._aggregate_waiting_for_filter = False
        if self.pending_detached_filter is not None:
            self.pending_detached_filter.cancel()
        editor = self.aggregate_filter
        if editor.pending_generation is not None:
            editor.fail(editor.pending_generation, "Reattached to Main")
        self.query_one(AggregatePane).set_following(True)
        if self.detached_view is not None:
            previous = self.detached_view
            self.detached_view = None
            self._retire_handle(previous)
        if self.requested_field is not None:
            self.request_aggregate(
                self.requested_field, update_field=False, reveal=False, infer_metrics=False
            )
        else:
            self._aggregate_generation += 1
        self.action_focus_counts()

    def _apply_detached_filter(self, request: FilterEditor.ApplyRequested) -> None:
        self.aggregate_filter.begin(request.text, request.generation)
        self._queued_detached_filter = request
        if self.pending_detached_filter is not None:
            self.pending_detached_filter.cancel()
        if self.requested_field is not None:
            self.request_aggregate(
                self.requested_field, update_field=False, reveal=False, infer_metrics=False
            )
        self.refresh_detached_filter()

    def refresh_detached_filter(self) -> None:
        if not self.is_running:
            return
        job = self.pending_detached_filter
        if job is not None and job.done:
            view = job.wait(0)
            generation = job.scope.request_generation
            if (
                view is not None
                and job.session is self.session
                and not self.aggregate_follows_main
                and self._queued_detached_filter is None
                and self.aggregate_filter.publish(
                    self._detached_filter_text, job.scope.expression, generation
                )
            ):
                previous = self.detached_view
                self.detached_view = view
                self.pending_detached_filter = None
                self._aggregate_waiting_for_filter = False
                if self.requested_field is not None:
                    self.request_aggregate(
                        self.requested_field, update_field=False, reveal=False, infer_metrics=False
                    )
                if previous is not None:
                    self._retire_handle(previous)
            else:
                if view is not None:
                    self._retire_handle(view)
                reason = (
                    "Canceled"
                    if job.status.phase == "cancelled"
                    else (job.diagnostics[0].message if job.diagnostics else "Filter failed")
                )
                self.aggregate_filter.fail(generation, reason)
                if not self.aggregate_follows_main and self._queued_detached_filter is None:
                    self._aggregate_waiting_for_filter = False
                    self.query_one(AggregatePane).fail(self._aggregate_generation, reason)
            self.pending_detached_filter = None
        if self.pending_detached_filter is None and self._queued_detached_filter is not None:
            request = self._queued_detached_filter
            self._queued_detached_filter = None
            try:
                self.pending_detached_filter = self.session.filter(
                    request.expression, request_generation=request.generation
                )
            except (ToolError, OSError) as error:
                self.aggregate_filter.fail(request.generation, str(error))
                self._aggregate_waiting_for_filter = False
                self.query_one(AggregatePane).fail(self._aggregate_generation, str(error))
            else:
                self._detached_filter_text = request.text

    def action_focus_grouping(self) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one("#aggregate-grouping", Input).focus()

    def action_focus_metrics(self, from_pane: bool = False) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one("#aggregate-metrics", Input).focus()

    def action_focus_aggregate(self, from_pane: bool = False) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one("#aggregate-field", Input).focus()

    def action_focus_counts(self) -> None:
        self._narrow_inspector = False
        self._layout_inspector()
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one(AggregateViewport).focus()

    def action_toggle_aggregate(self) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = not pane.display
        if not pane.display and isinstance(self.focused, (AggregateViewport, Input)):
            self.action_focus_console()

    def request_aggregate(
        self,
        path: tuple[str, ...],
        *,
        update_field: bool = True,
        reveal: bool = True,
        infer_metrics: bool = True,
        grouping: tuple[GroupBinding, ...] | None = None,
    ) -> None:
        if grouping is not None:
            self.aggregate_grouping = grouping
        self.requested_field = path
        if infer_metrics:
            record = (
                self.inspected_record
                if self.query_one(JSONInspector).has_focus
                else self.selected_record
            )
            value = FieldBinding(path).resolve(record or {})
            self.aggregate_metrics = (
                ("count", "sum", "mean", "min", "max")
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None
            )
        self._aggregate_generation += 1
        metric_label = ", ".join(self.aggregate_metrics) if self.aggregate_metrics else "values"
        editor = self.main_filter if self.aggregate_follows_main else self.aggregate_filter
        self._aggregate_waiting_for_filter = not self.aggregate_follows_main and (
            self.pending_detached_filter is not None or self._queued_detached_filter is not None
        )
        scope_text = (
            editor.pending_text if self._aggregate_waiting_for_filter else editor.applied_text
        )
        mode = "follows Main" if self.aggregate_follows_main else "independent"
        group_label = (
            f"group by {format_grouping(self.aggregate_grouping)} · "
            if self.aggregate_grouping
            else ""
        )
        label = (
            f"{format_field_path(path)} · {metric_label} · {group_label}"
            f"{mode}: {scope_text or 'all records'}"
        )
        self.query_one(AggregatePane).begin(
            path,
            label,
            self._aggregate_generation,
            update_field=update_field,
            reveal=reveal,
            metrics=self.aggregate_metrics,
            grouping=self.aggregate_grouping,
        )
        self._queued_aggregate = AggregateRequest(
            path,
            self._aggregate_generation,
            label,
            self.filtered_view if self.aggregate_follows_main else self.detached_view,
            self.aggregate_metrics,
            self.aggregate_grouping,
        )
        if self._aggregate_waiting_for_filter:
            self._queued_aggregate = None
        if self.pending_aggregate is not None:
            self.pending_aggregate.cancel()
        if (
            not self.aggregate_follows_main
            and self.detached_view is None
            and not self._aggregate_waiting_for_filter
        ):
            self._queued_aggregate = None
            self.query_one(AggregatePane).fail(
                self._aggregate_generation,
                "Independent filter has no successful scope; apply a valid draft",
            )
        self.refresh_aggregate()

    def refresh_aggregate(self) -> None:
        if not self.is_running:
            return
        job = self.pending_aggregate
        pane = self.query_one(AggregatePane)
        if job is not None and job.done:
            result = job.wait(0)
            generation = job.scope.request_generation
            if (
                result is not None
                and job.session is self.session
                and not self._aggregate_waiting_for_filter
                and self._queued_aggregate is None
                and generation == self._aggregate_generation
                and pane.publish(result, self._aggregate_label, generation)
            ):
                previous = self.aggregate_result
                self.aggregate_result = result
                if previous is not None:
                    self._retire_handle(previous)
            else:
                if result is not None:
                    self._retire_handle(result)
                reason = (
                    "Canceled"
                    if job.status.phase == "cancelled"
                    else (job.diagnostics[0].message if job.diagnostics else "Aggregate failed")
                )
                pane.fail(generation, reason)
            self.pending_aggregate = None
        if self.pending_aggregate is None and self._queued_aggregate is not None:
            request = self._queued_aggregate
            self._queued_aggregate = None
            try:
                if request.metrics is None:
                    self.pending_aggregate = self.session.count_values(
                        request.path,
                        grouping=request.grouping,
                        input_view=request.input_view,
                        request_generation=request.generation,
                    )
                else:
                    self.pending_aggregate = self.session.summarize_values(
                        request.path,
                        metrics=request.metrics,
                        grouping=request.grouping,
                        input_view=request.input_view,
                        request_generation=request.generation,
                    )
            except (ToolError, OSError, ValueError) as error:
                pane.fail(request.generation, str(error))
            else:
                self._aggregate_label = request.label

    def on_unmount(self) -> None:
        self.refresh_controller.close()
        self._queued_detached_filter = None
        if self.pending_detached_filter is not None:
            self.pending_detached_filter.cancel()
        if self.detached_view is not None:
            previous = self.detached_view
            self.detached_view = None
            self._retire_handle(previous, report=False)

        for handle in tuple(self._retired_handles):
            self._retire_handle(handle, report=False)

    def _layout_inspector(self, width: int | None = None) -> None:
        narrow = (self.size.width if width is None else width) < 90
        pane = self.query_one("#inspector")
        show = self.inspector_visible and (not narrow or self._narrow_inspector)
        pane.display = show
        pane.styles.width = "1fr" if narrow else f"{self.inspector_percent}%"
        pane.styles.min_width = 1 if narrow else 25
        self.query_one("#stream").display = not (narrow and show)
        if not show and self.focused is self.query_one(JSONInspector):
            self._stream_widget().focus()

    def on_resize(self, event: events.Resize) -> None:
        if self.query("#inspector"):
            self._narrow_inspector = False
            self._layout_inspector(event.size.width)

    def action_inspector(self) -> None:
        self.inspector_visible = not self.query_one("#inspector").display
        self._narrow_inspector = self.inspector_visible and self.size.width < 90
        self._layout_inspector()
        if self._narrow_inspector:
            self.query_one(JSONInspector).focus()

    def action_inspector_width(self, delta: int) -> None:
        self.inspector_percent = min(max(self.inspector_percent + delta, 20), 60)
        self._layout_inspector()

    def action_focus_inspector(self) -> None:
        self.inspector_visible = True
        self._narrow_inspector = self.size.width < 90
        self._layout_inspector()
        self.query_one(JSONInspector).focus()

    def action_focus_console(self) -> None:
        self._narrow_inspector = False
        self._layout_inspector()
        self._stream_widget().focus()

    def _cycle_panes(self, direction: int) -> None:
        panes: list[ConsoleViewport | TreeViewport | JSONInspector | AggregateViewport] = [
            self._stream_widget()
        ]
        if self.inspector_visible:
            panes.append(self.query_one(JSONInspector))
        if self.query_one(AggregatePane).display:
            panes.append(self.query_one(AggregateViewport))
        target = (
            panes[(panes.index(self.focused) + direction) % len(panes)]
            if self.focused in panes
            else panes[0 if direction > 0 else -1]
        )
        if isinstance(target, JSONInspector):
            self.action_focus_inspector()
        elif isinstance(target, AggregateViewport):
            self.action_focus_counts()
        else:
            self.action_focus_console()

    def action_next_pane(self, from_editor: bool = False) -> None:
        self._cycle_panes(1)

    def action_previous_pane(self, from_editor: bool = False) -> None:
        self._cycle_panes(-1)

    def _inspector_heading(self) -> None:
        state = "parsed record" if self.inspected_record is not None else "no record selected"
        pin = " · pinned" if self.pinned_identity else ""
        self.query_one("#inspector-heading", Static).update(f"JSON · {state}{pin}")

    def _show_selection(self) -> None:
        self.inspected_record = self.selected_record
        self.inspected_identity = self.selected_identity
        self.inspected_origin = self.selected_origin
        self.query_one(JSONInspector).set_record(self.inspected_record)
        self.query_one("#inspector-status", Static).update("Complete JSON")
        self._inspector_heading()

    def _origin_status(self, usage=None) -> None:
        def describe(
            label: str, identity: RecordIdentity | None, origin: SourceOrigin | None
        ) -> str:
            if identity is None or origin is None:
                return f"{label}: no record"
            view_count = self.query_one(ConsoleViewport).record_count
            return (
                f"{label} {self.selected_position + 1}/{view_count} · "
                f"dataset {identity.ordinal + 1}/{self.session.status.record_count} · input "
                if label == "Selected" and self.filtered_view is not None
                else f"{label} {identity.ordinal + 1}/{self.session.status.record_count} · input "
            ) + f"{identity.input_occurrence + 1} · {Path(origin.source).name}:{origin.position}"

        lines = [
            f"Focus: {self._focus_name()} · "
            + describe("Selected", self.selected_identity, self.selected_origin)
        ]
        if self.pinned_identity:
            lines.append(describe("Pinned", self.inspected_identity, self.inspected_origin))
        if usage is None:
            usage = self.session.resources
        lines.append(
            f"Disk {usage.disk_bytes:,} bytes · "
            f"Reserved {usage.reserved_disk_bytes + usage.catalog_reserve_bytes:,} bytes · "
            f"Budget {self.session.limits.disk_bytes:,} bytes · "
            f"RAM browsing cache {usage.ram_cache_bytes:,} bytes"
        )
        self.query_one("#origin", Static).update(visible_text("\n".join(lines), multiline=True))

    def action_copy_record(self) -> None:
        document = self.query_one(JSONInspector).document
        if not document:
            self.copy_status = "Copy unavailable: no record selected."
        elif self._clipboard_writer is None and (
            self.is_headless or os.environ.get("TERM_PROGRAM") == "Apple_Terminal"
        ):
            self.copy_status = (
                "Copy unavailable: this transport has no supported terminal clipboard."
            )
        else:
            try:
                writer = self._clipboard_writer or self.copy_to_clipboard
                writer(document)
            except OSError as error:
                self.copy_status = f"Copy unavailable: terminal transport failed ({error})."
            else:
                self.copy_status = (
                    "Complete JSON sent via OSC 52; terminal acceptance is unverified."
                )
        self.query_one("#inspector-status", Static).update(visible_text(self.copy_status))
        self.notify(visible_text(self.copy_status), markup=False)

    def action_pin(self) -> None:
        if self.pinned_identity is None:
            self.pinned_identity = self.inspected_identity
        else:
            self.pinned_identity = None
            self._show_selection()
        self._inspector_heading()
        self._origin_status()

    def show_record(self, ordinal: int) -> None:
        page = self.session.page(ordinal, 1)
        if not page.records:
            return
        self.selected_ordinal = ordinal
        self.selected_identity = page.identities[0]
        self.selected_record = page.records[0]
        self.selected_origin = page.origins[0]
        if self.pinned_identity is None:
            self._show_selection()
        self._origin_status()
