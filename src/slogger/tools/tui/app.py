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
from textual.widgets import Footer, Static

from ..core.runtime import SourceOrigin
from ..investigation import Investigation, RecordIdentity
from .console import ConsoleViewport
from .inspector import JSONInspector


class InvestigationApp(App[None]):
    """Initial native consumer, usable after synchronous capture completes."""

    TITLE = "slogger investigation"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("tab", "next_pane", "Next pane", priority=True),
        Binding("shift+tab", "next_pane", "Previous pane", show=False, priority=True),
        Binding("i", "inspector", "JSON"),
        Binding("[", "inspector_width(-5)", "Narrower", show=False),
        Binding("]", "inspector_width(5)", "Wider", show=False),
        Binding("f2", "focus_inspector", "Focus JSON"),
        Binding("f3", "focus_console", "Focus console"),
        Binding("ctrl+j", "focus_inspector", "Focus JSON", show=False),
        Binding("ctrl+k", "focus_console", "Focus console", show=False),
        Binding("p", "pin", "Pin JSON"),
        Binding("c", "copy_record", "Copy JSON"),
    ]
    CSS = """
    Screen { background: $background; }
    #heading { height: auto; max-height: 3; padding: 0 1; color: $text-muted; }
    #split { height: 1fr; }
    #stream { width: 1fr; }
    #inspector { width: 33%; min-width: 25; border-left: solid $primary-muted; }
    .pane-heading { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #console, #json { height: 1fr; }
    #inspector-status { height: auto; max-height: 3; padding: 0 1; color: $text-muted; }
    #origin { height: auto; max-height: 4; padding: 0 1; color: $text-muted; }
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
        self.selected_identity: RecordIdentity | None = None
        self.selected_record: dict[str, object] | None = None
        self.selected_origin: SourceOrigin | None = None
        self.pinned_identity: RecordIdentity | None = None
        self.inspected_identity: RecordIdentity | None = None
        self.inspected_origin: SourceOrigin | None = None
        self.inspected_record: dict[str, object] | None = None
        self.requested_field: tuple[str, ...] | None = None

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(
            f"CONSOLE · {status.record_count} records · {status.phase} · "
            f"{status.skipped_lines} skipped lines\n"
            "Tab panes · I JSON · [/] resize · P pin · C copy · F2/F3 focus · Ctrl+P keys",
            id="heading",
            markup=False,
        )
        with Horizontal(id="split"):
            with Vertical(id="stream"):
                yield Static(
                    "CONSOLE · pan · time · duration off",
                    id="console-heading",
                    classes="pane-heading",
                )
                yield ConsoleViewport(self.session)
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

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
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
            return isinstance(self.focused, (ConsoleViewport, JSONInspector))
        return super().check_action(action, parameters)

    def on_mount(self) -> None:
        self.show_record(0)
        self._layout_inspector()

    def on_console_viewport_options_changed(self, message: ConsoleViewport.OptionsChanged) -> None:
        options = message.options
        self.query_one("#console-heading", Static).update(
            f"CONSOLE · {'wrap' if options.wrap else 'pan'} · {options.timestamp_mode} · "
            f"duration {'on' if options.show_duration else 'off'}"
        )

    def on_console_viewport_selected(self, message: ConsoleViewport.Selected) -> None:
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
            self.query_one(ConsoleViewport).focus()

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
        self.query_one(ConsoleViewport).focus()

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
            return (
                f"{label} {identity.ordinal + 1}/{self.session.status.record_count} · input "
                f"{identity.input_occurrence + 1} · {Path(origin.source).name}:{origin.position}"
            )

        selected = describe("Selected", self.selected_identity, self.selected_origin)
        if self.pinned_identity:
            detail = describe("Pinned", self.inspected_identity, self.inspected_origin)
        else:
            detail = (
                f"Disk {self.session.resources.disk_bytes:,} bytes · "
                f"RAM browsing cache {self.session.resources.ram_cache_bytes:,} bytes"
            )
        self.query_one("#origin", Static).update(selected + "\n" + detail)

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
