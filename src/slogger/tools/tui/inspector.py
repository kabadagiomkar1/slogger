"""Complete native JSON presentation with exact IXR-compatible key targets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rich.cells import cell_len
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..core.encoding import json_spelling
from ..investigation.search import SearchOptions
from .search import highlight_json_line


@dataclass(frozen=True)
class JSONKeyTarget:
    """A displayed key and its exact Field.path, or explicit targeting guidance."""

    line: int
    label: str
    path: tuple[str, ...] | None
    guidance: str | None = None


class JSONInspector(ScrollView, can_focus=True):
    """Complete parsed JSON; highlight only the visible lines on demand."""

    BINDINGS = [
        Binding("l", "line_numbers", "JSON lines"),
        Binding("j", "key(1)", "Next key"),
        Binding("k", "key(-1)", "Previous key"),
        Binding("enter", "field", "Select field"),
    ]

    class KeySelected(Message, namespace="json_inspector"):
        def __init__(
            self, target: JSONKeyTarget, binding: tuple[str | None, int] = (None, 0)
        ) -> None:
            super().__init__()
            self.target = target
            self.binding = binding

    class FieldRequested(Message, namespace="json_inspector"):
        def __init__(
            self, path: tuple[str, ...], binding: tuple[str | None, int] = (None, 0)
        ) -> None:
            super().__init__()
            self.path = path
            self.binding = binding

    def __init__(self) -> None:
        super().__init__(id="json")
        self.binding: tuple[str | None, int] = (None, 0)
        self.line_numbers = False
        self.search_options: SearchOptions | None = None
        self.document = ""
        self._lines: list[str] = []
        self.key_targets: list[JSONKeyTarget] = []
        self.selected_target: JSONKeyTarget | None = None

    def set_search(self, options: SearchOptions | None) -> None:
        self.search_options = options
        self.refresh()

    def set_record(self, record: dict[str, object] | None) -> None:
        self.document = (
            json.dumps(record, indent=2, ensure_ascii=False) if record is not None else ""
        )
        self._lines = json_spelling(record, indent=2).split("\n") if record is not None else []
        self.key_targets = self._targets()
        self.selected_target = None
        self._update_size()
        self.scroll_to(x=0, y=0, animate=False)
        self.refresh()

    @property
    def selected_path(self) -> tuple[str, ...] | None:
        return self.selected_target.path if self.selected_target else None

    def _targets(self) -> list[JSONKeyTarget]:
        # Parse the complete pretty representation's container boundaries. Mapping
        # keys inside arrays cannot be represented by IXR's mapping-only paths.
        frames: list[tuple[str, tuple[str, ...] | None, str, str | None]] = []
        targets: list[JSONKeyTarget] = []
        for line, text in enumerate(self._lines):
            stripped = text.strip().rstrip(",")
            path: tuple[str, ...] | None = ()
            label = ""
            guidance = None
            if frames:
                kind, path, label, guidance = frames[-1]
                if kind == "[":
                    path = None
                    label += "[]"
                    guidance = (
                        "IXR paths cannot traverse array items; select the containing array key."
                    )
            match = re.match(r'^\s*("(?:\\.|[^"\\])*")\s*:', text)
            if match:
                key = json.loads(match[1])
                label += "[" + match[1] + "]"
                if not key:
                    path = None
                    guidance = (
                        "IXR requires nonempty path components; this key has an empty component."
                    )
                elif path is not None:
                    path += (key,)
                targets.append(JSONKeyTarget(line, label, path, guidance))
            if stripped.endswith(("{", "[")):
                frames.append((stripped[-1], path, label, guidance))
            elif stripped in ("}", "]") and frames:
                frames.pop()
        return targets

    def _select_target(self, target: JSONKeyTarget) -> None:
        self.selected_target = target
        top = self.scroll_offset.y
        if target.line < top:
            self.scroll_to(y=target.line, animate=False)
        elif target.line >= top + self.size.height:
            self.scroll_to(y=target.line - self.size.height + 1, animate=False)
        self.refresh()
        self.post_message(self.KeySelected(target, self.binding))

    def action_key(self, direction: int) -> None:
        if not self.key_targets:
            return
        index = self.key_targets.index(self.selected_target) if self.selected_target else -1
        if index == -1 and direction < 0:
            index = len(self.key_targets)
        index = min(max(index + direction, 0), len(self.key_targets) - 1)
        self._select_target(self.key_targets[index])

    def action_field(self) -> None:
        if self.selected_path is not None:
            self.post_message(self.FieldRequested(self.selected_path, self.binding))
        elif self.selected_target:
            self.post_message(self.KeySelected(self.selected_target, self.binding))

    def on_click(self, event: events.Click) -> None:
        self.focus()
        line = event.y + self.scroll_offset.y
        for target in self.key_targets:
            if target.line == line:
                self._select_target(target)
                break

    def _update_size(self) -> None:
        gutter = len(str(len(self._lines))) + 1 if self.line_numbers else 0
        self.virtual_size = Size(
            max((cell_len(line) for line in self._lines), default=1) + gutter,
            len(self._lines),
        )

    def action_line_numbers(self) -> None:
        self.line_numbers = not self.line_numbers
        self._update_size()
        self.refresh()

    def render_line(self, y: int) -> Strip:
        line = y + self.scroll_offset.y
        if line >= len(self._lines):
            return Strip.blank(self.size.width, self.rich_style)
        text = Syntax(
            self._lines[line],
            "json",
            theme="github-dark" if self.app.current_theme.dark else "friendly",
            background_color=self.rich_style.bgcolor.name if self.rich_style.bgcolor else "default",
        ).highlight(self._lines[line])
        # Pygments ensures a trailing newline even for a single input line. A
        # viewport strip must never move the terminal cursor to another row.
        text.rstrip()
        text = highlight_json_line(text, self.search_options, self.scroll_offset.x, self.size.width)
        if self.selected_target and self.selected_target.line == line:
            text.stylize("reverse")
        if self.line_numbers:
            number = Text(f"{line + 1:>{len(str(len(self._lines)))}} ", style="dim")
            number.append_text(text)
            text = number
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)
