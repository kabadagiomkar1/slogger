"""Native lower counts pane. Scoped exact operations remain headless."""

from __future__ import annotations

import json

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Input, Static

from ..core.filter_language import FilterSyntaxError, format_field_path, parse_field_path
from ..investigation import AggregateResult


class AggregateViewport(ScrollView, can_focus=True):
    """Page only visible derived rows; arbitrary group counts remain reachable."""

    BINDINGS = [
        Binding("up", "move(-1)", "Previous group", show=False),
        Binding("down", "move(1)", "Next group", show=False),
        Binding("pageup", "page(-1)", "Previous page", show=False),
        Binding("pagedown", "page(1)", "Next page", show=False),
        Binding("home", "edge(False)", "First group", show=False),
        Binding("end", "edge(True)", "Last group", show=False),
        Binding("left", "scroll_left", "Pan left", show=False),
        Binding("right", "scroll_right", "Pan right", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id="aggregate-results")
        self.result: AggregateResult | None = None
        self.selected = 0
        self.top = 0

    def set_result(self, result: AggregateResult) -> None:
        self.result = result
        self.selected = self.top = 0
        self.scroll_to(x=0, animate=False)
        self.refresh()

    def action_move(self, delta: int) -> None:
        if self.result is None:
            return
        self.selected = min(max(0, self.selected + delta), max(0, self.result.record_count - 1))
        if self.selected < self.top or self.selected >= self.top + self.size.height:
            self.top = self.selected
        self.refresh()

    def action_page(self, direction: int) -> None:
        self.action_move(direction * max(1, self.size.height - 1))

    def action_edge(self, last: bool) -> None:
        if self.result is not None:
            self.action_move((self.result.record_count if last else 0) - self.selected)

    def render_line(self, y: int) -> Strip:
        if self.result is None:
            return Strip.blank(self.size.width, self.rich_style)
        page = self.result.page(self.top + y, 1)
        if not page.records:
            return Strip.blank(self.size.width, self.rich_style)
        row = page.records[0]
        text = Text(f"{row['count']:>9,}  ", style="bold cyan")
        text.append(
            json.dumps(row["value"], ensure_ascii=False),
            style="magenta" if row["value"] is None else "",
        )
        if self.top + y == self.selected:
            text.stylize("reverse")
        self.virtual_size = Size(max(self.size.width, text.cell_len), self.size.height)
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)

    def on_click(self, event: events.Click) -> None:
        self.focus()
        self.action_move(self.top + event.y - self.selected)
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.action_move(3)
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.action_move(-3)
        event.stop()
        event.prevent_default()


class AggregatePane(Vertical):
    """Editable selected field with honest retained and pending Main labels."""

    DEFAULT_CSS = """
    AggregatePane { height: 40%; min-height: 7; max-height: 15; border-top: solid $primary-muted; }
    #aggregate-field { height: 3; margin: 0; border: tall $primary-muted; }
    #aggregate-label { height: auto; max-height: 3; color: $text-muted; padding: 0 1; }
    #aggregate-results { height: 1fr; overflow-y: hidden; }
    """

    class FieldRequested(Message):
        def __init__(self, path: tuple[str, ...]) -> None:
            super().__init__()
            self.path = path

    def __init__(self) -> None:
        super().__init__(id="aggregate-pane")
        self.display = False
        self.displayed_scope = ""
        self.pending_scope = ""
        self.status_text = "Select a field · counts include present null/zero/false"
        self.generation = 0

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder='Field · request.method or ["literal.key"] · Enter counts',
            id="aggregate-field",
        )
        yield Static(self.status_text, id="aggregate-label", markup=False)
        yield AggregateViewport()

    def _label(self, state: str = "") -> None:
        parts = [
            f"COUNTS · {self.displayed_scope}"
            if self.displayed_scope
            else "COUNTS · no successful result"
        ]
        if state:
            parts.append(state)
        self.status_text = "\n".join(parts)
        self.query_one("#aggregate-label", Static).update(self.status_text)

    def begin(self, path: tuple[str, ...], scope: str, generation: int) -> None:
        self.display = True
        self.generation = generation
        self.pending_scope = scope
        self.query_one(Input).value = format_field_path(path)
        self._label(f"Pending: {scope} · Esc cancel")

    def publish(self, result: AggregateResult, scope: str, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.displayed_scope = scope
        self.pending_scope = ""
        self.query_one(AggregateViewport).set_result(result)
        self._label(
            f"{result.record_count:,} groups · complete · present values only · "
            "F5 field / F6 results"
        )
        return True

    def fail(self, generation: int, reason: str) -> None:
        if generation == self.generation:
            self._label(f"{reason} · requested {self.pending_scope}; prior counts retained")
            self.pending_scope = ""

    def on_input_submitted(self, message: Input.Submitted) -> None:
        message.stop()
        try:
            path = parse_field_path(message.value)
        except (FilterSyntaxError, ValueError) as error:
            self._label(str(error))
        else:
            self.post_message(self.FieldRequested(path))
