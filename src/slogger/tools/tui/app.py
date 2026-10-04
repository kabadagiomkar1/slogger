"""Optional native split view. Shared Investigation operations stay headless."""

from __future__ import annotations

import json

from rich.cells import cell_len
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Static

from ..core.runtime import SourceOrigin
from ..investigation import Investigation, RecordIdentity
from .console import ConsoleViewport


class JSONInspector(ScrollView, can_focus=True):
    """Complete parsed JSON; highlight only the visible lines on demand."""

    def __init__(self) -> None:
        super().__init__(id="json")
        self.document = ""
        self._lines: list[str] = []

    def set_record(self, record: dict[str, object] | None) -> None:
        self.document = (
            json.dumps(record, indent=2, ensure_ascii=False) if record is not None else ""
        )
        self._lines = self.document.splitlines()
        self.virtual_size = Size(
            max((cell_len(line) for line in self._lines), default=1), len(self._lines)
        )
        self.scroll_to(x=0, y=0, animate=False)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        line = y + self.scroll_offset.y
        if line >= len(self._lines):
            return Strip.blank(self.size.width, self.rich_style)
        text = Syntax(
            self._lines[line], "json", theme="github-dark", background_color="default"
        ).highlight(self._lines[line])
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)


class InvestigationApp(App[None]):
    """Native consumer of a progressively published captured prefix."""

    TITLE = "slogger investigation"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("tab", "focus_next", "Next pane"),
        Binding("escape", "cancel_capture", "Cancel loading"),
    ]
    CSS = """
    Screen { background: $background; }
    #heading { height: auto; min-height: 2; max-height: 6; padding: 0 1; color: $text-muted; }
    #split { height: 1fr; }
    #stream { width: 2fr; }
    #inspector { width: 1fr; min-width: 25; border-left: solid $primary-muted; }
    .pane-heading { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #console, #json { height: 1fr; }
    #origin { height: 2; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, session: Investigation) -> None:
        super().__init__()
        self.session = session
        self.selected_ordinal = 0
        self.selected_identity: RecordIdentity | None = None
        self.selected_origin: SourceOrigin | None = None
        self.inspected_record: dict[str, object] | None = None
        self._capture_status = session.status

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(self.capture_heading(), id="heading", markup=False)
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
                )
                yield JSONInspector()
        yield Static(id="origin")
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
            "W wrap · T time · D duration · Tab panes · Esc cancel loading"
        )
        if status.phase in ("failed", "canceled") and self.session.diagnostics.terminal:
            diagnostic = self.session.diagnostics.terminal
            location = (
                f"{diagnostic.origin.source}:{diagnostic.origin.position} · "
                if diagnostic.origin is not None
                else ""
            )
            text += f"\n{diagnostic.code}: {location}{diagnostic.message}"
        return text

    def on_mount(self) -> None:
        self.show_record(0)
        self.set_interval(0.1, self.refresh_capture)

    def refresh_capture(self) -> None:
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
            self.update_origin()

    def action_cancel_capture(self) -> None:
        self.session.cancel()

    def on_console_viewport_options_changed(self, message: ConsoleViewport.OptionsChanged) -> None:
        options = message.options
        self.query_one("#console-heading", Static).update(
            f"CONSOLE · {'wrap' if options.wrap else 'pan'} · {options.timestamp_mode} · "
            f"duration {'on' if options.show_duration else 'off'}"
        )

    def on_console_viewport_selected(self, message: ConsoleViewport.Selected) -> None:
        self.show_record(message.ordinal)

    def show_record(self, ordinal: int) -> None:
        page = self.session.page(ordinal, 1)
        if not page.records:
            return
        self.selected_ordinal = ordinal
        self.selected_identity = page.identities[0]
        self.inspected_record = page.records[0]
        self.query_one(JSONInspector).set_record(page.records[0])
        self.selected_origin = page.origins[0]
        self.update_origin()

    def update_origin(self) -> None:
        origin = self.selected_origin
        identity = self.selected_identity
        if origin is None or identity is None:
            return
        ordinal = self.selected_ordinal
        self.query_one("#origin", Static).update(
            f"Record {ordinal + 1}/{self.session.status.record_count} · input "
            f"{identity.input_occurrence + 1} · {origin.source}:{origin.position}\n"
            f"Disk {self.session.resources.disk_bytes:,} bytes · "
            f"RAM browsing cache {self.session.resources.ram_cache_bytes:,} bytes"
        )
