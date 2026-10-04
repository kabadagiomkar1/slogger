"""Native lower aggregate pane. Scoped exact operations remain headless."""

from __future__ import annotations

import json

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Button, Input, Static

from ..core.bindings import GroupBinding
from ..core.filter_language import FilterSyntaxError, format_field_path, parse_field_path
from ..investigation import AggregateResult
from .filter_editor import FilterEditor


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
        if self.result.scope.metrics is None and not self.result.scope.grouping:
            text = Text(f"{row['count']:>9,}  ", style="bold cyan")
            text.append(
                json.dumps(row["value"], ensure_ascii=False),
                style="magenta" if row["value"] is None else "",
            )
        else:
            text = Text()
            for name, value in row.items():
                if text:
                    text.append("   ")
                text.append(name + " ", style="bold cyan")
                text.append(_display_scalar(value), style="magenta" if value is None else "")
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
    AggregatePane { height: 40%; min-height: 9; max-height: 18; border-top: solid $primary-muted; }
    #aggregate-field, #aggregate-metrics, #aggregate-grouping {
        height: 1; margin: 0; border: none; padding: 0 1;
    }
    #aggregate-scope-controls { height: 1; }
    #aggregate-scope-controls Button { height: 1; min-width: 14; border: none; padding: 0 1; }
    #aggregate-mode { width: 1fr; height: 1; padding: 0 1; }
    #aggregate-label { height: auto; max-height: 3; color: $text-muted; padding: 0 1; }
    #aggregate-results { height: 1fr; overflow-y: hidden; }
    """

    class FieldRequested(Message):
        def __init__(
            self,
            path: tuple[str, ...],
            *,
            metrics: tuple[str, ...] | None = None,
            infer_metrics: bool = True,
            grouping: tuple[GroupBinding, ...] | None = None,
        ) -> None:
            super().__init__()
            self.path = path
            self.metrics = metrics
            self.infer_metrics = infer_metrics
            self.grouping = grouping

    class DetachRequested(Message):
        pass

    class ReattachRequested(Message):
        pass

    def __init__(self, editor: FilterEditor | None = None) -> None:
        super().__init__(id="aggregate-pane")
        self.editor = editor or FilterEditor(
            id="aggregate-editor", input_id="aggregate-filter", label="Scope", edit_key="Ctrl+D"
        )
        self.editor.display = False
        self.display = False
        self.displayed_scope = ""
        self.pending_scope = ""
        self.status_text = "Select a field · counts include present null/zero/false"
        self.generation = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="aggregate-scope-controls"):
            yield Static("Follows applied Main · Ctrl+D detach", id="aggregate-mode", markup=False)
            yield Button("Detach", id="aggregate-detach")
            reattach = Button("Reattach", id="aggregate-reattach")
            reattach.display = False
            yield reattach
        yield self.editor
        yield Input(
            placeholder='Field · request.method or ["literal.key"] · Enter counts',
            id="aggregate-field",
        )
        yield Input(
            value="values",
            placeholder="Metrics · values or count, sum, mean, min, max",
            id="aggregate-metrics",
        )
        yield Input(
            placeholder='Group by · region, request.zone as zone, ["literal.key"] · Enter applies',
            id="aggregate-grouping",
        )
        yield Static(self.status_text, id="aggregate-label", markup=False)
        yield AggregateViewport()

    def set_following(self, following: bool) -> None:
        self.editor.display = not following
        self.query_one("#aggregate-detach", Button).display = following
        self.query_one("#aggregate-reattach", Button).display = not following
        self.query_one("#aggregate-mode", Static).update(
            "Follows applied Main · Ctrl+D detach"
            if following
            else "Independent scope · Ctrl+D edit · Reattach follows Main"
        )

    def on_button_pressed(self, message: Button.Pressed) -> None:
        if message.button.id == "aggregate-detach":
            self.post_message(self.DetachRequested())
        elif message.button.id == "aggregate-reattach":
            self.post_message(self.ReattachRequested())
        else:
            return
        message.stop()

    def _label(self, state: str = "") -> None:
        parts = [
            f"AGGREGATE · {self.displayed_scope}"
            if self.displayed_scope
            else "AGGREGATE · no successful result"
        ]
        if state:
            parts.append(state)
        self.status_text = "\n".join(parts)
        self.query_one("#aggregate-label", Static).update(self.status_text)

    def begin(
        self,
        path: tuple[str, ...],
        scope: str,
        generation: int,
        *,
        update_field: bool = True,
        reveal: bool = True,
        metrics: tuple[str, ...] | None = None,
        grouping: tuple[GroupBinding, ...] = (),
    ) -> None:
        if reveal:
            self.display = True
        self.generation = generation
        self.pending_scope = scope
        if update_field:
            self.query_one("#aggregate-field", Input).value = format_field_path(path)
            self.query_one("#aggregate-metrics", Input).value = (
                ", ".join(metrics) if metrics is not None else "values"
            )
        if update_field:
            self.query_one("#aggregate-grouping", Input).value = format_grouping(grouping)
        self._label(f"Pending: {scope} · Esc cancel")

    def publish(self, result: AggregateResult, scope: str, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.displayed_scope = scope
        self.pending_scope = ""
        self.query_one(AggregateViewport).set_result(result)
        population = "groups" if result.scope.metrics is None else "summaries"
        self._label(
            f"{result.record_count:,} {population} · "
            "complete · present values only · F5 field / F6 results / F9 metrics"
        )
        return True

    def fail(self, generation: int, reason: str) -> None:
        if generation == self.generation:
            self._label(f"{reason} · requested {self.pending_scope}; prior results retained")
            self.pending_scope = ""

    def on_input_submitted(self, message: Input.Submitted) -> None:
        message.stop()
        try:
            path = parse_field_path(self.query_one("#aggregate-field", Input).value)
            if message.input.id == "aggregate-grouping":
                self.post_message(
                    self.FieldRequested(
                        path, grouping=parse_grouping(message.value), infer_metrics=False
                    )
                )
                return
            if message.input.id == "aggregate-metrics":
                raw = message.value.strip()
                metrics = (
                    None if raw == "values" else tuple(part.strip() for part in raw.split(","))
                )
                if metrics is not None and (
                    not metrics
                    or any(op not in ("count", "sum", "mean", "min", "max") for op in metrics)
                    or len(set(metrics)) != len(metrics)
                ):
                    raise ValueError("Metrics: values or unique count, sum, mean, min, max")
                self.post_message(self.FieldRequested(path, metrics=metrics, infer_metrics=False))
                return
        except (FilterSyntaxError, ValueError) as error:
            self._label(str(error))
        else:
            self.post_message(self.FieldRequested(path))


def _display_scalar(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except ValueError:
        if not isinstance(value, int):
            raise
        # Exact totals can exceed the interpreter's decimal conversion threshold.
        parts = []
        remaining = abs(value)
        while remaining:
            remaining, part = divmod(remaining, 10**9)
            parts.append(part)
        return (
            ("-" if value < 0 else "")
            + str(parts[-1])
            + "".join(f"{part:09d}" for part in reversed(parts[:-1]))
        )


def format_grouping(grouping: tuple[GroupBinding, ...]) -> str:
    return ", ".join(
        format_field_path(item.path)
        + (
            " as "
            + (
                item.label
                if item.label.isidentifier()
                else json.dumps(item.label, ensure_ascii=False)
            )
            if item.label != format_field_path(item.path)
            else ""
        )
        for item in grouping
    )


def parse_grouping(text: str) -> tuple[GroupBinding, ...]:
    if not text.strip():
        return ()
    bindings = []
    for component in _group_segments(text):
        parts = _group_segments(component, alias=True)
        if len(parts) > 2:
            raise ValueError("Grouping: one optional 'as name' per field")
        name = None
        if len(parts) == 2:
            raw = parts[1].strip()
            if raw.startswith('"'):
                name = json.loads(raw)
            elif raw.isidentifier():
                name = raw
            else:
                raise ValueError("Grouping alias must be a name or quoted JSON string")
        bindings.append(GroupBinding(parse_field_path(parts[0].strip()), name))
    return tuple(bindings)


def _group_segments(text: str, *, alias: bool = False) -> list[str]:
    """Split only outside exact bracket/quoted path components."""
    parts = []
    quote = False
    escaped = False
    depth = start = 0
    for position, char in enumerate(text):
        if escaped:
            escaped = False
        elif quote and char == "\\":
            escaped = True
        elif char == '"':
            quote = not quote
        elif not quote:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            elif depth == 0 and (
                (not alias and char == ",")
                or (
                    alias
                    and text[position : position + 2] == "as"
                    and position > 0
                    and text[position - 1].isspace()
                    and position + 2 < len(text)
                    and text[position + 2].isspace()
                )
            ):
                parts.append(text[start:position])
                start = position + (2 if alias else 1)
    parts.append(text[start:])
    return parts
