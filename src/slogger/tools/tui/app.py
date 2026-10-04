"""Optional native split view. Shared Investigation operations stay headless."""

from __future__ import annotations

import json

from rich.cells import cell_len
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Static

from ..investigation import Investigation, RecordIdentity
from .presentation import console_text


class ConsoleViewport(ScrollView, can_focus=True):
    """Virtual one-row console; only viewport rows are decoded and rendered."""

    BINDINGS = [
        Binding("up", "select(-1)", "Previous", show=False),
        Binding("down", "select(1)", "Next", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
    ]

    class Selected(Message):
        def __init__(self, ordinal: int) -> None:
            super().__init__()
            self.ordinal = ordinal

    def __init__(self, session: Investigation) -> None:
        super().__init__(id="console")
        self.session = session
        self.selected = 0
        self._width = 1

    def on_mount(self) -> None:
        self.virtual_size = Size(self.size.width, self.session.status.record_count)
        self.focus()

    def render_line(self, y: int) -> Strip:
        ordinal = y + self.scroll_offset.y
        page = self.session.page(ordinal, 1)
        if not page.records:
            return Strip.blank(self.size.width, self.rich_style)
        marker = "› " if ordinal == self.selected else "  "
        text = Text(marker)
        text.append_text(console_text(page.records[0]))
        if ordinal == self.selected:
            text.stylize("reverse")
        self._width = max(self._width, text.cell_len)
        self.virtual_size = Size(
            max(self.size.width, self._width), self.session.status.record_count
        )
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)

    def select(self, ordinal: int) -> None:
        count = self.session.status.record_count
        if not count:
            return
        self.selected = min(max(ordinal, 0), count - 1)
        top = self.scroll_offset.y
        if self.selected < top:
            self.scroll_to(y=self.selected, animate=False)
        elif self.selected >= top + self.size.height:
            self.scroll_to(y=max(0, self.selected - self.size.height + 1), animate=False)
        self.refresh()
        self.post_message(self.Selected(self.selected))

    def action_select(self, delta: int) -> None:
        self.select(self.selected + delta)

    def action_page(self, direction: int) -> None:
        self.select(self.selected + direction * max(1, self.size.height))

    def action_first(self) -> None:
        self.select(0)

    def action_last(self) -> None:
        self.select(self.session.status.record_count - 1)

    def on_click(self, event: events.Click) -> None:
        self.focus()
        self.select(event.y + self.scroll_offset.y)


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
            "↑↓ select · PgUp/PgDn page · Home/End · Tab panes",
            id="heading",
        )
        with Horizontal(id="split"):
            with Vertical(id="stream"):
                yield Static("CONSOLE", classes="pane-heading")
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
