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
from ..investigation.search import SearchOptions
from ..investigation.tree import TraceTree, TreeRow
from .console import _RecordLayout
from .presentation import ConsoleOptions, console_text
from .text import visible_text


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
        def __init__(self, ordinal: int, tree: TraceTree) -> None:
            super().__init__()
            self.ordinal = ordinal
            self.tree = tree

    def __init__(self) -> None:
        super().__init__(id="tree")
        self.trace_tree: TraceTree | None = None
        self.focused_key: int | None = None
        self._top: int | None = None
        self._top_line = 0
        self._strips: list[Strip] = []
        self._record_layout_cache: tuple[int, _RecordLayout] | None = None
        self.expanded_default = True
        self._exceptions: set[int] = set()
        self._exception_identities: dict[int, str] = {}
        self._fold_bytes = 0
        self._rows: list[TreeRow] = []
        self._window_key: tuple[object, ...] | None = None
        self._fold_revision = 0
        self._virtual_width = 1
        self.options = ConsoleOptions()
        self.search_options: SearchOptions | None = None
        self._revealed_ordinal: int | None = None
        self._fold_owner: object | None = None

    def set_tree(self, tree: TraceTree, ordinal: int | None, options: ConsoleOptions) -> None:
        first = tree.row(-(ordinal + 1)) if ordinal is not None else tree.edge_child()
        self.bind_owner(tree, first.key if first else None, options)
        if ordinal is not None:
            self._revealed_ordinal = ordinal
            self._fold_revision += 1

    def bind_owner(self, tree: TraceTree, initial_key: int | None, options: ConsoleOptions) -> None:
        """Publish an already verified staging key without synchronous database reads."""
        self.trace_tree = tree
        self.options = options
        if self._fold_owner is not tree.session:
            self._exceptions.clear()
            self._exception_identities.clear()
            self._fold_bytes = 0
            self.expanded_default = True
        self._fold_owner = tree.session
        self._revealed_ordinal = None
        self.focused_key = self._top = initial_key
        self._top_line = 0
        self._record_layout_cache = None
        self._window_key = None
        self._virtual_width = 1
        self.refresh()

    def clear_tree(self) -> None:
        """Detach obsolete readers while retaining this owner's sparse fold preferences."""
        self.trace_tree = None
        self.focused_key = self._top = None
        self._top_line = 0
        self._rows.clear()
        self._strips.clear()
        self._record_layout_cache = None
        self._window_key = None
        self._revealed_ordinal = None
        self.refresh()

    def set_search(self, options: SearchOptions | None) -> None:
        self.search_options = options
        self._window_key = None
        self._record_layout_cache = None
        self.refresh()

    def reveal(self, ordinal: int, *, notify: bool = True) -> None:
        """Reveal one complete record path without retaining a depth-sized fold set."""
        if self.trace_tree is None:
            return
        row = self.trace_tree.row(-(ordinal + 1))
        self._revealed_ordinal = ordinal
        self._fold_revision += 1
        self._window_key = None
        if notify:
            self.select(row)
        else:
            self.focused_key = self._top = row.key
            self._top_line = 0

    def _expanded(self, key: int) -> bool:
        if key < 0:
            return False
        expanded = self.expanded_default != (key in self._exceptions)
        return expanded or (
            self._revealed_ordinal is not None
            and self.trace_tree is not None
            and self.trace_tree.is_ancestor(key, self._revealed_ordinal)
        )

    def _set_expanded(self, key: int, expanded: bool) -> None:
        self._fold_revision += 1
        self._revealed_ordinal = None
        if expanded == self.expanded_default:
            self._exceptions.discard(key)
            identity = self._exception_identities.pop(key, None)
            if identity is not None:
                self._fold_bytes -= 256 + len(identity.encode("utf-8")) * 4
        elif key not in self._exceptions and self.trace_tree is not None:
            identity = self.trace_tree.node_identity(key)
            cost = 256 + len(identity.encode("utf-8")) * 4
            if self._fold_bytes + cost > self.trace_tree.session.limits.working_memory_bytes // 2:
                self.app.notify(
                    "Fold state exceeds working memory; use Fold all to reset.", markup=False
                )
            else:
                self._exceptions.add(key)
                self._exception_identities[key] = identity
                self._fold_bytes += cost

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

    def set_options(self, options: ConsoleOptions) -> None:
        """Apply presentation without losing folds or focused record identity."""
        self.options = options
        self._top_line = 0
        self._window_key = None
        self._record_layout_cache = None
        self._virtual_width = 1
        self.scroll_to(x=0, animate=False)
        self.refresh()

    def _record_layout(self, row: TreeRow) -> _RecordLayout:
        if self._record_layout_cache is not None and self._record_layout_cache[0] == row.key:
            return self._record_layout_cache[1]
        layout = _RecordLayout(
            self._text(row),
            max(1, self.size.width) if self.options.wrap else None,
            self.search_options if row.kind == "record" else None,
        )
        self._record_layout_cache = row.key, layout
        return layout

    def _window(self) -> None:
        key = (
            self._top,
            self._top_line,
            self.size,
            self._fold_revision,
            self.options,
            self.search_options,
            self.scroll_offset.x,
            self.app.current_theme.dark,
        )
        if key == self._window_key:
            return
        self._record_layout_cache = None
        self._window_key = key
        self._rows = []
        self._strips = []
        if self.trace_tree is None or self._top is None:
            return
        row = self.trace_tree.row(self._top)
        line = self._top_line
        retained = 0
        while len(self._rows) < self.size.height:
            layout = self._record_layout(row)
            line = min(line, layout.height - 1)
            while line < layout.height and len(self._rows) < self.size.height:
                text, crop = layout.line(
                    line, 0 if self.options.wrap else self.scroll_offset.x, self.size.width
                )
                strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
                strip = strip.crop(crop, crop + self.size.width)
                cost = resident_size(row.__dict__) + resident_size(strip.text) + 128
                if retained + cost > self.trace_tree.session.limits.page_memory_bytes:
                    break
                retained += cost
                self._rows.append(row)
                self._strips.append(strip)
                line += 1
            if line < layout.height:
                break
            self._virtual_width = max(self._virtual_width, layout.max_width)
            following = self._next(row)
            if following is None:
                break
            row, line = following, 0
        self.virtual_size = Size(
            self.size.width if self.options.wrap else max(self.size.width, self._virtual_width),
            self.size.height,
        )

    def _depth(self, row: TreeRow) -> int:
        assert self.trace_tree is not None
        depth = 0
        while row.parent_key is not None:
            depth += 1
            row = self.trace_tree.row(row.parent_key)
        return depth

    def _text(self, row: TreeRow) -> Text:
        assert self.trace_tree is not None
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
            text.append_text(
                console_text(page.records[0], self.options, light=not self.app.current_theme.dark)
            )
        else:
            text.append("▾ " if self._expanded(row.key) else "▸ ", style="dim")
            text.append(
                visible_text(row.label or row.span_id or row.trace_id or "span"), style="bold"
            )
            if row.kind != "trace":
                text.append(f" · {row.relationship} · {row.lifecycle}", style="dim")
                if row.name_conflict:
                    text.append(" · conflicting names", style="yellow")
                if row.status is not None:
                    text.append(f" · {row.status} · {row.duration_ms}ms", style="dim")
            if row.context_only:
                text.append(" · Ancestor context", style="italic dim")
            if self.trace_tree.scope.population == "filtered":
                text.append(
                    f" · {row.match_count} admitted / {row.record_count} evidence records",
                    style="dim",
                )
            else:
                text.append(f" · {row.record_count} direct records", style="dim")
        return text

    def render_line(self, y: int) -> Strip:
        self._window()
        if y >= len(self._rows):
            return Strip.blank(self.size.width, self.rich_style)
        strip = self._strips[y]
        if self._rows[y].key == self.focused_key:
            strip = strip.apply_style(Style(reverse=True))
        return strip.adjust_cell_length(self.size.width, self.rich_style)

    def on_resize(self) -> None:
        self._top_line = 0
        self._window_key = None
        self._record_layout_cache = None
        self.refresh()

    def select(self, row: TreeRow) -> None:
        self.focused_key = row.key
        self._window()
        if not any(item.key == row.key for item in self._rows):
            self._top = row.key
            self._top_line = 0
        if row.ordinal is not None and self.trace_tree is not None:
            self.post_message(self.Selected(row.ordinal, self.trace_tree))
        self.refresh()

    def action_move(self, direction: int) -> None:
        if self.trace_tree is None or self.focused_key is None:
            return
        row = self.trace_tree.row(self.focused_key)
        following = self._next(row) if direction > 0 else self._previous(row)
        if following is not None:
            self.select(following)

    def action_page(self, direction: int) -> None:
        if not self.options.wrap:
            for _ in range(max(1, self.size.height - 1)):
                self.action_move(direction)
            return
        if self.trace_tree is None or self._top is None:
            return
        row = self.trace_tree.row(self._top)
        line = self._top_line
        for _ in range(max(1, self.size.height - 1)):
            if direction > 0:
                if line + 1 < self._record_layout(row).height:
                    line += 1
                else:
                    following = self._next(row)
                    if following is None:
                        break
                    row, line = following, 0
            elif line > 0:
                line -= 1
            else:
                previous = self._previous(row)
                if previous is None:
                    break
                row = previous
                line = self._record_layout(row).height - 1
        self._top, self._top_line = row.key, line
        self.focused_key = row.key
        if row.ordinal is not None:
            self.post_message(self.Selected(row.ordinal, self.trace_tree))
        self.refresh()

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
        self._revealed_ordinal = None
        self.expanded_default = not self.expanded_default
        self._exceptions.clear()
        self._exception_identities.clear()
        self._fold_bytes = 0
        if not self.expanded_default and self.focused_key is not None:
            row = self.trace_tree.row(self.focused_key)
            while row.parent_key is not None:
                row = self.trace_tree.row(row.parent_key)
            self.focused_key = self._top = row.key
            self._top_line = 0
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
        if event.ctrl or event.shift:
            return
        self.action_page(1)
        event.prevent_default()
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if event.ctrl or event.shift:
            return
        self.action_page(-1)
        event.prevent_default()
        event.stop()
