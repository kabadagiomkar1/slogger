# /// script
# requires-python = ">=3.10"
# dependencies = ["textual==8.2.8"]
# ///
"""THROWAWAY native terminal prototype. Run with uv run --with-editable . <path>."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from pathlib import Path

from native_query import CORE_FIELDS, completions, console_record, filter_store, search_store
from native_store import Store, connect, demo_files, open_capture, path_spelling, size_of
from native_ui import (
    AggregatePane,
    JSONInspector,
    Preferences,
    QueryInput,
    ToggleChip,
    aggregate_preview,
    get_value,
)
from rich.style import Style
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Label, OptionList, Select, Static


def console_column(value, width, style):
    column = Text(value, style=style)
    column.truncate(width, overflow="ellipsis")
    column.align("left", width)
    return column


class LogViewport(ScrollView):
    """Render viewport lines only. Record data lives in Store, not widget cells."""

    can_focus = True
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
        Binding("home", "edge(False)", show=False),
        Binding("end", "edge(True)", show=False),
        Binding("left", "pan(-12)", show=False),
        Binding("right", "pan(12)", show=False),
        Binding("space", "fold", show=False),
        Binding("shift+space", "fold_all", show=False),
    ]

    def __init__(self):
        super().__init__(id="logs")
        self.cursor = 0
        self.tree_rows = None
        self.folded = set()
        self.wrap_rows = False
        self._shown_tree = []
        self.field_ranges = {}

    @property
    def factor(self):
        return 3 if self.wrap_rows else 1

    @property
    def count(self):
        if self.tree_rows is not None:
            return len(self._shown_tree)
        return self.app.store.view_count if self.app.store else 0

    def selected(self):
        if not self.count or not self.app.store:
            return None
        if self.tree_rows is not None:
            return self._shown_tree[self.cursor]["rid"]
        return self.app.store.row_id(self.cursor)

    def reset_size(self):
        if self.tree_rows is not None:
            self._shown_tree = [
                row
                for row in self.tree_rows
                if not any(key in self.folded for key in row["ancestors"])
            ]
        self.cursor = max(0, min(self.cursor, self.count - 1))
        estimated_width = (
            min(4000, self.app.store.manifest.get("max_record_bytes", 1000))
            if self.app.store
            else 1000
        )
        self.virtual_size = Size(
            self.size.width if self.wrap_rows else max(self.size.width, estimated_width),
            max(1, self.count * self.factor),
        )
        self.refresh()

    def choose(self, position):
        self.cursor = max(0, min(position, self.count - 1))
        y = self.cursor * self.factor
        if y < self.scroll_offset.y:
            self.scroll_to(y=y, animate=False)
        elif y + self.factor > self.scroll_offset.y + self.size.height - 1:
            self.scroll_to(y=max(0, y - self.size.height + self.factor + 1), animate=False)
        self.refresh()
        self.app.show_selected()

    def action_move(self, amount):
        self.choose(self.cursor + amount)

    def action_page(self, direction):
        self.choose(self.cursor + direction * max(1, self.size.height // self.factor - 1))

    def action_edge(self, end):
        self.choose(self.count - 1 if end else 0)

    def action_pan(self, amount):
        if self.tree_rows is not None and self.count:
            row = self._shown_tree[self.cursor]
            key = row.get("key")
            if key:
                if (amount < 0 and key not in self.folded) or (amount > 0 and key in self.folded):
                    self.action_fold()
                    return
                if amount > 0:
                    self.choose(self.cursor + 1)
                    return
            if amount < 0 and row["ancestors"]:
                parent = row["ancestors"][-1]
                for position, candidate in enumerate(self._shown_tree):
                    if candidate.get("key") == parent:
                        self.choose(position)
                        return
        if not self.wrap_rows:
            self.scroll_to(x=max(0, self.scroll_offset.x + amount), animate=False)

    def action_fold(self):
        if self.tree_rows is None or not self.count:
            return
        row = self._shown_tree[self.cursor]
        key = row.get("key") or (row["ancestors"][-1] if row["ancestors"] else None)
        if key:
            self.folded.symmetric_difference_update({key})
            self.reset_size()
            self.choose(self.cursor)

    def action_fold_all(self):
        if self.tree_rows is not None:
            self.folded = (
                set() if self.folded else {row["key"] for row in self.tree_rows if row.get("key")}
            )
            self.reset_size()
            self.choose(0)

    def on_resize(self):
        self.reset_size()

    def on_click(self, event: events.Click):
        self.focus()
        position = (int(event.y) + self.scroll_offset.y) // self.factor
        self.choose(position)
        row = (
            self._shown_tree[position]
            if self.tree_rows is not None and position < self.count
            else None
        )
        if row and row.get("key"):
            self.action_fold()
            return
        field = event.style.meta.get("field")
        if field:
            self.app.open_aggregate(tuple(field))
            return
        logical_x = int(event.x) + self.scroll_offset.x
        if self.wrap_rows:
            logical_x += ((int(event.y) + self.scroll_offset.y) % self.factor) * self.size.width
        for start, end, path in self.field_ranges.get(position, []):
            if start <= logical_x < end:
                self.app.open_aggregate(path)
                break

    def render_line(self, y):
        width = self.size.width
        logical_y = y + self.scroll_offset.y
        position, wrapped_line = divmod(logical_y, self.factor)
        if position >= self.count or not self.app.store:
            return Strip.blank(width, self.rich_style)
        tree_row = self._shown_tree[position] if self.tree_rows is not None else None
        rid = tree_row["rid"] if tree_row else self.app.store.row_id(position)
        if tree_row and tree_row["kind"] != "record":
            indicator = "▸" if tree_row.get("key") in self.folded else "▾"
            text = Text(
                "  " * tree_row["depth"] + indicator + " " + tree_row["label"],
                style="bold " + self.app.palette["accent"],
            )
        else:
            record, _, _ = self.app.store.record(rid)
            level = str(record.get("level", "?"))
            color = self.app.palette[
                "error" if level == "ERROR" else "warn" if level == "WARN" else "info"
            ]
            text = Text("  " * (tree_row["depth"] if tree_row else 0))
            text.append("▸ " if position == self.cursor else "  ", style=self.app.palette["accent"])
            source = self.app.store.record(rid)[1]
            ordinal = next(
                i + 1
                for i, file in enumerate(self.app.store.manifest["files"])
                if file["path"] == source
            )
            source_width = max(2, len(str(len(self.app.store.manifest["files"]))))
            text.append(f"{ordinal:0{source_width}} │ ", style=self.app.palette["muted"])
            stamp = str(record.get("timestamp", "—"))
            if self.app.timestamp_mode == "time":
                stamp = stamp[11:19] if "T" in stamp else stamp
            elif self.app.timestamp_mode == "date":
                stamp = stamp[:19].replace("T", " ")
            stamp_width = {"time": 8, "date": 19, "raw": 40}[self.app.timestamp_mode]
            text.append(console_column(stamp, stamp_width, self.app.palette["muted"]))
            text.append(" ")
            text.append(console_column(level, 8, color))
            text.append(" ")
            text.append(
                console_column(
                    str(record.get("logger", "—")),
                    self.app.logger_width,
                    self.app.palette["accent"],
                )
            )
            text.append("  ")
            text.append(str(record.get("message", "—")))
            ranges = []
            if record.get("span_name"):
                start = text.cell_len
                text.append(
                    " [" + str(record["span_name"]) + "]",
                    style=Style(color=self.app.palette["span"], meta={"field": ("span_name",)}),
                )
                ranges.append((start, text.cell_len, ("span_name",)))
            custom = {
                k: v
                for k, v in console_record(record, self.app.show_duration).items()
                if k not in CORE_FIELDS | {"span_name"}
            }
            for key, value in custom.items():
                text.append("  ")
                start = text.cell_len
                text.append(
                    key + "=", style=Style(color=self.app.palette["field"], meta={"field": (key,)})
                )
                text.append(
                    str(value)
                    if isinstance(value, str)
                    else json.dumps(value, separators=(",", ":")),
                    style=Style(color=self.app.palette["value"], meta={"field": (key,)}),
                )
                ranges.append((start, text.cell_len, (key,)))
            self.field_ranges[position] = ranges
            if len(self.field_ranges) > 300:
                self.field_ranges = {position: ranges}
            # Deliberately cap visual rendering, while search/copy use full data.
            if len(text) > 4000:
                text = text[:3990] + Text(" … JSON")
        if position == self.cursor:
            text.stylize("on " + self.app.palette["selected"])
        pattern = self.app.search_pattern()
        if pattern:
            text.highlight_regex(pattern, style=self.app.palette["match"])
        if self.wrap_rows:
            pieces = text.wrap(self.app.console, max(1, width), overflow="fold")
            text = pieces[wrapped_line] if wrapped_line < len(pieces) else Text("")
            if wrapped_line == 2 and len(pieces) > 3:
                text = text[: max(0, width - 8)] + Text(" … JSON", style=self.app.palette["warn"])
            strip = Strip(text.render(self.app.console))
        else:
            strip = Strip(text.render(self.app.console)).crop(
                self.scroll_offset.x, self.scroll_offset.x + width
            )
        return strip.apply_style(self.rich_style).adjust_cell_length(width, self.rich_style)


class NativeTUI(App):
    TITLE = "IXR · native prototype"
    CSS = """
    Screen { background: $background; color: $foreground; }
    #title { height: 2; background: $surface; color: $primary; padding: 0 1; }
    #filter-row { height: 1; margin: 0 1; background: $panel; }
    .input-label { width: 8; color: $text-muted; }
    Input { height: 1; border: none; padding: 0 1; background: $panel; }
    Input:focus { background: $primary 12%; }
    #filter { width: 1fr; }
    #suggestions, #aggregate-suggestions { height: 3; max-height: 5; margin: 0 1; border: none;
                   padding: 0 1; background: $surface; }
    #aggregate-suggestions { display: none; margin: 0; }
    #search-row { height: 1; margin: 1 1 0 1; }
    #search { width: 1fr; }
    Button { height: 1; min-width: 3; width: auto; padding: 0 1; border: none;
             background: $surface; color: $text-muted; }
    Button:hover { background: $primary 20%; color: $foreground; }
    Button.enabled { background: $primary 22%; color: $primary; text-style: bold; }
    #search-row Button { margin-left: 1; }
    #controls { height: 1; margin: 1 1 0 1; }
    #controls Button { margin-right: 1; }
    #body { height: 1fr; margin-top: 1; }
    #main { width: 1fr; height: 1fr; }
    #view-heading { height: 1; color: $text-muted; padding: 0 1; }
    #logs { width: 1fr; height: 1fr; scrollbar-size: 1 1; border: none; }
    #logs:focus { border: none; }
    #inspector { width: 28%; min-width: 28; border-left: solid $panel; background: $surface; }
    #inspector-title { height: 1; color: $primary; padding: 0 1; }
    #json { height: 1fr; border: none; background: $surface; scrollbar-size: 1 1; }
    #origin { height: 1; color: $primary; padding: 0 1; }
    #status { height: 1; color: $text-muted; padding: 0 1; }
    Footer { background: $surface; }
    #aggregate { display: none; height: 14; border-top: solid $primary;
                 background: $surface; padding: 0 1; }
    .aggregate-heading { height: 1; margin-bottom: 1; }
    .section-label { width: 12; color: $primary; text-style: bold; }
    #aggregate-scope { width: 1fr; color: $text-muted; }
    .aggregate-inputs { height: 1; margin-bottom: 1; }
    .aggregate-inputs .input-label { width: 6; }
    #aggregate-field { width: 20; }
    #aggregate-mode { width: 22; height: 1; border: none; }
    #aggregate-group { width: 1fr; }
    #aggregate-filter { width: 1fr; }
    #aggregate-scroll { height: 1fr; }
    #aggregate-results { height: auto; }
    #aggregate-note { height: 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "filter", "Filter"),
        Binding("slash", "search", "Search"),
        Binding("n", "next_match", "Next"),
        Binding("N", "previous_match", "Previous", show=False),
        Binding("i", "inspector", "JSON"),
        Binding("t", "tree", "Tree"),
        Binding("a", "aggregate", "Aggregate"),
        Binding("d", "timestamp", "Date", show=False),
        Binding("w", "wrap", "Wrap"),
        Binding("p", "pin", "Pin", show=False),
        Binding("c", "copy", "Copy", show=False),
        Binding("left_square_bracket", "narrow", show=False),
        Binding("right_square_bracket", "widen", show=False),
        Binding("comma", "settings", "Settings"),
        Binding("ctrl+r", "refresh_data", "Refresh"),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(self, paths, cache_root, ram_mib=32, disk_gb=10):
        super().__init__()
        self.register_theme(
            Theme(
                name="ixr-dark",
                primary="#8fb9d7",
                secondary="#83bfa5",
                accent="#d6b977",
                background="#131b24",
                surface="#192430",
                panel="#202e3c",
                foreground="#d5dee7",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                name="ixr-light",
                primary="#255c87",
                secondary="#276c53",
                accent="#846000",
                background="#f4f6f8",
                surface="#e8edf2",
                panel="#dce4eb",
                foreground="#233446",
                dark=False,
            )
        )
        self.paths = paths
        self.cache_root = Path(cache_root)
        self.ram_mib = ram_mib
        self.disk_gb = disk_gb
        self.store = None
        self.complete = False
        self.applied_filter = ""
        self.cancel_event = threading.Event()
        self.generation = 0
        self.operation = ""
        self.pinned = None
        self.matches = 0
        self.tree_busy = False
        self.inspector_percent = 28
        self.inspector_override = False
        self._progress_tick = 0
        self.last_metrics = None
        self.timestamp_mode = "time"
        self.show_duration = False
        self.search_timer = None
        self.aggregate_timer = None
        self.aggregate_generation = 0
        self.aggregate_cancel = threading.Event()
        self.suggestion_start = 0
        self.suggestion_choices = []
        self.navigate_after_search = False
        self.logger_width = 20
        self.completion_states = {}

    def compose(self) -> ComposeResult:
        yield Static(
            "IXR  /  INVESTIGATION\nNative terminal prototype · console + record inspector",
            id="title",
        )
        with Horizontal(id="filter-row"):
            yield Label("FILTER", classes="input-label")
            yield QueryInput(
                placeholder='level = "ERROR" and amount >= 100',
                id="filter",
                compact=True,
                select_on_focus=False,
            )
            yield Button("Clear", id="clear-filter", compact=True, flat=True)
        yield OptionList(id="suggestions", compact=True, markup=False)
        with Horizontal(id="search-row"):
            yield Label("SEARCH", classes="input-label")
            yield Input(
                placeholder="Type to highlight · Enter / n / N to navigate",
                id="search",
                compact=True,
                select_on_focus=False,
            )
            yield ToggleChip("Full record", id="full")
            yield ToggleChip("Case", id="case")
            yield ToggleChip("Word", id="word")
        with Horizontal(id="controls"):
            for label, key in [
                ("Console / Tree t", "toggle-tree"),
                ("JSON i", "toggle-json"),
                ("Agg a", "toggle-aggregate"),
                ("Fold", "fold-all"),
                ("Expand", "expand-all"),
                ("Date d", "toggle-date"),
                ("Prefs ,", "settings"),
            ]:
                yield Button(label, id=key, compact=True, flat=True)
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield Static("CONSOLE  ·  click a user field to aggregate", id="view-heading")
                yield LogViewport()
                yield AggregatePane()
            with Vertical(id="inspector"):
                yield Static("RECORD  ·  JSON", id="inspector-title")
                yield JSONInspector()
        yield Static("Opening supplied files…", id="origin")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        self.theme = "ixr-dark"
        self.load_settings()
        self.query_one("#suggestions").display = False
        self.viewport.focus()
        self.start_capture()

    @property
    def dark(self):
        return self.theme != "ixr-light"

    @property
    def palette(self):
        if self.dark:
            return {
                "accent": "#8fb9d7",
                "muted": "#8094a7",
                "field": "#a3b4c4",
                "value": "#d5dee7",
                "span": "#a6a0c3",
                "selected": "#26394b",
                "match": "bold #18202a on #e5c875",
                "error": "#ed8690",
                "warn": "#d5b676",
                "info": "#86b69e",
            }
        return {
            "accent": "#255c87",
            "muted": "#5f7082",
            "field": "#435e76",
            "value": "#233446",
            "span": "#72558f",
            "selected": "#cddfeb",
            "match": "bold #312404 on #e9cd75",
            "error": "#ac3040",
            "warn": "#866000",
            "info": "#276c53",
        }

    def set_theme(self, name):
        self.theme = name
        self.viewport.refresh()
        inspector = self.query_one(JSONInspector)
        inspector.set_record(inspector.record, preserve_scroll=True)

    def search_pattern(self):
        text = self.query_one("#search", Input).value
        if not text:
            return None
        flags = 0 if self.query_one("#case", ToggleChip).value else re.IGNORECASE
        whole = self.query_one("#word", ToggleChip).value
        return re.compile(
            (r"(?<!\w)" if whole else "") + re.escape(text) + (r"(?!\w)" if whole else ""), flags
        )

    def update_view_heading(self):
        name = "TREE" if self.viewport.tree_rows is not None else "CONSOLE"
        count = self.store.view_count if self.store else 0
        self.query_one("#view-heading", Static).update(
            Text(
                f"{name}  ·  {count:,} records  ·  "
                + (
                    "click a span to fold · ← / → navigate"
                    if name == "TREE"
                    else "click a user field to aggregate"
                )
            )
        )
        button = self.query_one("#toggle-tree", Button)
        button.set_class(name == "TREE", "enabled")
        button.label = "Tree t" if name == "TREE" else "Console t"
        for key in ("fold-all", "expand-all"):
            self.query_one("#" + key).display = name == "TREE"

    def action_timestamp(self):
        modes = ["time", "date", "raw"]
        self.timestamp_mode = modes[(modes.index(self.timestamp_mode) + 1) % len(modes)]
        self.query_one("#toggle-date", Button).set_class(self.timestamp_mode != "time", "enabled")
        self.viewport.refresh()

    def action_aggregate(self):
        pane = self.query_one(AggregatePane)
        pane.display = not pane.display
        self.query_one("#toggle-aggregate", Button).set_class(pane.display, "enabled")
        if pane.display:
            self.schedule_aggregate()

    def open_aggregate(self, path):
        if not self.complete:
            return
        pane = self.query_one(AggregatePane)
        pane.display = True
        self.query_one("#toggle-aggregate", Button).add_class("enabled")
        spelling = path_spelling(path)
        self.query_one("#aggregate-field", Input).value = spelling
        rid = self.pinned or self.viewport.selected()
        record = self.store.record(rid)[0] if rid else {}
        _, value = get_value(record, path)
        self.query_one("#aggregate-mode", Select).value = (
            "numeric"
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else "counts"
        )
        self.query_one("#aggregate-group", Input).value = ""
        self.schedule_aggregate()

    @on(Input.Submitted, "#aggregate-field, #aggregate-group, #aggregate-filter")
    def aggregate_submitted(self):
        self.schedule_aggregate()

    @on(Select.Changed, "#aggregate-mode")
    def aggregate_mode_changed(self):
        if self.is_mounted:
            self.schedule_aggregate()

    def schedule_aggregate(self):
        if not self.is_mounted or not self.complete or not self.query_one(AggregatePane).display:
            return
        if self.operation == "capture" or (
            self.operation == "filter" and self.query_one(AggregatePane).follow
        ):
            return
        if self.aggregate_timer:
            self.aggregate_timer.stop()
        self.aggregate_timer = self.set_timer(0.08, self.start_aggregate)

    def start_aggregate(self):
        if self.operation == "capture" or (
            self.operation == "filter" and self.query_one(AggregatePane).follow
        ):
            return
        self.aggregate_cancel.set()
        self.aggregate_cancel = threading.Event()
        self.aggregate_generation += 1
        pane = self.query_one(AggregatePane)
        query = (
            self.applied_filter if pane.follow else self.query_one("#aggregate-filter", Input).value
        )
        if pane.follow:
            self.query_one("#aggregate-filter", Input).value = query
        self.query_one("#aggregate-scope", Static).update(
            Text(
                ("Following main" if pane.follow else "Independent")
                + " · "
                + (query or "all records")
            )
        )
        self.query_one("#aggregate-note", Static).update("Calculating…")
        self.run_aggregate(
            self.aggregate_generation,
            self.aggregate_cancel,
            self.store,
            self.query_one("#aggregate-field", Input).value,
            self.query_one("#aggregate-group", Input).value,
            self.query_one("#aggregate-mode", Select).value,
            pane.follow,
            query,
        )

    @work(thread=True, exit_on_error=False)
    def run_aggregate(self, generation, cancel, store, field, group, mode, follow, query):
        try:
            table, note = aggregate_preview(store, field, group, mode, follow, query, cancel)
            self.call_from_thread(self.aggregate_finished, generation, table, note)
        except Exception as exc:
            self.call_from_thread(self.aggregate_finished, generation, None, str(exc))

    def aggregate_finished(self, generation, table, note):
        if generation != self.aggregate_generation:
            return
        if table is not None:
            self.query_one("#aggregate-results", Static).update(table)
        else:
            self.query_one("#aggregate-results", Static).update(
                Text("Choose a scalar field for counts or a numeric field for a summary.")
            )
        self.query_one("#aggregate-note", Static).update(Text(note))

    def clear_unused_cache(self):
        import shutil

        from native_store import lock

        removed = 0
        for entry in self.cache_root.glob("dataset-*"):
            lease = lock(entry / "lease.lock")
            if lease:
                shutil.rmtree(entry)
                lease.close()
                removed += 1
        self.notify(f"Removed {removed} unused datasets; active data retained")

    @property
    def viewport(self):
        return self.query_one(LogViewport)

    def status(self, text):
        self.query_one("#status", Static).update(Text(text))
        self.query_one("#status", Static).tooltip = text

    def progress(self, label, done, total, count, generation=None):
        now = time.monotonic()
        if now - self._progress_tick < 0.15 and done != total:
            return
        self._progress_tick = now
        generation = self.generation if generation is None else generation
        self.call_from_thread(self.update_progress, generation, label, done, total, count)

    def update_progress(self, generation, label, done, total, count):
        if generation != self.generation:
            return
        pct = done / max(1, total) * 100
        self.status(
            f"{label} {pct:5.1f}% · {count:,} records · Esc cancels\n"
            f"Applied filter: {self.applied_filter or '(all records)'}"
        )
        if not self.complete and self.store and label == "Capturing":
            self.store.count = self.store.view_count = count
            self.viewport.reset_size()

    def start_capture(self):
        if self.operation:
            self.notify("Cancel the current operation before refresh")
            return
        self.aggregate_cancel.set()
        self.aggregate_generation += 1
        if self.aggregate_timer:
            self.aggregate_timer.stop()
        if self.store and not self.complete:
            self.store.close()
            self.store = None
            self.viewport.tree_rows = None
            self.viewport.reset_size()
        self.generation += 1
        self.cancel_event = threading.Event()
        self.operation = "capture"
        self.capture(self.generation, self.cancel_event)

    @work(thread=True, exit_on_error=False)
    def capture(self, generation, cancel):
        try:

            def partial(directory, manifest):
                self.call_from_thread(self.attach_partial, generation, directory, manifest)

            store, metrics = open_capture(
                self.paths,
                self.cache_root,
                cancel,
                lambda *args: self.progress(*args, generation=generation),
                partial,
                self.disk_gb,
                self.ram_mib,
                active_store=self.store if self.complete else None,
            )
            self.call_from_thread(self.capture_finished, generation, store, metrics)
        except Exception as exc:
            self.call_from_thread(self.failed, generation, str(exc))

    def attach_partial(self, generation, directory, manifest):
        if generation != self.generation or self.complete:
            return
        if self.store:
            self.store.close()
        self.store = Store(directory, manifest, ram_mib=self.ram_mib, disk_gb=self.disk_gb)
        self.viewport.reset_size()
        self.viewport.choose(0)

    def capture_finished(self, generation, store, metrics):
        if generation != self.generation:
            store.close()
            return
        selected = self.viewport.selected() if self.store else None
        identity = self.store.record(selected) if selected else None
        if self.store:
            if self.store.directory == store.directory and store.lease is None:
                store.lease = self.store.lease
                self.store.lease = None
            self.store.close()
        self.store = store
        logger_values = store.manifest.get("samples", {}).get("logger", {})
        self.logger_width = min(
            28, max(12, max((Text(str(json.loads(v))).cell_len for v in logger_values), default=20))
        )
        self.complete = True
        self.operation = ""
        self.last_metrics = metrics
        self.viewport.tree_rows = None
        self.viewport.reset_size()
        self.update_view_heading()
        restored = False
        if identity and selected <= store.count and store.record(selected) == identity:
            self.viewport.choose(selected - 1)
            restored = True
        else:
            self.viewport.choose(0)
        self.pinned = None
        self.status(
            f"{metrics['mode']} · {metrics['seconds']:.2f}s · {store.count:,} records · "
            f"{store.manifest['skipped']:,} skipped · complete\n"
            + (
                "Selection verified."
                if restored
                else "Selection reset; pins reset on prototype refresh."
            )
        )
        self.update_suggestions()
        if self.applied_filter:
            self.start_filter(self.applied_filter)
        else:
            self.schedule_aggregate()

    def failed(self, generation, message):
        if generation != self.generation:
            return
        self.operation = ""
        if self.store and not self.complete and self.store.lease is None:
            from native_store import lock

            self.store.lease = lock(self.store.directory / "lease.lock")
        self.status(
            "Stopped: "
            + message
            + "\n"
            + (
                "Previous complete dataset remains usable."
                if self.complete
                else "Partial capture: browsing/JSON only. Refresh to retry."
            )
        )
        if self.complete:
            self.schedule_aggregate()

    def ready(self):
        if not self.complete:
            self.notify("Wait for complete capture; browsing and JSON are available now")
            return False
        if self.operation == "capture":
            self.notify("Refresh is running; previous view remains usable")
            return False
        return True

    def show_selected(self):
        rid = self.pinned or self.viewport.selected()
        if not rid or not self.store:
            self.query_one(JSONInspector).set_record({})
            return
        record, source, line = self.store.record(rid)
        self.query_one(JSONInspector).set_record(record)
        self.query_one("#inspector-title", Static).update(
            "JSON · pinned · valid" if self.pinned else "JSON · valid · click key"
        )
        self.query_one("#origin", Static).update(
            Text(
                f"{Path(source).name}:{line}  · record {rid:,} · "
                f"view {self.viewport.cursor + 1:,}/{self.viewport.count:,}"
                + (" · INCOMPLETE CAPTURE" if not self.complete else "")
            )
        )
        self.query_one("#origin", Static).tooltip = source

    @on(Input.Changed, "#filter, #aggregate-filter")
    def query_changed(self, event):
        self.update_suggestions(event.input.id)

    def completion_menu(self, key):
        return self.query_one(
            "#aggregate-suggestions" if key == "aggregate-filter" else "#suggestions", OptionList
        )

    def update_suggestions(self, key="filter"):
        samples = self.store.manifest.get("samples", {}) if self.store else {}
        widget = self.query_one("#" + key, Input)
        start, choices = completions(widget.value[: widget.cursor_position], samples)
        self.completion_states[key] = (start, choices)
        if key == "filter":
            self.suggestion_start = start
            self.suggestion_choices = choices
        menu = self.completion_menu(key)
        menu.tooltip = "Sampled keys and values · ↑/↓ selects · Tab or click inserts"
        menu.clear_options()
        menu.add_options([Text(choice, style=self.palette["accent"]) for choice in choices])
        menu.highlighted = 0 if choices else None
        menu.display = bool(choices) and widget.has_focus and not widget.disabled

    def move_suggestion(self, direction, key="filter"):
        menu = self.completion_menu(key)
        _, choices = self.completion_states.get(key, (0, []))
        if choices:
            menu.highlighted = ((menu.highlighted or 0) + direction) % len(choices)
            menu.scroll_to_highlight()

    def complete_query(self, key="filter"):
        widget = self.query_one("#" + key, Input)
        if not self.completion_states.get(key, (0, []))[1]:
            self.update_suggestions(key)
        start, choices = self.completion_states.get(key, (0, []))
        index = self.completion_menu(key).highlighted or 0
        if choices:
            completed = widget.value[:start] + choices[index]
            widget.value = completed + widget.value[widget.cursor_position :]
            widget.cursor_position = len(completed)
            widget.focus()

    @on(OptionList.OptionSelected, "#suggestions, #aggregate-suggestions")
    def selected_suggestion(self, event):
        self.complete_query(
            "aggregate-filter" if event.option_list.id == "aggregate-suggestions" else "filter"
        )

    def on_descendant_focus(self, event):
        if self.is_mounted and event.widget.id in ("filter", "aggregate-filter"):
            self.update_suggestions(event.widget.id)

    def on_descendant_blur(self, event):
        if self.is_mounted and event.widget.id in ("filter", "aggregate-filter"):
            self.call_later(self.hide_suggestions, event.widget.id)

    def hide_suggestions(self, key="filter"):
        menu = self.completion_menu(key)
        if self.focused not in (self.query_one("#" + key), menu):
            menu.display = False

    @on(Input.Submitted, "#filter")
    def submit_filter(self, event):
        if self.ready():
            self.start_filter(event.value)
            self.viewport.focus()

    def begin_operation(self, label):
        self.cancel_event.set()
        self.cancel_event = threading.Event()
        self.generation += 1
        self.operation = label
        return self.generation, self.cancel_event

    def start_filter(self, query):
        if self.query_one(AggregatePane).follow:
            self.aggregate_cancel.set()
            self.aggregate_generation += 1
            if self.aggregate_timer:
                self.aggregate_timer.stop()
        generation, cancel = self.begin_operation("filter")
        self.status("Filter pending; previous successful view retained · Esc cancels")
        self.run_filter(generation, cancel, self.store, query)

    @work(thread=True, exit_on_error=False)
    def run_filter(self, generation, cancel, store, query):
        try:
            name, count = filter_store(
                store,
                query,
                cancel,
                lambda *args: self.progress(*args, generation=generation),
            )
            self.call_from_thread(self.filter_finished, generation, store, name, count, query)
        except Exception as exc:
            self.call_from_thread(self.failed, generation, str(exc))

    def filter_finished(self, generation, store, name, count, query):
        if generation != self.generation or store is not self.store:
            store.drop(name)
            return
        old = store.view
        selected = self.viewport.selected()
        store.view = name
        store.view_count = count
        self.applied_filter = query
        store.drop(store.search)
        store.search = None
        self.matches = 0
        self.operation = ""
        self.viewport.tree_rows = None
        self.viewport.reset_size()
        position = store.position_of(selected) if selected else None
        self.viewport.choose(position if position is not None else 0)
        store.drop(old)
        self.status(
            f"Applied: {query or '(all records)'} · {count:,}/{store.count:,} records\n"
            "Search honors this filter. Tree preview available with t."
        )
        self.update_view_heading()
        self.schedule_aggregate()
        if self.query_one("#search", Input).value:
            self.start_search()

    @on(Input.Submitted, "#search")
    def submit_search(self):
        if self.ready():
            if self.search_timer:
                self.search_timer.stop()
            self.navigate_after_search = True
            self.start_search()
            self.viewport.focus()

    @on(Input.Changed, "#search")
    def search_changed(self):
        self.schedule_search()

    def schedule_search(self):
        self.viewport.refresh()
        self.query_one(JSONInspector).refresh()
        if self.search_timer:
            self.search_timer.stop()
        if self.operation == "search":
            self.cancel_event.set()
            self.generation += 1
            self.operation = ""
        if self.complete and self.operation != "capture":
            self.search_timer = self.set_timer(0.18, self.live_search)

    def live_search(self):
        if self.operation in ("", "search") and self.complete:
            self.start_search()

    def start_search(self):
        text = self.query_one("#search", Input).value
        if not text:
            self.store.drop(self.store.search)
            self.store.search = None
            self.matches = 0
            self.status("Search cleared")
            return
        generation, cancel = self.begin_operation("search")
        flags = tuple(
            self.query_one("#" + key, ToggleChip).value for key in ("full", "case", "word")
        )
        self.run_search(generation, cancel, self.store, self.store.view, text, flags)

    @work(thread=True, exit_on_error=False)
    def run_search(self, generation, cancel, store, view, text, flags):
        try:
            name, count = search_store(
                store,
                text,
                *flags,
                view,
                cancel,
                lambda *args: self.progress(*args, generation=generation),
                self.show_duration,
            )
            self.call_from_thread(self.search_finished, generation, store, name, count)
        except Exception as exc:
            self.call_from_thread(self.failed, generation, str(exc))

    def search_finished(self, generation, store, name, count):
        if generation != self.generation or store is not self.store:
            store.drop(name)
            return
        store.drop(store.search)
        store.search = name
        self.matches = count
        self.operation = ""
        self.status(
            f"{count:,} search matches · n / N navigate · filter: {self.applied_filter or '(all)'}"
        )
        self.viewport.refresh()
        self.query_one(JSONInspector).refresh()
        if self.navigate_after_search:
            self.navigate_after_search = False
            self.jump_match(1)

    def jump_match(self, direction):
        if not self.store or not self.store.search or not self.matches:
            self.notify("No matches for the current search")
            return
        selected = self.viewport.selected()
        position = self.store.position_of(selected) if selected else -1
        position = position if position is not None else -1
        operator, ordering = (">", "ASC") if direction > 0 else ("<", "DESC")
        row = self.store.db.execute(
            f'SELECT seq,rid FROM "{self.store.search}" WHERE seq {operator} ? '
            f"ORDER BY seq {ordering} LIMIT 1",
            (position + 1,),
        ).fetchone()
        if not row:
            row = self.store.db.execute(
                f'SELECT seq,rid FROM "{self.store.search}" ORDER BY seq {ordering} LIMIT 1'
            ).fetchone()
        if self.viewport.tree_rows is not None:
            tree_position = next(
                (
                    i
                    for i, item in enumerate(self.viewport.tree_rows)
                    if item["rid"] == row[1] and item["kind"] == "record"
                ),
                None,
            )
            if tree_position is not None:
                target = self.viewport.tree_rows[tree_position]
                self.viewport.folded.difference_update(target["ancestors"])
                self.viewport.reset_size()
                self.viewport.choose(self.viewport._shown_tree.index(target))
                return
            self.viewport.tree_rows = None
            self.viewport.reset_size()
            self.notify("Match outside the limited tree preview; returned to console")
        self.viewport.choose(row[0] - 1)

    def action_next_match(self):
        self.jump_match(1)

    def action_previous_match(self):
        self.jump_match(-1)

    def action_filter(self):
        self.query_one("#filter", Input).focus()

    def action_search(self):
        self.query_one("#search", Input).focus()

    def action_inspector(self):
        pane = self.query_one("#inspector")
        pane.display = not pane.display
        self.inspector_override = True
        self.query_one("#toggle-json", Button).set_class(pane.display, "enabled")

    def action_narrow(self):
        self.inspector_percent = max(20, self.inspector_percent - 5)
        self.query_one("#inspector").styles.width = f"{self.inspector_percent}%"

    def action_widen(self):
        self.inspector_percent = min(65, self.inspector_percent + 5)
        self.query_one("#inspector").styles.width = f"{self.inspector_percent}%"

    def on_resize(self, event):
        if self.is_mounted and not self.inspector_override:
            self.query_one("#inspector").display = event.size.width >= 100

    def action_wrap(self):
        self.viewport.wrap_rows = not self.viewport.wrap_rows
        self.viewport.reset_size()
        self.viewport.scroll_to(x=0, animate=False)
        self.viewport.choose(self.viewport.cursor)

    def action_pin(self):
        self.pinned = None if self.pinned else self.viewport.selected()
        self.show_selected()

    def action_copy(self):
        rid = self.pinned or self.viewport.selected()
        if rid:
            record = self.store.record(rid)[0]
            self.copy_to_clipboard(json.dumps(record, indent=2, ensure_ascii=False))
            self.notify("Full JSON sent to terminal clipboard (terminal support required)")

    def action_settings(self):
        self.push_screen(Preferences())

    def action_refresh_data(self):
        self.start_capture()

    def action_cancel(self):
        if isinstance(self.screen, Preferences):
            self.screen.dismiss()
            return
        self.cancel_event.set()
        # Capture must finish its cleanup before another capture can begin.
        if self.operation and self.operation != "capture":
            self.generation += 1
            self.operation = ""
            self.status("Operation cancelled; previous successful view retained")
        self.viewport.focus()

    @on(Button.Pressed)
    def button(self, event):
        event.stop()
        key = event.button.id
        if key in ("full", "case", "word"):
            event.button.flip()
            self.schedule_search()
            return
        if key == "aggregate-follow":
            event.button.flip()
            self.query_one(AggregatePane).follow = event.button.value
            scoped = self.query_one("#aggregate-filter", Input)
            scoped.disabled = event.button.value
            if not event.button.value:
                scoped.value = self.applied_filter
            self.schedule_aggregate()
            return
        if key in ("fold-all", "expand-all"):
            self.viewport.folded = (
                {row["key"] for row in (self.viewport.tree_rows or []) if row.get("key")}
                if key == "fold-all"
                else set()
            )
            self.viewport.reset_size()
            self.viewport.choose(0)
            return
        if key == "clear-filter":
            self.query_one("#filter", Input).value = ""
            if self.ready():
                self.start_filter("")
            return
        actions = {
            "toggle-json": self.action_inspector,
            "toggle-tree": self.action_tree,
            "toggle-aggregate": self.action_aggregate,
            "run-aggregate": self.schedule_aggregate,
            "close-aggregate": self.action_aggregate,
            "toggle-date": self.action_timestamp,
            "settings": self.action_settings,
        }
        if key in actions:
            actions[key]()
            self.viewport.focus()

    def action_tree(self):
        if not self.ready() or self.operation:
            return
        if self.viewport.tree_rows is not None:
            selected = self.viewport.selected()
            self.viewport.tree_rows = None
            self.viewport.reset_size()
            self.viewport.choose(self.store.position_of(selected) or 0)
            self.update_view_heading()
            return
        generation, cancel = self.begin_operation("tree")
        self.run_tree(generation, cancel, self.store, self.store.view)

    @work(thread=True, exit_on_error=False)
    def run_tree(self, generation, cancel, store, view):
        try:
            rows, limited = build_tree(store, view, cancel)
            self.call_from_thread(self.tree_finished, generation, rows, limited)
        except Exception as exc:
            self.call_from_thread(self.failed, generation, str(exc))

    def tree_finished(self, generation, rows, limited):
        if generation != self.generation:
            return
        self.operation = ""
        self.viewport.tree_rows = rows
        self.viewport.folded.clear()
        self.viewport.reset_size()
        self.viewport.choose(0)
        self.update_view_heading()
        self.status(
            "Tree preview · first appearance · space folds · shift+space folds all\n"
            + (
                "LIMITED to first 10,000 matching records."
                if limited
                else "Ancestor context retained; missing/conflicting spans are explicit."
            )
        )

    def save_settings(self):
        self.cache_root.mkdir(parents=True, exist_ok=True)
        data = {
            "wrap": self.viewport.wrap_rows,
            "inspector": self.query_one("#inspector").display,
            "version": 2,
            "width": self.inspector_percent,
            "theme": self.theme,
            "timestamp": self.timestamp_mode,
            "duration": self.show_duration,
            "line_numbers": self.query_one(JSONInspector).line_numbers,
            "ram_mib": self.ram_mib,
            "search": {
                key: self.query_one("#" + key, ToggleChip).value for key in ("full", "case", "word")
            },
        }
        (self.cache_root / "PROTOTYPE-settings.json").write_text(json.dumps(data))
        self.notify("Saved prototype presentation defaults")

    def load_settings(self):
        path = self.cache_root / "PROTOTYPE-settings.json"
        if path.exists():
            data = json.loads(path.read_text())
            self.viewport.wrap_rows = data.get("wrap", False)
            self.inspector_percent = data.get("width", 28) if data.get("version") == 2 else 28
            self.query_one("#inspector").styles.width = f"{self.inspector_percent}%"
            self.query_one("#inspector").display = data.get("inspector", self.size.width >= 100)
            self.inspector_override = True
            self.theme = (
                "ixr-light" if data.get("theme") in ("ixr-light", "textual-light") else "ixr-dark"
            )
            self.timestamp_mode = data.get("timestamp", "time")
            self.show_duration = data.get("duration", False)
            self.ram_mib = data.get("ram_mib", self.ram_mib)
            self.query_one(JSONInspector).line_numbers = data.get("line_numbers", True)
            for key, value in data.get("search", {}).items():
                if key in ("full", "case", "word"):
                    chip = self.query_one("#" + key, ToggleChip)
                    chip.value = value
                    chip.sync()

    def on_unmount(self):
        self.aggregate_cancel.set()
        self.cancel_event.set()
        if self.store:
            self.store.close()


