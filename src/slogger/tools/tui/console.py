"""Bounded native console rows anchored by record identity and wrapped line."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from math import ceil

from rich.cells import get_character_cell_size
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..investigation import Investigation, RecordIdentity, RecordPage, RecordView, ViewScope
from ..investigation.search import SearchOptions
from .presentation import ConsoleOptions, console_fields, console_text
from .search import highlight_line, visible_offsets


class _RecordLayout:
    """One complete admitted record, with at most 1025 sparse line checkpoints."""

    def __init__(self, text: Text, width: int | None, search: SearchOptions | None = None) -> None:
        self.text = text
        self.search = search
        self.text.expand_tabs(4)
        self.width = width
        self.checkpoints: list[tuple[int, int]] = []
        self.checkpoint_rows: list[int] = []
        stride = max(128, ceil((len(text.plain) + 1) / 1024))
        self.height = 0
        self.max_width = 1
        for row, (start, _, cells) in enumerate(self._lines(0)):
            if row % stride == 0:
                self.checkpoints.append((row, start))
                self.checkpoint_rows.append(row)
            self.height = row + 1
            self.max_width = max(self.max_width, cells)

    def _lines(self, start: int):
        plain = self.text.plain
        cells = 0
        for position in range(start, len(plain)):
            char = plain[position]
            if char == "\n":
                yield start, position, cells
                start, cells = position + 1, 0
                continue
            char_cells = get_character_cell_size(char)
            if self.width is not None and cells and cells + char_cells > self.width:
                yield start, position, cells
                start, cells = position, 0
            cells += char_cells
        yield start, len(plain), cells

    def line(self, row: int, offset: int = 0, width: int | None = None) -> Text:
        checkpoint = bisect_right(self.checkpoint_rows, row) - 1
        first_row, checkpoint_start = self.checkpoints[max(0, checkpoint)]
        for line_offset, (start, end, _) in enumerate(self._lines(checkpoint_start)):
            if first_row + line_offset == row:
                left, right = (
                    visible_offsets(self.text.plain, start, end, offset, width)
                    if width is not None and self.search is not None
                    else (start, end)
                )
                return highlight_line(
                    self.text, start, end, self.search, visible_start=left, visible_end=right
                )
        return Text()


class ConsoleViewport(ScrollView, can_focus=True):
    """Virtual display rows, retaining one record layout and only visible strips.

    Vertical position is a displayed result position plus a line within its record. This
    avoids scanning the dataset or retaining a height entry for every record.
    """

    DEFAULT_CSS = "ConsoleViewport { overflow-y: hidden; }"
    BINDINGS = [
        Binding("up", "select(-1)", "Previous", show=False),
        Binding("down", "select(1)", "Next", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("ctrl+up", "rows(-1)", "Scroll up", show=False),
        Binding("ctrl+down", "rows(1)", "Scroll down", show=False),
        Binding("left", "scroll_left", "Pan left", show=False),
        Binding("right", "scroll_right", "Pan right", show=False),
        Binding("shift+left", "pan_page(-1)", "Pan page left", show=False),
        Binding("shift+right", "pan_page(1)", "Pan page right", show=False),
        Binding("ctrl+left", "pan_start", "Pan start", show=False),
        Binding("w", "wrap", "Wrap"),
        Binding("t", "timestamp", "Timestamp"),
        Binding("d", "duration", "Duration"),
        Binding("alt+left", "field(-1)", "Previous field", show=False),
        Binding("alt+right", "field(1)", "Next field", show=False),
        Binding("enter", "count_field", "Field counts", show=False),
    ]

    class Selected(Message):
        def __init__(self, position: int, identity: RecordIdentity, view_scope: ViewScope) -> None:
            super().__init__()
            self.position = position
            self.identity = identity
            self.view_scope = view_scope
            self.ordinal = identity.ordinal

    class FieldSelected(Message):
        def __init__(
            self, path: tuple[str, ...], binding: tuple[str | None, int] = (None, 0)
        ) -> None:
            super().__init__()
            self.path = path
            self.binding = binding

    class FieldRequested(Message):
        def __init__(
            self,
            path: tuple[str, ...],
            view_scope: ViewScope,
            binding: tuple[str | None, int] = (None, 0),
        ) -> None:
            super().__init__()
            self.path = path
            self.binding = binding
            self.view_scope = view_scope

    class OptionsChanged(Message):
        def __init__(
            self, options: ConsoleOptions, binding: tuple[str | None, int] = (None, 0)
        ) -> None:
            super().__init__()
            self.options = options
            self.binding = binding

    def __init__(self, session: Investigation, options: ConsoleOptions | None = None) -> None:
        super().__init__(id="console")
        self.session = session
        self.binding: tuple[str | None, int] = (session.owner_id, 0)
        self.view: RecordView | None = None
        self.options = options or ConsoleOptions()
        self.search_options: SearchOptions | None = None
        self.selected = 0
        self._top = (0, 0)
        self._layout: tuple[int, _RecordLayout] | None = None
        self._window_key: tuple[object, ...] | None = None
        self._rows: list[tuple[int, int, Strip]] = []
        self._width = 1
        self.selected_field: tuple[str, ...] | None = None

    @property
    def view_scope(self) -> ViewScope:
        return (
            self.view.view_scope
            if self.view is not None
            else ViewScope(self.session.dataset_id, self.session.dataset_id)
        )

    @property
    def record_count(self) -> int:
        return self.view.record_count if self.view is not None else self.session.status.record_count

    def page(self, position: int, limit: int = 100) -> RecordPage:
        return (
            self.view.page(position, limit)
            if self.view is not None
            else self.session.page(position, limit)
        )

    def bind_owner(
        self, session: Investigation, view: RecordView | None, position: int, generation: int
    ) -> None:
        """Publish an already staged owner/position without performing record reads."""
        self.session = session
        self.binding = session.owner_id, generation
        self.view = view
        self.selected = position
        self._top = position, 0
        self._layout = None
        self._rows.clear()
        self._window_key = None
        self._width = 1
        self.scroll_to(x=0, animate=False)
        self.refresh()

    def set_view(self, view: RecordView | None, selected_ordinal: int | None = None) -> None:
        """Install successful membership and retain selection only when it belongs."""
        self.view = view
        selected = (
            view.position_of(selected_ordinal)
            if view is not None and selected_ordinal is not None
            else selected_ordinal
        )
        self.selected = selected if selected is not None else 0
        self._top = self.selected, 0
        self._layout = None
        self._rows = []
        self._window_key = None
        self._width = 1
        self.scroll_to(x=0, animate=False)
        self.select(self.selected)
        self.refresh()

    def set_search(self, options: SearchOptions | None) -> None:
        self.search_options = options
        self._layout = None
        self._window_key = None
        self.refresh()

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _: self.presentation_updated())
        self.focus()
        self.capture_updated()

    def on_resize(self) -> None:
        self._layout = None
        self._window_key = None
        if self.record_count:
            ordinal, row = self._top
            self._top = (ordinal, min(row, self._record(ordinal).height - 1))
        self.refresh()

    def presentation_updated(self) -> None:
        """Invalidate styled viewport caches when a theme changes."""
        self._layout = None
        self._window_key = None
        self.refresh()

    def capture_updated(self) -> None:
        """Redraw an updated admitted prefix without resetting selected identity."""
        self._window_key = None
        self.refresh()

    def _record(self, ordinal: int) -> _RecordLayout:
        if self._layout is not None and self._layout[0] == ordinal:
            return self._layout[1]
        page = self.page(ordinal, 1)
        text = Text("  ")
        if page.records:
            text.append_text(
                console_text(page.records[0], self.options, light=not self.app.current_theme.dark)
            )
            if ordinal == self.selected and self.selected_field is not None:
                for span in tuple(text.spans):
                    if (
                        isinstance(span.style, Style)
                        and span.style.meta.get("field_path") == self.selected_field
                    ):
                        text.stylize("bold underline", span.start, span.end)
        layout = _RecordLayout(
            text, max(1, self.size.width) if self.options.wrap else None, self.search_options
        )
        self._layout = ordinal, layout
        self._width = max(self._width, layout.max_width)
        return layout

    def _window(self) -> None:
        key = (
            self._top,
            self.size,
            self.scroll_offset.x,
            self.options,
            self.record_count,
        )
        if self._window_key == key:
            return
        self._rows = []
        ordinal, row = self._top
        while len(self._rows) < self.size.height and ordinal < self.record_count:
            layout = self._record(ordinal)
            while row < layout.height and len(self._rows) < self.size.height:
                line = layout.line(
                    row, 0 if self.options.wrap else self.scroll_offset.x, self.size.width
                )
                strip = Strip(line.render(self.app.console)).apply_style(self.rich_style)
                start = 0 if self.options.wrap else self.scroll_offset.x
                strip = strip.crop(start, start + self.size.width)
                self._rows.append((ordinal, row, strip))
                row += 1
            ordinal, row = ordinal + 1, 0
        self.virtual_size = Size(
            self.size.width if self.options.wrap else max(self.size.width, self._width),
            self.size.height,
        )
        self._window_key = key

    def render_line(self, y: int) -> Strip:
        self._window()
        if y >= len(self._rows):
            return Strip.blank(self.size.width, self.rich_style)
        ordinal, row, strip = self._rows[y]
        if ordinal == self.selected:
            if row == 0 and self.scroll_offset.x == 0:
                strip = Strip.join([Strip(Text("› ").render(self.app.console)), strip.crop(2)])
            strip = strip.apply_style(Style(reverse=True))
        return strip.adjust_cell_length(self.size.width, self.rich_style)

    def select(self, ordinal: int) -> None:
        count = self.record_count
        if not count:
            return
        self.selected = min(max(ordinal, 0), count - 1)
        self._window()
        if not any(record == self.selected for record, _, _ in self._rows):
            self._top = self.selected, 0
        self.refresh()
        page = self.page(self.selected, 1)
        if page.identities:
            self.post_message(self.Selected(self.selected, page.identities[0], self.view_scope))

    def action_select(self, delta: int) -> None:
        self.select(self.selected + delta)

    def _scroll_rows(self, delta: int) -> None:
        if not self.record_count:
            return
        ordinal, row = self._top
        if delta > 0:
            while delta:
                layout = self._record(ordinal)
                remaining = layout.height - row - 1
                if delta <= remaining:
                    row += delta
                    break
                if ordinal + 1 >= self.record_count:
                    row = layout.height - 1
                    break
                delta -= remaining + 1
                ordinal, row = ordinal + 1, 0
        else:
            delta = -delta
            while delta:
                if delta <= row:
                    row -= delta
                    break
                if ordinal == 0:
                    row = 0
                    break
                delta -= row + 1
                ordinal -= 1
                row = self._record(ordinal).height - 1
        self._top = ordinal, row
        self.refresh()

    def action_pan_page(self, direction: int) -> None:
        if not self.options.wrap:
            self.scroll_to(
                x=self.scroll_target_x + direction * max(1, self.size.width - 1),
                animate=False,
            )

    def action_pan_start(self) -> None:
        self.scroll_to(x=0, animate=False)

    def action_rows(self, delta: int) -> None:
        self._scroll_rows(delta)

    def action_page(self, direction: int) -> None:
        self._scroll_rows(direction * max(1, self.size.height - 1))
        self.select(self._top[0])

    def action_first(self) -> None:
        self._top = 0, 0
        self.select(0)

    def action_last(self) -> None:
        self._top = max(0, self.record_count - 1), 0
        self.select(self._top[0])

    def set_options(self, options: ConsoleOptions) -> None:
        """Apply session presentation options without changing captured data."""
        self.options = options
        self._layout = None
        self._window_key = None
        self._width = 1
        self._top = self.selected, 0
        self.scroll_to(x=0, animate=False)
        self.refresh()
        self.post_message(self.OptionsChanged(options, self.binding))

    def action_wrap(self) -> None:
        self.set_options(replace(self.options, wrap=not self.options.wrap))

    def action_timestamp(self) -> None:
        modes = ("time", "datetime", "original")
        next_mode = modes[(modes.index(self.options.timestamp_mode) + 1) % len(modes)]
        self.set_options(replace(self.options, timestamp_mode=next_mode))

    def action_duration(self) -> None:
        self.set_options(replace(self.options, show_duration=not self.options.show_duration))

    def action_field(self, direction: int) -> None:
        page = self.page(self.selected, 1)
        if not page.records:
            return
        fields = [(key,) for key, _ in console_fields(page.records[0], self.options) if key]
        if not fields:
            return
        index = (
            fields.index(self.selected_field)
            if self.selected_field in fields
            else (-1 if direction > 0 else 0)
        )
        self.selected_field = fields[(index + direction) % len(fields)]
        self._layout = None
        self._window_key = None
        self.refresh()
        self.post_message(self.FieldSelected(self.selected_field, self.binding))

    def action_count_field(self) -> None:
        if self.selected_field is not None:
            self.post_message(
                self.FieldRequested(self.selected_field, self.view_scope, self.binding)
            )

    def on_click(self, event: events.Click) -> None:
        self.focus()
        self._window()
        if 0 <= event.y < len(self._rows):
            self.select(self._rows[event.y][0])
            path = event.style.meta.get("field_path")
            if (
                isinstance(path, tuple)
                and path
                and all(isinstance(key, str) and key for key in path)
            ):
                self.selected_field = path
                self._layout = None
                self._window_key = None
                self.refresh()
                self.post_message(self.FieldSelected(path, self.binding))
                if event.ctrl or event.chain > 1:
                    self.post_message(self.FieldRequested(path, self.view_scope, self.binding))
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if not event.ctrl and not event.shift:
            self._scroll_rows(3)
            event.prevent_default()
            event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if not event.ctrl and not event.shift:
            self._scroll_rows(-3)
            event.prevent_default()
            event.stop()
