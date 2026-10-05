"""Compact literal-search interaction; headless jobs own complete matching."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.cells import get_character_cell_size
from rich.style import Style
from rich.text import Span, Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Static

from ..core.encoding import json_spelling
from ..errors import ToolError
from ..investigation.search import (
    SearchJob,
    SearchOptions,
    SearchProjection,
    SearchResult,
    match_ranges,
)
from .input import DraftInput
from .presentation import CONSOLE_FIELDS, HIDDEN_FIELDS
from .text import character_spelling, visible_text

if TYPE_CHECKING:
    from .app import InvestigationApp


def console_projection(show_duration: bool) -> SearchProjection:
    return SearchProjection(
        tuple(sorted(CONSOLE_FIELDS)),
        tuple(sorted(HIDDEN_FIELDS)),
        ("duration_ms",) if show_duration else (),
        (("span", "span_name"),),
    )


class SearchInput(DraftInput):
    def on_key(self, event: events.Key) -> None:
        owner = self.parent.parent if self.parent is not None else None
        if not isinstance(owner, SearchBar):
            return
        actions = {"alt+s": "scope", "alt+c": "case", "alt+w": "word"}
        if event.key in actions:
            owner.toggle(actions[event.key])
        elif event.key in ("enter", "shift+enter"):
            owner.post_message(SearchBar.Navigate(event.key == "shift+enter"))
        else:
            return
        event.stop()
        event.prevent_default()


class SearchBar(Vertical):
    DEFAULT_CSS = """
    SearchBar { height: 2; }
    SearchBar Horizontal { height: 1; }
    SearchBar .search-label { width: 6; height: 1; content-align: center middle; }
    SearchBar Input { width: 1fr; height: 1; border: none; padding: 0 1; }
    SearchBar .search-option { height: 1; width: auto; padding: 0 1; color: $text-muted; }
    SearchBar .search-option:hover { background: $primary-muted; color: $text; }
    SearchBar .search-status { height: 1; padding: 0 1; color: $text-muted; }
    """

    class Changed(Message):
        pass

    class Navigate(Message):
        def __init__(self, previous: bool = False):
            super().__init__()
            self.previous = previous

    def __init__(self):
        super().__init__(id="search-bar")
        self.full_record = False
        self.case_sensitive = False
        self.whole_word = False
        self.status_text = "Empty · F7 search · Enter next · Shift+Enter previous · F3 stream"

    @property
    def text(self) -> str:
        return self.query_one(Input).value

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("Find", classes="search-label", markup=False)
            yield SearchInput(
                placeholder="Literal text; navigate without filtering", id="record-search"
            )
            yield Static("Console", id="search-scope", classes="search-option", markup=False)
            yield Static("Aa off", id="search-case", classes="search-option", markup=False)
            yield Static("Word off", id="search-word", classes="search-option", markup=False)
        yield Static(self.status_text, classes="search-status", markup=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.post_message(self.Changed())

    def toggle(self, option: str) -> None:
        if option == "scope":
            self.full_record = not self.full_record
        elif option == "case":
            self.case_sensitive = not self.case_sensitive
        elif option == "word":
            self.whole_word = not self.whole_word
        self.query_one("#search-scope", Static).update("Full" if self.full_record else "Console")
        self.query_one("#search-case", Static).update(
            f"Aa {'on' if self.case_sensitive else 'off'}"
        )
        self.query_one("#search-word", Static).update(f"Word {'on' if self.whole_word else 'off'}")
        self.post_message(self.Changed())

    def on_click(self, event: events.Click) -> None:
        if event.widget is not None and event.widget.id in (
            "search-scope",
            "search-case",
            "search-word",
        ):
            self.toggle(event.widget.id.removeprefix("search-"))
            event.stop()

    def show_status(self, text: str) -> None:
        self.status_text = text
        self.query_one(".search-status", Static).update(visible_text(text, multiline=True))


def visible_offsets(text: str, start: int, end: int, offset: int, width: int) -> tuple[int, int]:
    left, right, _ = visible_window(text, start, end, offset, width)
    return left, right


def visible_window(
    text: str, start: int, end: int, offset: int, width: int
) -> tuple[int, int, int]:
    """Return source offsets and the first cell, including a partial wide glyph."""
    cells = 0
    left, right, left_cell = end, end, 0
    for position in range(start, end):
        size = get_character_cell_size(text[position])
        if cells + size > offset and left == end:
            left, left_cell = position, cells
        cells += size
        if cells >= offset + width:
            right = position + 1
            break
    return left, right, left_cell if left != end else cells


def highlight_line(
    original: Text,
    start: int,
    end: int,
    options: SearchOptions | None,
    *,
    visible_start: int | None = None,
    visible_end: int | None = None,
    spans: Sequence[Span] | None = None,
) -> Text:
    """Highlight only this visible line, keeping the number of added spans bounded.

    Presentation annotates decoded tokens, so JSON quotes/escapes and punctuation
    cannot introduce matches. Complete source offsets survive wrapping/panning.
    """
    selected = original.spans if spans is None else spans
    line = (
        original[start:end]
        if spans is None
        else Text(
            original.plain[start:end],
            style=original.style,
            justify=original.justify,
            overflow=original.overflow,
            no_wrap=original.no_wrap,
            end=original.end,
            tab_size=original.tab_size,
            spans=[
                Span(max(0, span.start - start), min(end, span.end) - start, span.style)
                for span in selected
                if span.start < end and span.end > start
            ],
        )
    )
    if options is None or not options.text:
        return line
    visible_start = start if visible_start is None else visible_start
    visible_end = end if visible_end is None else visible_end
    style = Style(color="black", bgcolor="yellow", bold=True)
    for span in selected:
        if span.end <= visible_start or span.start >= visible_end:
            continue
        meta = span.style.meta if isinstance(span.style, Style) else {}
        source = meta.get("search_source")
        if not isinstance(source, str):
            continue
        encoded = bool(meta.get("search_json"))
        token_start = span.start
        source_offset = int(meta.get("search_offset", 0))
        ranges = match_ranges(source, options)
        mapped_position, decoded_position = token_start + (1 if encoded else 0), 0
        column = int(meta.get("search_column", 0))
        for first, last in ranges:
            if encoded:
                while decoded_position < first:
                    mapped_position += len(json_spelling(source[decoded_position])[1:-1])
                    decoded_position += 1
                left = mapped_position
                while decoded_position < last:
                    mapped_position += len(json_spelling(source[decoded_position])[1:-1])
                    decoded_position += 1
                right = mapped_position
            elif meta.get("search_rendered"):
                if last <= source_offset:
                    continue
                decoded_position = max(decoded_position, source_offset)
                while decoded_position < max(first, source_offset):
                    fragment, column = character_spelling(
                        source[decoded_position], column, multiline=True
                    )
                    mapped_position += len(fragment)
                    decoded_position += 1
                left = mapped_position
                while decoded_position < last:
                    fragment, column = character_spelling(
                        source[decoded_position], column, multiline=True
                    )
                    mapped_position += len(fragment)
                    decoded_position += 1
                right = mapped_position
            else:
                left, right = (
                    token_start + first - source_offset,
                    token_start + last - source_offset,
                )
            left, right = max(left, visible_start, span.start), min(right, visible_end, span.end)
            if left < right:
                line.stylize(style, left - start, right - start)
            if left >= visible_end:
                break
    return line


def highlight_json_line(text: Text, options: SearchOptions | None, offset: int, width: int) -> Text:
    if options is None or options.scope != "full" or not options.text:
        return text
    left, right = visible_offsets(text.plain, 0, len(text), offset, width)
    for token in re.finditer(
        r'"(?:\\.|[^"\\])*"|true|false|null|NaN|-?Infinity|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?',
        text.plain,
    ):
        if token.end() <= left or token.start() >= right:
            continue
        value = json.loads(token[0])
        source = value if isinstance(value, str) else token[0]
        text.stylize(
            Style(meta={"search_source": source, "search_json": isinstance(value, str)}),
            token.start(),
            token.end(),
        )
    return highlight_line(text, 0, len(text), options, visible_start=left, visible_end=right)


class SearchController:
    """Consumer generations/debounce; no matching or dataset policy lives here."""

    def __init__(self, app: InvestigationApp):
        self.app = app
        self.result: SearchResult | None = None
        self.pending: SearchJob | None = None
        self.generation = 0
        self._dirty_at: float | None = None
        self._blocked = False

    def options(self) -> SearchOptions:
        from .console import ConsoleViewport

        bar = self.app.search_bar
        return SearchOptions(
            bar.text,
            "full" if bar.full_record else "console",
            bar.case_sensitive,
            bar.whole_word,
            console_projection(self.app.query_one(ConsoleViewport).options.show_duration),
        )

    def update(self, reason: str = "Searching", *, blocked: bool = False) -> None:
        from .console import ConsoleViewport

        if not self.app.is_running:
            return
        blocked = blocked or self.app.main_filter.pending_generation is not None
        self.generation += 1
        self._blocked = blocked
        if self.pending:
            self.pending.cancel()
        if self.result:
            try:
                self.result.close()
            except (ToolError, OSError) as error:
                self.app.notify(visible_text(f"Search cleanup failed: {error}"), markup=False)
            self.result = None
        options = self.options()
        self.app.query_one(ConsoleViewport).set_search(options if options.text else None)
        from .tree import TreeViewport

        self.app.query_one(TreeViewport).set_search(options if options.text else None)
        from .inspector import JSONInspector

        self.app.query_one(JSONInspector).set_search(options if options.text else None)
        self._dirty_at = time.monotonic() if options.text and not blocked else None
        self.app.search_bar.show_status(
            (
                f"{reason} · previous match scope invalid · Enter next · "
                "Alt+S scope · Alt+C case · Alt+W word"
            )
            if options.text
            else "Empty · F7 search · Enter next · Shift+Enter previous · F3 stream"
        )

    def refresh(self) -> None:
        if not self.app.is_running:
            return
        job = self.pending
        if job and job.done:
            result = job.wait(0)
            self.pending = None
            if (
                result is not None
                and job.session is self.app.session
                and job.scope.input_scope == self.app.tree_input_scope
                and job.scope.request_generation == self.generation
                and not self._blocked
            ):
                self.result = result
                self.app.search_bar.show_status(
                    f"{result.record_count:,} matching records · applied Main scope · "
                    "Enter next · Shift+Enter previous · Alt+S/C/W options"
                )
            elif result:
                try:
                    result.close()
                except (ToolError, OSError) as error:
                    self.app.notify(visible_text(f"Search cleanup failed: {error}"), markup=False)
            elif job.scope.request_generation == self.generation:
                reason = (
                    "Canceled"
                    if job.status.phase == "cancelled"
                    else (job.diagnostics[0].message if job.diagnostics else "Search failed")
                )
                self.app.search_bar.show_status(reason + " · stream retained")
        if (
            self.pending is not None
            or self._dirty_at is None
            or time.monotonic() - self._dirty_at < 0.15
        ):
            return
        self._dirty_at = None
        try:
            self.pending = self.app.session.search(
                self.options(),
                input_view=self.app.filtered_view,
                request_generation=self.generation,
            )
        except (ToolError, OSError) as error:
            self.app.search_bar.show_status(str(error) + " · stream retained")

    def navigate(self, previous: bool = False) -> None:
        from .console import ConsoleViewport

        if self.result is None:
            return
        ordinal = self.result.neighbor(self.app.selected_ordinal, previous=previous)
        if ordinal is None:
            return
        position = (
            self.app.filtered_view.position_of(ordinal) if self.app.filtered_view else ordinal
        )
        if position is not None:
            if self.app.tree_mode:
                from .tree import TreeViewport

                self.app.query_one(TreeViewport).reveal(ordinal)
            else:
                self.app.query_one(ConsoleViewport).select(position)

    def cancel(self) -> None:
        if self.pending is None and self._dirty_at is None:
            return
        self.generation += 1
        self._dirty_at = None
        if self.pending:
            self.pending.cancel()
        self.app.search_bar.show_status("Canceled · stream retained")
