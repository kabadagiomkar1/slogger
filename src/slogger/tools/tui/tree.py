"""Virtual native tree navigation; no flattened full-trace array or fold set."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..investigation.resources import resident_size
from ..investigation.tree import TraceTree, TreeRow
from .presentation import ConsoleOptions, console_text


class TreeViewport(ScrollView, can_focus=True):
    BINDINGS = [
        Binding("up", "move(-1)", "Previous row", show=False),
        Binding("down", "move(1)", "Next row", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "edge(False)", "First row", show=False),
        Binding("end", "edge(True)", "Last row", show=False),
        Binding("left", "parent", "Collapse / parent", show=False),
        Binding("right", "child", "Expand / child", show=False),
        Binding("space,enter", "fold", "Fold node"),
        Binding("shift+space", "fold_all", "Fold all"),
        Binding("shift+left", "pan(-1)", "Pan left", show=False),
        Binding("shift+right", "pan(1)", "Pan right", show=False),
    ]

    class Selected(Message):
        def __init__(self, ordinal: int) -> None:
            super().__init__()
            self.ordinal = ordinal

    def __init__(self) -> None:
        super().__init__(id="tree")
        self.trace_tree: TraceTree | None = None
        self.focused_key: int | None = None
        self._top: int | None = None
        self.expanded_default = True
        self._exceptions: set[int] = set()
        self._rows: list[TreeRow] = []
        self._window_key: tuple[object, ...] | None = None
        self._fold_revision = 0
        self._virtual_width = 1
        self.options = ConsoleOptions()

    def set_tree(self, tree: TraceTree, ordinal: int | None, options: ConsoleOptions) -> None:
        self.trace_tree = tree
        self.options = options
        self._exceptions.clear()
        self.expanded_default = True
        first = tree.edge_child()
        self.focused_key = -(ordinal + 1) if ordinal is not None else first.key if first else None
        self._top = self.focused_key
        self._window_key = None
        self._virtual_width = 1
        self.refresh()

    def _expanded(self, key: int) -> bool:
        return self.expanded_default != (key in self._exceptions)

    def _set_expanded(self, key: int, expanded: bool) -> None:
        self._fold_revision += 1
        if expanded == self.expanded_default:
            self._exceptions.discard(key)
        elif self.trace_tree is not None and len(self._exceptions) >= max(
            1, self.trace_tree.session.limits.working_memory_bytes // 256
        ):
            self.app.notify(
                "Fold state exceeds working memory; use Fold all to reset.", markup=False
            )
        else:
            self._exceptions.add(key)

    def _next(self, row: TreeRow) -> TreeRow | None:
        assert self.trace_tree is not None
        if self._expanded(row.key):
            child = self.trace_tree.edge_child(row.key)
            if child is not None:
                return child
        while True:
            sibling = self.trace_tree.sibling(row.key)
            if sibling is not None:
                return sibling
            if row.parent_key is None:
                return None
            row = self.trace_tree.row(row.parent_key)

    def _previous(self, row: TreeRow) -> TreeRow | None:
        assert self.trace_tree is not None
        sibling = self.trace_tree.sibling(row.key, previous=True)
        if sibling is None:
            return self.trace_tree.row(row.parent_key) if row.parent_key is not None else None
        while self._expanded(sibling.key):
            child = self.trace_tree.edge_child(sibling.key, last=True)
            if child is None:
                break
            sibling = child
        return sibling

    def _window(self) -> None:
        key = (self._top, self.size, self._fold_revision, self.options)
        if key == self._window_key:
            return
        self._window_key = key
        self._rows = []
        if self.trace_tree is None or self._top is None:
            return
        row = self.trace_tree.row(self._top)
        retained = 0
        while len(self._rows) < self.size.height:
            cost = resident_size(row.__dict__) + 128
            if retained + cost > self.trace_tree.session.limits.page_memory_bytes:
                break
            retained += cost
            self._rows.append(row)
            following = self._next(row)
            if following is None:
                break
            row = following
        self.virtual_size = Size(max(self.size.width, self._virtual_width), self.size.height)

    def _depth(self, row: TreeRow) -> int:
        assert self.trace_tree is not None
        depth = 0
        while row.parent_key is not None:
            depth += 1
            row = self.trace_tree.row(row.parent_key)
        return depth

    def render_line(self, y: int) -> Strip:
        self._window()
        if y >= len(self._rows) or self.trace_tree is None:
            return Strip.blank(self.size.width, self.rich_style)
        row = self._rows[y]
        depth = self._depth(row)
        indent = min(depth * 2, max(0, self.size.width // 3))
        text = Text(" " * indent)
        if depth * 2 > indent:
            text.append(f"[{depth}] ", style="dim")
        if row.kind == "record":
            text.append("· ", style="dim")
            if row.relationship:
                text.append(f"[{row.relationship}] ", style="dim")
            assert row.ordinal is not None
            page = self.trace_tree.session.page(row.ordinal, 1)
            text.append_text(console_text(page.records[0], self.options))
        else:
            text.append("▾ " if self._expanded(row.key) else "▸ ", style="dim")
            text.append(row.label or row.span_id or row.trace_id or "span", style="bold")
            if row.kind != "trace":
                text.append(f" · {row.relationship} · {row.lifecycle}", style="dim")
                if row.name_conflict:
                    text.append(" · conflicting names", style="yellow")
                if row.status is not None:
                    text.append(f" · {row.status} · {row.duration_ms}ms", style="dim")
            text.append(f" · {row.record_count} direct records", style="dim")
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        if strip.cell_length > self._virtual_width:
            self._virtual_width = strip.cell_length
            self.virtual_size = Size(self._virtual_width, self.size.height)
        if row.key == self.focused_key:
            strip = strip.apply_style(Style(reverse=True))
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)

    def select(self, row: TreeRow) -> None:
        self.focused_key = row.key
        self._window()
        if not any(item.key == row.key for item in self._rows):
            self._top = row.key
        if row.ordinal is not None:
            self.post_message(self.Selected(row.ordinal))
        self.refresh()

    def action_move(self, direction: int) -> None:
        if self.trace_tree is None or self.focused_key is None:
            return
        row = self.trace_tree.row(self.focused_key)
        following = self._next(row) if direction > 0 else self._previous(row)
        if following is not None:
            self.select(following)

    def action_page(self, direction: int) -> None:
        for _ in range(max(1, self.size.height - 1)):
            self.action_move(direction)

    def action_edge(self, last: bool) -> None:
        if self.trace_tree is None:
            return
        row = self.trace_tree.edge_child(last=last)
        if row is None:
            return
        if last:
            while self._expanded(row.key):
                child = self.trace_tree.edge_child(row.key, last=True)
                if child is None:
                    break
                row = child
        self.select(row)

    def action_fold(self) -> None:
        if self.trace_tree is not None and self.focused_key is not None:
            row = self.trace_tree.row(self.focused_key)
            if row.child_count:
                self._set_expanded(row.key, not self._expanded(row.key))
                self.refresh()

    def action_fold_all(self) -> None:
        if self.trace_tree is None:
            return
        self._fold_revision += 1
        self.expanded_default = not self.expanded_default
        self._exceptions.clear()
        if not self.expanded_default and self.focused_key is not None:
            row = self.trace_tree.row(self.focused_key)
            while row.parent_key is not None:
                row = self.trace_tree.row(row.parent_key)
            self.focused_key = self._top = row.key
        self.refresh()

    def action_parent(self) -> None:
        if self.trace_tree is None or self.focused_key is None:
            return
        row = self.trace_tree.row(self.focused_key)
        if row.child_count and self._expanded(row.key):
            self._set_expanded(row.key, False)
            self.refresh()
        elif row.parent_key is not None:
            self.select(self.trace_tree.row(row.parent_key))

    def action_child(self) -> None:
        if self.trace_tree is None or self.focused_key is None:
            return
        row = self.trace_tree.row(self.focused_key)
        if row.child_count and not self._expanded(row.key):
            self._set_expanded(row.key, True)
            self.refresh()
        else:
            child = self.trace_tree.edge_child(row.key)
            if child is not None:
                self.select(child)

    def action_pan(self, direction: int) -> None:
        self.scroll_to(
            x=max(0, self.scroll_offset.x + direction * max(1, self.size.width // 2)), animate=False
        )

    def on_click(self, event: events.Click) -> None:
        self.focus()
        self._window()
        if 0 <= event.y < len(self._rows):
            self.select(self._rows[event.y])
            if self._rows[event.y].kind != "record":
                self.action_fold()
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.action_page(1)
        event.prevent_default()
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.action_page(-1)
        event.prevent_default()
        event.stop()
