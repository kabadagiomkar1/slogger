"""Optional native split view. Shared Investigation operations stay headless."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from ..core.bindings import FieldBinding
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
from ..investigation.search import SearchResult
from ..investigation.tree import TraceTree, TreeJob
from .aggregates import AggregatePane, AggregateViewport
from .console import ConsoleViewport
from .filter_editor import FilterEditor
from .inspector import JSONInspector
from .search import SearchBar, SearchController
from .tree import TreeViewport


class InvestigationApp(App[None]):
    """Native consumer of a progressively published captured prefix."""

    TITLE = "slogger investigation"
    BINDINGS = [
        Binding("b", "tree", "Flat / tree"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "cancel_capture", "Cancel work"),
        Binding("tab", "next_pane", "Next pane", priority=True),
        Binding("shift+tab", "previous_pane", "Previous pane", show=False, priority=True),
        Binding("i", "inspector", "JSON"),
        Binding("[", "inspector_width(-5)", "Narrower", show=False),
        Binding("]", "inspector_width(5)", "Wider", show=False),
        Binding("f2", "focus_inspector", "Focus JSON"),
        Binding("f3", "focus_console", "Focus console"),
        Binding("f4", "focus_filter", "Main filter"),
        Binding("f5", "focus_aggregate", "Field aggregate"),
        Binding("f6", "focus_counts", "Focus aggregate"),
        Binding("f7", "focus_search", "Search"),
        Binding("f8", "next_match", "Next match", show=False),
        Binding("shift+f8", "previous_match", "Previous match", show=False),
        Binding("f9", "focus_metrics", "Metrics", show=False),
        Binding("ctrl+a", "toggle_aggregate", "Aggregate pane", show=False),
        Binding("ctrl+j", "focus_inspector", "Focus JSON", show=False),
        Binding("ctrl+k", "focus_console", "Focus console", show=False),
        Binding("p", "pin", "Pin JSON"),
        Binding("c", "copy_record", "Copy JSON"),
    ]
    CSS = """
    Screen { background: $background; }
    #heading { height: auto; min-height: 2; max-height: 6; padding: 0 1; color: $text-muted; }
    #split { height: 1fr; }
    #stream { width: 1fr; }
    #inspector { width: 33%; min-width: 25; border-left: solid $primary-muted; }
    .pane-heading { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #console, #json, #tree { height: 1fr; }
    #inspector-status { height: auto; max-height: 3; padding: 0 1; color: $text-muted; }
    #origin { height: auto; max-height: 6; padding: 0 1; color: $text-muted; }
    """

    def __init__(
        self, session: Investigation, *, clipboard_writer: Callable[[str], None] | None = None
    ) -> None:
        super().__init__()
        self.session = session
        self._clipboard_writer = clipboard_writer
        self.copy_status = ""
        self.inspector_visible = True
        self.inspector_percent = 33
        self._narrow_inspector = False
        self.selected_ordinal = 0
        self.selected_position = 0
        self.main_filter = FilterEditor()
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
        self.aggregate_result: AggregateResult | None = None
        self.pending_aggregate: AggregateJob | None = None
        self._aggregate_generation = 0
        self._aggregate_label = ""
        self._queued_aggregate: (
            tuple[tuple[str, ...], int, str, RecordView | None, tuple[str, ...] | None] | None
        ) = None
        self._capture_status = session.status
        self.tree_mode = False
        self.tree_status = ""
        self._tree_requested = False
        self._tree_job: TreeJob | None = None
        self._tree_result: TraceTree | None = None

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(self.capture_heading(), id="heading", markup=False)
        yield self.main_filter
        yield self.search_bar
        with Horizontal(id="split"):
            with Vertical(id="stream"):
                yield Static(
                    "CONSOLE · pan · time · duration off",
                    id="console-heading",
                    classes="pane-heading",
                )
                yield ConsoleViewport(self.session)
                tree = TreeViewport()
                tree.display = False
                yield tree
                yield AggregatePane()
            with Vertical(id="inspector"):
                yield Static(
                    "JSON · parsed record" if status.record_count else "JSON · no record selected",
                    classes="pane-heading",
                    id="inspector-heading",
                    markup=False,
                )
                yield Static(
                    "j/k keys · Enter field · L lines", id="inspector-status", markup=False
                )
                yield JSONInspector()
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
            f"CONSOLE · {status.record_count:,} records · {state} · {progress} · "
            f"{status.skipped_lines:,} skipped lines\n"
            "↑↓ select · PgUp/PgDn page · Home/End · ←→ pan · "
            "W wrap · T time · D duration · Tab panes · Esc cancel loading\n"
            "B flat/tree · I JSON · [/] resize · P pin · C copy · F2/F3 focus · Ctrl+P keys"
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
        return text

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Flat / tree", "B · Explore complete unfiltered traces", self.action_tree
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
            "F7 · Literal text; Enter next, Shift+Enter previous",
            self.action_focus_search,
        )
        yield SystemCommand(
            "Next search match", "F8 · Navigate complete matching records", self.action_next_match
        )
        yield SystemCommand(
            "Previous search match", "Shift+F8 · Navigate backward", self.action_previous_match
        )
        yield SystemCommand(
            "Edit Main filter", "F4 · Infix IXR; Enter applies", self.action_focus_filter
        )
        yield SystemCommand(
            "Cancel filter/loading", "Escape · Keep the successful view", self.action_cancel_capture
        )
        yield SystemCommand(
            "Summarize selected field",
            "F5 · Exact values following Main",
            self.action_focus_aggregate,
        )
        yield SystemCommand("Focus aggregate", "F6 · Browse every group", self.action_focus_counts)
        yield SystemCommand(
            "Toggle aggregate pane", "Ctrl+A · Show / hide lower pane", self.action_toggle_aggregate
        )
        yield SystemCommand(
            "Edit aggregate metrics", "F9 · Values or numeric metrics", self.action_focus_metrics
        )
        yield SystemCommand("Toggle JSON", "I · Hide or show the inspector", self.action_inspector)
        yield SystemCommand(
            "Focus JSON", "F2 · Inspect JSON, including narrow screens", self.action_focus_inspector
        )
        yield SystemCommand("Focus console", "F3 · Return to the stream", self.action_focus_console)
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
        if action in ("next_pane", "previous_pane"):
            return isinstance(
                self.focused, (ConsoleViewport, JSONInspector, TreeViewport, AggregateViewport)
            )
        return super().check_action(action, parameters)

    def on_mount(self) -> None:
        self.show_record(0)
        self._layout_inspector()
        self.set_interval(0.1, self.refresh_capture)
        self.set_interval(0.05, self.refresh_filter)
        self.set_interval(0.05, self.search.refresh)
        self.set_interval(0.05, self.refresh_aggregate)
        self.set_interval(0.1, self.refresh_discovery)
        self.refresh_discovery()

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
        if self.discovery_job is None and self.session.status.complete:
            try:
                self.discovery_job = self.session.discover()
            except ToolError as error:
                self.main_filter.discovery_status = str(error)
                return
        job = self.discovery_job
        if job is None:
            self.main_filter.discovery_status = "Dataset choices require complete capture"
        elif job.status.phase == "complete":
            if self.main_filter.discovery_index is None:
                self.main_filter.discovery_status = "Whole dataset choices ready"
                self.main_filter.set_discovery(job.result())
        elif job.status.phase in ("failed", "canceled", "closed"):
            reason = job.status.diagnostic.message if job.status.diagnostic else job.status.phase
            self.main_filter.discovery_status = "Discovery unavailable: " + reason
        else:
            self.main_filter.discovery_status = (
                f"Discovering {job.status.processed_records:,}/{job.status.total_records:,} records"
            )
        self.main_filter.render_status()

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
        self.query_one("#heading", Static).update(self.capture_heading())
        console = self.query_one(ConsoleViewport)
        console.capture_updated()
        if self.selected_identity is None and status.record_count:
            self.show_record(0)
        else:
            self._origin_status()

    @property
    def search_result(self) -> SearchResult | None:
        return self.search.result

    def action_focus_search(self) -> None:
        self.search_bar.query_one(Input).focus()

    def on_search_bar_changed(self) -> None:
        self.search.update()

    def on_search_bar_navigate(self, message: SearchBar.Navigate) -> None:
        self.search.navigate(message.previous)

    def action_next_match(self) -> None:
        self.search.navigate()

    def action_previous_match(self) -> None:
        self.search.navigate(True)

    def action_focus_filter(self) -> None:
        self.main_filter.query_one(Input).focus()

    def on_filter_editor_apply_requested(self, message: FilterEditor.ApplyRequested) -> None:
        if message.editor is not self.main_filter:
            return
        if self.tree_mode or self._tree_requested:
            self.action_tree()
        self.search.update("Main filter pending", blocked=True)
        self.main_filter.begin(message.text, message.generation)
        self._queued_filter = message
        if self.pending_filter is not None:
            self.pending_filter.cancel()
        self.refresh_filter()

    def refresh_filter(self) -> None:
        if not self.is_running:
            return
        job = self.pending_filter
        if job is not None and job.done:
            view = job.wait(0)
            generation = job.scope.request_generation
            if (
                view is not None
                and self._queued_filter is None
                and self.main_filter.publish(self._filter_text, job.scope.expression, generation)
            ):
                previous = self.filtered_view
                self.filtered_view = view
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
                if self.requested_field is not None:
                    self.request_aggregate(
                        self.requested_field, update_field=False, reveal=False, infer_metrics=False
                    )
                if previous is not None:
                    previous.close()
            else:
                if view is not None:
                    view.close()
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
        self.search.cancel()
        if self.main_filter.pending_generation is not None:
            self.main_filter.fail(self.main_filter.pending_generation, "Canceled")
        self._queued_filter = None
        if self.pending_filter is not None:
            self.pending_filter.cancel()
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
            self._tree_job.cancel()
            self.tree_status = "Tree canceled; console retained."
            self.query_one("#heading", Static).update(self.capture_heading())

    def _stream_widget(self) -> ConsoleViewport | TreeViewport:
        return self.query_one(TreeViewport) if self.tree_mode else self.query_one(ConsoleViewport)

    def action_tree(self) -> None:
        if self.tree_mode or self._tree_requested:
            self._tree_requested = False
            if self._tree_job is not None and self._tree_job.status.phase in (
                "pending",
                "building",
            ):
                self._tree_job.cancel()
            self.tree_mode = False
            self.query_one(TreeViewport).display = False
            console = self.query_one(ConsoleViewport)
            console.display = True
            console.select(self.selected_ordinal)
            self.on_console_viewport_options_changed(
                ConsoleViewport.OptionsChanged(console.options)
            )
            self.tree_status = ""
            self._stream_widget().focus()
        else:
            if self.search_bar.text:
                self.tree_status = (
                    "Tree search unavailable until ancestor reveal is implemented; "
                    "clear search or use flat view."
                )
            elif self.filtered_view is not None:
                self.tree_status = (
                    "Tree unavailable for an applied filter until ancestor context is implemented."
                )
            elif self.pending_filter is not None or self._queued_filter is not None:
                self.tree_status = "Tree unavailable while the Main filter is pending."
            elif self._tree_result is not None:
                self._show_tree()
            else:
                try:
                    self._tree_job = self.session.build_tree()
                except ToolError as error:
                    self.tree_status = str(error)
                else:
                    self._tree_requested = True
                    self.tree_status = "Tree building · complete unfiltered dataset · Esc cancel"
        self.query_one("#heading", Static).update(self.capture_heading())

    def refresh_tree(self) -> None:
        if not self.is_running:
            return
        job = self._tree_job
        if job is None or not self._tree_requested:
            return
        if job.status.phase == "complete":
            result = job.result()
            if result.scope.dataset_id == self.session.dataset_id:
                self._tree_result = result
                self._show_tree()
        elif job.status.phase in ("failed", "canceled", "closed"):
            self._tree_requested = False
            diagnostic = job.status.diagnostic
            self.tree_status = (
                f"Tree {job.status.phase}: {diagnostic.message if diagnostic else ''}"
            )
        else:
            self.tree_status = (
                f"Tree building · {job.status.processed_records:,}/"
                f"{job.status.total_records:,} records · Esc cancel"
            )
        self.query_one("#heading", Static).update(self.capture_heading())

    def _show_tree(self) -> None:
        assert self._tree_result is not None
        self._tree_requested = False
        self.tree_mode = True
        self.tree_status = (
            "TREE · unfiltered · ← collapse/parent · → expand/child · "
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
        self.query_one("#console-heading", Static).update(
            "TREE · complete unfiltered source evidence"
        )
        viewport.focus()

    def on_tree_viewport_selected(self, message: TreeViewport.Selected) -> None:
        if self.tree_mode:
            self.selected_position = message.ordinal
            self.show_record(message.ordinal)

    def on_console_viewport_options_changed(self, message: ConsoleViewport.OptionsChanged) -> None:
        options = message.options
        self.search.update()
        self.query_one("#console-heading", Static).update(
            f"CONSOLE · {'wrap' if options.wrap else 'pan'} · {options.timestamp_mode} · "
            f"duration {'on' if options.show_duration else 'off'}"
        )

    def on_console_viewport_selected(self, message: ConsoleViewport.Selected) -> None:
        if self.tree_mode:
            return
        if message.view_scope != self.query_one(ConsoleViewport).view_scope:
            return
        self.selected_position = message.position
        self.show_record(message.ordinal)

    def on_console_viewport_field_selected(self, message: ConsoleViewport.FieldSelected) -> None:
        self.query_one("#console-heading", Static).update(
            f"CONSOLE · field {format_field_path(message.path)} · Alt+←/→ fields · Enter counts"
        )

    def on_console_viewport_field_requested(self, message: ConsoleViewport.FieldRequested) -> None:
        if message.view_scope == self.query_one(ConsoleViewport).view_scope:
            self.request_aggregate(message.path)

    def on_json_inspector_key_selected(self, message: JSONInspector.KeySelected) -> None:
        target = message.target
        self._inspector_heading()
        self.query_one("#inspector-status", Static).update(target.guidance or target.label)

    def on_json_inspector_field_requested(self, message: JSONInspector.FieldRequested) -> None:
        self.request_aggregate(message.path)

    def on_aggregate_pane_field_requested(self, message: AggregatePane.FieldRequested) -> None:
        if not message.infer_metrics:
            self.aggregate_metrics = message.metrics
        self.request_aggregate(
            message.path, infer_metrics=message.infer_metrics, update_field=message.infer_metrics
        )

    def action_focus_metrics(self) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one("#aggregate-metrics", Input).focus()

    def action_focus_aggregate(self) -> None:
        pane = self.query_one(AggregatePane)
        pane.display = True
        pane.query_one(Input).focus()

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
    ) -> None:
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
        label = (
            f"{format_field_path(path)} · {metric_label} · follows Main: "
            f"{self.main_filter.applied_text or 'all records'}"
        )
        self.query_one(AggregatePane).begin(
            path,
            label,
            self._aggregate_generation,
            update_field=update_field,
            reveal=reveal,
            metrics=self.aggregate_metrics,
        )
        self._queued_aggregate = (
            path,
            self._aggregate_generation,
            label,
            self.filtered_view,
            self.aggregate_metrics,
        )
        if self.pending_aggregate is not None:
            self.pending_aggregate.cancel()
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
                and self._queued_aggregate is None
                and generation == self._aggregate_generation
                and pane.publish(result, self._aggregate_label, generation)
            ):
                previous = self.aggregate_result
                self.aggregate_result = result
                if previous is not None:
                    previous.close()
            else:
                if result is not None:
                    result.close()
                reason = (
                    "Canceled"
                    if job.status.phase == "cancelled"
                    else (job.diagnostics[0].message if job.diagnostics else "Aggregate failed")
                )
                pane.fail(generation, reason)
            self.pending_aggregate = None
        if self.pending_aggregate is None and self._queued_aggregate is not None:
            path, generation, label, input_view, metrics = self._queued_aggregate
            self._queued_aggregate = None
            try:
                if metrics is None:
                    self.pending_aggregate = self.session.count_values(
                        path, input_view=input_view, request_generation=generation
                    )
                else:
                    self.pending_aggregate = self.session.summarize_values(
                        path, metrics=metrics, input_view=input_view, request_generation=generation
                    )
            except (ToolError, OSError, ValueError) as error:
                pane.fail(generation, str(error))
            else:
                self._aggregate_label = label

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
            self._stream_widget(),
            self.query_one(JSONInspector),
        ]
        if self.query_one(AggregatePane).display:
            panes.append(self.query_one(AggregateViewport))
        current = panes.index(self.focused) if self.focused in panes else 0
        target = panes[(current + direction) % len(panes)]
        if isinstance(target, JSONInspector):
            self.action_focus_inspector()
        elif isinstance(target, AggregateViewport):
            self.action_focus_counts()
        else:
            self.action_focus_console()

    def action_next_pane(self) -> None:
        self._cycle_panes(1)

    def action_previous_pane(self) -> None:
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
        self.query_one("#inspector-status", Static).update("j/k keys · Enter field · L lines")
        self._inspector_heading()

    def _origin_status(self) -> None:
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

        lines = [describe("Selected", self.selected_identity, self.selected_origin)]
        if self.pinned_identity:
            lines.append(describe("Pinned", self.inspected_identity, self.inspected_origin))
        usage = self.session.resources
        lines.append(
            f"Disk {usage.disk_bytes:,} bytes · "
            f"Reserved {usage.reserved_disk_bytes + usage.catalog_reserve_bytes:,} bytes · "
            f"Budget {self.session.limits.disk_bytes:,} bytes · "
            f"RAM browsing cache {usage.ram_cache_bytes:,} bytes"
        )
        self.query_one("#origin", Static).update("\n".join(lines))

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
        self.query_one("#inspector-status", Static).update(self.copy_status)
        self.notify(self.copy_status, markup=False)

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
