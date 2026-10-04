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

from ..core.runtime import SourceOrigin
from ..errors import ToolError
from ..investigation import FilterJob, Investigation, RecordIdentity, RecordView
from ..investigation.tree import TraceTree, TreeJob
from .console import ConsoleViewport
from .filter_editor import FilterEditor
from .inspector import JSONInspector
from .tree import TreeViewport


class InvestigationApp(App[None]):
    """Native consumer of a progressively published captured prefix."""

    TITLE = "slogger investigation"
    BINDINGS = [
        Binding("b", "tree", "Flat / tree"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "cancel_capture", "Cancel work"),
        Binding("tab", "next_pane", "Next pane", priority=True),
        Binding("shift+tab", "next_pane", "Previous pane", show=False, priority=True),
        Binding("i", "inspector", "JSON"),
        Binding("[", "inspector_width(-5)", "Narrower", show=False),
        Binding("]", "inspector_width(5)", "Wider", show=False),
        Binding("f2", "focus_inspector", "Focus JSON"),
        Binding("f3", "focus_console", "Focus console"),
        Binding("f4", "focus_filter", "Main filter"),
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
        if status.phase == "verifying":
            progress = f"{status.verified_bytes:,}/{status.total_bytes:,} bytes verified"
        text = (
            f"CONSOLE · {status.record_count:,} records · {state} · {progress} · "
            f"{status.skipped_lines:,} skipped lines\n"
            "↑↓ select · PgUp/PgDn page · Home/End · ←→ pan · "
            "W wrap · T time · D duration · Tab panes · Esc cancel loading\n"
            "B flat/tree · I JSON · [/] resize · P pin · C copy · F2/F3 focus · Ctrl+P keys"
        )
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
            "Edit Main filter", "F4 · Infix IXR; Enter applies", self.action_focus_filter
        )
        yield SystemCommand(
            "Cancel filter/loading", "Escape · Keep the successful view", self.action_cancel_capture
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
        if action == "next_pane":
            return isinstance(self.focused, (ConsoleViewport, JSONInspector, TreeViewport))
        return super().check_action(action, parameters)

    def on_mount(self) -> None:
        self.show_record(0)
        self._layout_inspector()
        self.set_interval(0.1, self.refresh_capture)
        self.set_interval(0.05, self.refresh_filter)

    def refresh_capture(self) -> None:
        self.refresh_tree()
        status = self.session.status
        if status == self._capture_status:
            return
        self._capture_status = status
        self.query_one("#heading", Static).update(self.capture_heading())
        console = self.query_one(ConsoleViewport)
        console.capture_updated()
        if self.selected_identity is None and status.record_count:
            self.show_record(0)
        else:
            self._origin_status()

    def action_focus_filter(self) -> None:
        self.main_filter.query_one(Input).focus()

    def on_filter_editor_apply_requested(self, message: FilterEditor.ApplyRequested) -> None:
        if message.editor is not self.main_filter:
            return
        if self.tree_mode or self._tree_requested:
            self.action_tree()
        self.main_filter.begin(message.text, message.generation)
        self._queued_filter = message
        if self.pending_filter is not None:
            self.pending_filter.cancel()
        self.refresh_filter()

    def refresh_filter(self) -> None:
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
        if self.pending_filter is None and self._queued_filter is not None:
            request = self._queued_filter
            self._queued_filter = None
            try:
                self.pending_filter = self.session.filter(
                    request.expression, request_generation=request.generation
                )
            except (ToolError, OSError) as error:
                self.main_filter.fail(request.generation, str(error))
            else:
                self._filter_text = request.text

    def action_cancel_capture(self) -> None:
        if self.main_filter.pending_generation is not None:
            self.main_filter.fail(self.main_filter.pending_generation, "Canceled")
        self._queued_filter = None
        if self.pending_filter is not None:
            self.pending_filter.cancel()
        self.session.cancel()
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
            if self.filtered_view is not None:
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

    def on_json_inspector_key_selected(self, message: JSONInspector.KeySelected) -> None:
        target = message.target
        self._inspector_heading()
        self.query_one("#inspector-status", Static).update(target.guidance or target.label)

    def on_json_inspector_field_requested(self, message: JSONInspector.FieldRequested) -> None:
        self.requested_field = message.path

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

    def action_next_pane(self) -> None:
        if self.focused is self.query_one(JSONInspector):
            self.action_focus_console()
        else:
            self.action_focus_inspector()

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
        lines.append(
            f"Disk {self.session.resources.disk_bytes:,} bytes · "
            f"RAM browsing cache {self.session.resources.ram_cache_bytes:,} bytes"
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