def build_tree(store, view, cancel):
    """Bounded representative trace tree, not production reconstruction."""
    with connect(store.db_path) as db:
        db.set_progress_handler(lambda: int(cancel.is_set()), 10000)
        db.execute("CREATE INDEX IF NOT EXISTS trace_lookup ON records(trace)")
        store.check_budget()
        if view:
            sql = (
                f'SELECT r.id,r.trace,r.span,r.parent,r.name FROM "{view}" v '
                "JOIN records r ON r.id=v.rid ORDER BY v.seq LIMIT 10001"
            )
        else:
            sql = "SELECT id,trace,span,parent,name FROM records ORDER BY id LIMIT 10001"
        records = db.execute(sql).fetchall()
        limited = len(records) > 10000
        records = records[:10000]
        traces = {}
        loose = []
        for rid, trace, span, parent, name in records:
            if not trace or not span:
                loose.append(rid)
                continue
            groups = traces.setdefault(trace, {})
            item = groups.setdefault(span, {"ids": [], "parents": set(), "name": name or span})
            item["ids"].append(rid)
            item["parents"].add(parent)
        # Add span evidence from outside the filter to preserve ancestor context.
        # Bound this prototype enrichment, rather than retaining every source row.
        for trace, groups in traces.items():
            if cancel.is_set():
                raise InterruptedError("Cancelled")
            for rid, span, parent, name in db.execute(
                "SELECT id,span,parent,name FROM records WHERE trace=? ORDER BY id LIMIT 10000",
                (trace,),
            ):
                if span:
                    item = groups.setdefault(
                        span,
                        {
                            "ids": [],
                            "parents": set(),
                            "name": name or span,
                            "context": rid,
                        },
                    )
                    item["parents"].add(parent)
    rows = []

    def emit_span(trace, span, groups, depth, ancestors, active):
        item = groups[span]
        key = trace + "/" + span
        if key in active:
            return
        active = active | {key}
        conflicting = len(item["parents"]) > 1
        rid = item["ids"][0] if item["ids"] else item.get("context")
        suffix = " [conflicting parents]" if conflicting else ""
        suffix += " [context]" if not item["ids"] else ""
        rows.append(
            {
                "kind": "span",
                "rid": rid,
                "key": key,
                "depth": depth,
                "label": f"{item['name']} · {len(item['ids'])} records{suffix}",
                "ancestors": ancestors,
            }
        )
        for record_id in item["ids"]:
            rows.append(
                {
                    "kind": "record",
                    "rid": record_id,
                    "depth": depth + 1,
                    "ancestors": [*ancestors, key],
                }
            )
        for child, candidate in groups.items():
            if candidate["parents"] == {span} and trace + "/" + child not in active:
                emit_span(trace, child, groups, depth + 1, [*ancestors, key], active)

    for trace, groups in traces.items():
        # Insertion order comes from source record order, independent of timestamps.
        roots = []
        for span, item in list(groups.items()):
            if len(item["parents"]) > 1:
                roots.append(span)
                continue
            parent = next(iter(item["parents"]), "")
            if not parent:
                roots.append(span)
            elif parent not in groups:
                groups[parent] = {
                    "ids": [],
                    "parents": {""},
                    "name": parent + " [missing parent]",
                    "context": item["ids"][0] if item["ids"] else item.get("context"),
                }
                roots.append(parent)
        trace_key = "trace/" + trace
        first_id = next((item["ids"][0] for item in groups.values() if item["ids"]), None)
        rows.append(
            {
                "kind": "trace",
                "rid": first_id,
                "key": trace_key,
                "depth": 0,
                "label": trace,
                "ancestors": [],
            }
        )
        for root in dict.fromkeys(roots):
            emit_span(trace, root, groups, 1, [trace_key], set())
        emitted = {row.get("key") for row in rows}
        for span in groups:
            if trace + "/" + span not in emitted:
                groups[span]["name"] += " [unresolved/cyclic]"
                emit_span(trace, span, groups, 1, [trace_key], set())
    if loose:
        rows.append(
            {
                "kind": "span",
                "rid": loose[0],
                "key": "untraced",
                "depth": 0,
                "label": "Records without sufficient trace identity",
                "ancestors": [],
            }
        )
        rows.extend(
            {"kind": "record", "rid": rid, "depth": 1, "ancestors": ["untraced"]} for rid in loose
        )
    return rows, limited


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="JSONL files, in concatenation order")
    parser.add_argument("--cache-dir", default="/tmp/slogger-tui-PROTOTYPE-cache")
    parser.add_argument("--ram-mib", type=int, default=32)
    parser.add_argument("--disk-gb", type=float, default=10)
    parser.add_argument("--capture-benchmark", action="store_true")
    args = parser.parse_args()
    paths = args.files or demo_files(Path(args.cache_dir) / "demo")
    if args.capture_benchmark:
        import resource

        store, metrics = open_capture(
            paths,
            Path(args.cache_dir),
            threading.Event(),
            lambda *_: None,
            budget_gb=args.disk_gb,
            ram_mib=args.ram_mib,
        )
        # Exercise random record paging, including the tail, without retaining rows.
        start = time.monotonic()
        for i in range(300):
            if store.count:
                store.record(1 + (i * 7919) % store.count)
        metrics.update(
            records=store.count,
            source_bytes=store.manifest.get("bytes"),
            disk_bytes=size_of(Path(args.cache_dir)),
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            random_300_reads_seconds=time.monotonic() - start,
            cache_admission_bytes=store.cache_bytes,
            python=__import__("sys").version,
        )
        # macOS reports bytes, Linux KiB.
        if __import__("sys").platform != "darwin":
            metrics["peak_rss_bytes"] *= 1024
        store.close()
        print(json.dumps(metrics, indent=2))
    else:
        NativeTUI(paths, args.cache_dir, args.ram_mib, args.disk_gb).run()


if __name__ == "__main__":
    main()
