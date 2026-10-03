# /// script
# requires-python = ">=3.10"
# dependencies = ["textual==8.2.8"]
# ///
"""THROWAWAY native terminal prototype. Run with uv run --with-editable . <path>."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from native_query import CORE_FIELDS, completions, console_record, filter_store, search_store
from native_store import Store, connect, demo_files, open_capture, size_of
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Button, Checkbox, Footer, Input, Label, Static, TextArea


class QueryInput(Input):
    BINDINGS = [Binding("tab", "complete", show=False)]

    def action_complete(self):
        self.app.complete_query()


class Settings(ModalScreen):
    DEFAULT_CSS = """
    Settings { align: center middle; background: $background 70%; }
    #settings-box { width: 64; height: auto; border: round $accent; padding: 1 2; }
    #settings-box Label { height: auto; margin-bottom: 1; }
    #settings-box Button { width: 100%; }
    """

    def compose(self):
        with Vertical(id="settings-box"):
            yield Label("PROTOTYPE · settings / help")
            yield Label(
                "w  wrap (3-line preview)     i  JSON inspector\n"
                "[ / ]  inspector width       p  pin current record\n"
                "c  copy full JSON via terminal clipboard\n"
                "t  trace tree                space  fold/unfold span\n"
                "shift+space  fold/unfold all  Esc  cancel / leave input\n"
                "Ctrl+R  explicit refresh     n / N  next/previous search\n"
                "↑ ↓ PgUp PgDn Home End  navigate; ← → pan"
            )
            yield Label(
                "Cache: " + str(self.app.cache_root) + "\n"
                "10 GB disk default · 7-day expiry · "
                + str(self.app.ram_mib)
                + " MiB RAM admission budget\n"
                "Settings saved here are prototype preferences only."
            )
            yield Button("Change theme", id="theme")
            yield Button("Clear unused cached datasets", id="clear-cache")
            yield Button("Save current presentation defaults", id="save-settings")
            yield Button("Close", id="close-settings", variant="primary")

    @on(Button.Pressed)
    def press(self, event):
        if event.button.id == "theme":
            self.app.theme = (
                "textual-light" if self.app.theme != "textual-light" else "textual-dark"
            )
        elif event.button.id == "save-settings":
            self.app.save_settings()
        elif event.button.id == "clear-cache":
            from native_store import lock

            removed = 0
            for entry in self.app.cache_root.glob("dataset-*"):
                lease = lock(entry / "lease.lock")
                if lease:
                    import shutil

                    shutil.rmtree(entry)
                    lease.close()
                    removed += 1
            self.app.notify(f"Removed {removed} unused dataset(s); open data protected")
        else:
            self.dismiss()

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss()


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
        if event.chain == 2:
            self.action_fold()

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
                "  " * tree_row["depth"] + indicator + " " + tree_row["label"], style="bold #9cc9e8"
            )
        else:
            record, _, _ = self.app.store.record(rid)
            level = str(record.get("level", "?"))
            color = "#f27689" if level == "ERROR" else "#edc572" if level == "WARN" else "#80bfa4"
            text = Text("  " * (tree_row["depth"] if tree_row else 0))
            text.append("▸ " if position == self.cursor else "  ", style="#80cfff")
            source = self.app.store.record(rid)[1]
            ordinal = next(
                i + 1
                for i, file in enumerate(self.app.store.manifest["files"])
                if file["path"] == source
            )
            text.append(f"{ordinal:02} │ ", style="#637b91")
            text.append(str(record.get("timestamp", "—"))[-13:] + " ", style="#8998aa")
            text.append(level.ljust(5) + " ", style=color)
            text.append(str(record.get("logger", "—")) + "  ", style="#9cc9e8")
            text.append(str(record.get("message", "—")))
            custom = {k: v for k, v in console_record(record).items() if k not in CORE_FIELDS}
            if custom:
                text.append(
                    "  "
                    + " ".join(
                        f"{k}={json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                        for k, v in custom.items()
                    ),
                    style="#8998aa",
                )
            # Deliberately cap visual rendering, while search/copy use full data.
            if len(text) > 4000:
                text = text[:3990] + Text(" … JSON")
        if position == self.cursor:
            text.stylize("on #25394d")
        if self.wrap_rows:
            pieces = text.wrap(self.app.console, max(1, width), overflow="fold")
            text = pieces[wrapped_line] if wrapped_line < len(pieces) else Text("")
            if wrapped_line == 2 and len(pieces) > 3:
                text = text[: max(0, width - 8)] + Text(" … JSON", style="#edc572")
            strip = Strip(text.render(self.app.console))
        else:
            strip = Strip(text.render(self.app.console)).crop(
                self.scroll_offset.x, self.scroll_offset.x + width
            )
        return strip.apply_style(self.rich_style).adjust_cell_length(width, self.rich_style)


class NativeTUI(App):
    TITLE = "IXR · native prototype"
    CSS = """
    Screen { background: #101923; color: #d5dee8; }
    #title { height: 1; background: #1a2a3b; color: #9cc9e8; padding: 0 1; }
    #filter { height: 3; margin: 0 1; }
    #suggestions { height: 1; color: #80cfff; padding: 0 2; }
    #search-row { height: 3; margin: 0 1; }
    #search { width: 1fr; }
    #search-row Checkbox { width: auto; padding: 0 1; border: none; }
    #controls { height: 3; padding: 0 1; }
    #controls Button { min-width: 8; width: auto; margin-right: 1; }
    #body { height: 1fr; }
    #logs { width: 1fr; height: 1fr; scrollbar-size: 1 1; }
    #logs:focus { border: solid #31475d; }
    #inspector { width: 40%; min-width: 28; border-left: solid #31475d; }
    #inspector-title { height: 1; color: #9cc9e8; padding: 0 1; }
    #json { height: 1fr; border: none; background: #14202d; }
    #origin { height: 1; color: #80cfff; padding: 0 1; }
    #status { height: 2; color: #9cabbc; padding: 0 1; }
    Footer { background: #1a2a3b; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "filter", "Filter"),
        Binding("slash", "search", "Search"),
        Binding("n", "next_match", "Next"),
        Binding("N", "previous_match", "Previous", show=False),
        Binding("i", "inspector", "JSON"),
        Binding("t", "tree", "Tree"),
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
        self.inspector_percent = 40
        self.inspector_override = False
        self._progress_tick = 0
        self.last_metrics = None

    def compose(self) -> ComposeResult:
        yield Static(" IXR / NATIVE TERMINAL PROTOTYPE  ·  layout A  ·  finite files", id="title")
        yield QueryInput(
            placeholder='Filter · level = "ERROR" and duration_ms >= 300 · Enter applies',
            id="filter",
            select_on_focus=False,
        )
        yield Static("Tab completes syntax / sampled fields / values", id="suggestions")
        with Horizontal(id="search-row"):
            yield Input(
                placeholder="Search records · Enter finds next · n / N navigate", id="search"
            )
            yield Checkbox("Full", id="full")
            yield Checkbox("Case", id="case")
            yield Checkbox("Word", id="word")
        with Horizontal(id="controls"):
            yield Button("JSON [i]", id="toggle-json")
            yield Button("Tree [t]", id="toggle-tree")
            yield Button("Wrap [w]", id="toggle-wrap")
            yield Button("Refresh", id="refresh")
            yield Button("Settings", id="settings")
        with Horizontal(id="body"):
            yield LogViewport()
            with Vertical(id="inspector"):
                yield Static("JSON · current record", id="inspector-title")
                yield TextArea(
                    "",
                    language="json",
                    read_only=True,
                    show_line_numbers=True,
                    soft_wrap=False,
                    id="json",
                )
        yield Static("Waiting for capture", id="origin")
        yield Static(
            "Captured records appear progressively; full-dataset operations wait.", id="status"
        )
        yield Footer()

    def on_mount(self):
        self.theme = "textual-dark"
        self.load_settings()
        self.viewport.focus()
        self.start_capture()

    @property
    def viewport(self):
        return self.query_one(LogViewport)

    def status(self, text):
        self.query_one("#status", Static).update(Text(text))

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
        self.complete = True
        self.operation = ""
        self.last_metrics = metrics
        self.viewport.tree_rows = None
        self.viewport.reset_size()
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
            self.query_one("#json", TextArea).load_text("")
            return
        record, source, line = self.store.record(rid)
        text = json.dumps(record, indent=2, ensure_ascii=False)
        if len(text) > 64_000:
            text = text[:64_000] + "\n… PROTOTYPE INSPECTOR PREVIEW · c copies full JSON"
        self.query_one("#json", TextArea).load_text(text)
        self.query_one("#inspector-title", Static).update(
            "JSON · PINNED" if self.pinned else "JSON · current record"
        )
        self.query_one("#origin", Static).update(
            Text(
                f"{Path(source).name}:{line}  · record {rid:,} · "
                f"view {self.viewport.cursor + 1:,}/{self.viewport.count:,}"
                + (" · INCOMPLETE CAPTURE" if not self.complete else "")
            )
        )
        self.query_one("#origin", Static).tooltip = source

    @on(Input.Changed, "#filter")
    def query_changed(self):
        self.update_suggestions()

    def update_suggestions(self):
        samples = self.store.manifest.get("samples", {}) if self.store else {}
        value = self.query_one("#filter", Input).value
        _, choices = completions(value, samples)
        self.query_one("#suggestions", Static).update(
            Text(
                "Tab → " + "  ·  ".join(choices)
                if choices
                else "Enter applies · Esc returns to logs"
            )
        )

    def complete_query(self):
        widget = self.query_one("#filter", Input)
        samples = self.store.manifest.get("samples", {}) if self.store else {}
        prefix = widget.value[: widget.cursor_position]
        start, choices = completions(prefix, samples)
        if choices:
            completed = prefix[:start] + choices[0]
            widget.value = completed + widget.value[widget.cursor_position :]
            widget.cursor_position = len(completed)

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
        if self.query_one("#search", Input).value:
            self.start_search()

    @on(Input.Submitted, "#search")
    def submit_search(self):
        if self.ready():
            self.start_search()
            self.viewport.focus()

    @on(Checkbox.Changed)
    def search_options_changed(self):
        if self.complete and self.query_one("#search", Input).value and not self.operation:
            self.start_search()

    def start_search(self):
        text = self.query_one("#search", Input).value
        if not text:
            self.store.drop(self.store.search)
            self.store.search = None
            self.matches = 0
            return
        generation, cancel = self.begin_operation("search")
        flags = tuple(self.query_one("#" + key, Checkbox).value for key in ("full", "case", "word"))
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
        self.jump_match(1)

    def jump_match(self, direction):
        if not self.store or not self.store.search or not self.matches:
            self.notify("No search matches; Enter in search first")
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

    def action_narrow(self):
        self.inspector_percent = max(25, self.inspector_percent - 5)
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
        self.push_screen(Settings())

    def action_refresh_data(self):
        self.start_capture()

    def action_cancel(self):
        self.cancel_event.set()
        # Capture must finish its cleanup before another capture can begin.
        if self.operation and self.operation != "capture":
            self.generation += 1
            self.operation = ""
            self.status("Operation cancelled; previous successful view retained")
        self.viewport.focus()

    @on(Button.Pressed)
    def button(self, event):
        actions = {
            "toggle-json": self.action_inspector,
            "toggle-tree": self.action_tree,
            "toggle-wrap": self.action_wrap,
            "refresh": self.action_refresh_data,
            "settings": self.action_settings,
        }
        if event.button.id in actions:
            actions[event.button.id]()
            self.viewport.focus()

    def action_tree(self):
        if not self.ready() or self.operation:
            return
        if self.viewport.tree_rows is not None:
            selected = self.viewport.selected()
            self.viewport.tree_rows = None
            self.viewport.reset_size()
            self.viewport.choose(self.store.position_of(selected) or 0)
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
            "width": self.inspector_percent,
            "theme": self.theme,
        }
        (self.cache_root / "PROTOTYPE-settings.json").write_text(json.dumps(data))
        self.notify("Saved prototype presentation defaults")

    def load_settings(self):
        path = self.cache_root / "PROTOTYPE-settings.json"
        if path.exists():
            data = json.loads(path.read_text())
            self.viewport.wrap_rows = data.get("wrap", False)
            self.inspector_percent = data.get("width", 40)
            self.query_one("#inspector").styles.width = f"{self.inspector_percent}%"
            self.query_one("#inspector").display = data.get("inspector", self.size.width >= 100)
            self.inspector_override = True
            self.theme = data.get("theme", "textual-dark")

    def on_unmount(self):
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
