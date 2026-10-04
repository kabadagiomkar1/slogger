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
    """Initial native consumer, usable after synchronous capture completes."""

    TITLE = "slogger investigation"
    BINDINGS = [Binding("q", "quit", "Quit"), Binding("tab", "focus_next", "Next pane")]
    CSS = """
    Screen { background: $background; }
    #heading { height: 2; padding: 0 1; color: $text-muted; }
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
        self.inspected_record: dict[str, object] | None = None

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(
            f"CONSOLE · {status.record_count} records · {status.phase} · "
            f"{status.skipped_lines} skipped lines\n"
            "↑↓ select · PgUp/PgDn page · Home/End · ←→ pan · "
            "W wrap · T time · D duration · Tab panes",
            id="heading",
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
                )
                yield JSONInspector()
        yield Static(id="origin")
        yield Footer()

    def on_mount(self) -> None:
        self.show_record(0)

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
        origin = page.origins[0]
        self.query_one("#origin", Static).update(
            f"Record {ordinal + 1}/{self.session.status.record_count} · input "
            f"{page.identities[0].input_occurrence + 1} · {origin.source}:{origin.position}\n"
            f"Disk {self.session.resources.disk_bytes:,} bytes · "
            f"RAM browsing cache {self.session.resources.ram_cache_bytes:,} bytes"
        )
