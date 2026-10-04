"""Throwaway native presentation widgets: inspector, aggregates, preferences."""

from __future__ import annotations

import json
import re

from native_query import META_FIELDS, QUIET_FIELDS, Parser
from native_store import check_cancel, path_spelling
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Span, Text
from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Button, Input, Label, OptionList, Select, Static

from slogger.tools import count_rows, max_of, mean_of, min_of, scan, sum_of


def get_value(record, path):
    value = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


class QueryInput(Input):
    BINDINGS = [
        Binding("tab", "complete", show=False),
        Binding("down", "suggestion(1)", show=False),
        Binding("up", "suggestion(-1)", show=False),
    ]

    def action_complete(self):
        self.app.complete_query(self.id)

    def action_suggestion(self, direction):
        self.app.move_suggestion(direction, self.id)


class ToggleChip(Button):
    def __init__(self, label, *, value=False, id=None):
        self.caption = label
        self.value = value
        super().__init__(label, id=id, compact=True, flat=True)
        self.sync()

    def sync(self):
        self.label = ("✓ " if self.value else "○ ") + self.caption
        self.set_class(self.value, "enabled")

    def flip(self):
        self.value = not self.value
        self.sync()


class JSONInspector(ScrollView):
    can_focus = True
    BINDINGS = [Binding("enter", "aggregate", "Aggregate field", show=False)]

    def __init__(self):
        super().__init__(id="json")
        self.lines = []
        self.paths = {}
        self.selected_path = None
        self.line_numbers = True
        self.record = {}

    @property
    def text(self):
        return json.dumps(self.record, indent=2)

    def set_record(self, record, preserve_scroll=False):
        self.record = record
        code = json.dumps(record, indent=2, ensure_ascii=False)
        preview = code[:64_000]
        theme = "github-dark" if self.app.dark else "friendly"
        highlighted = Syntax(preview, "json", theme=theme, background_color="default").highlight(
            preview
        )

        # Keep token foregrounds while allowing the terminal pane's background through.
        def foreground(style):
            if isinstance(style, str):
                style = Style.parse(style)
            return Style(color=style.color, bold=style.bold, italic=style.italic)

        highlighted.style = foreground(highlighted.style)
        highlighted.spans = [
            Span(span.start, span.end, foreground(span.style)) for span in highlighted.spans
        ]
        self.lines = list(highlighted.split("\n", allow_blank=True))
        self.paths = {}
        stack = {}
        for line, text in enumerate(self.lines):
            match = re.match(r'^(\s*)"((?:\\.|[^"\\])*)"\s*:', text.plain)
            if match:
                depth = len(match[1]) // 2
                key = json.loads('"' + match[2] + '"')
                stack[depth] = key
                for stale in [d for d in stack if d > depth]:
                    del stack[stale]
                self.paths[line] = tuple(stack[d] for d in sorted(stack))
        if len(code) > 64_000:
            self.lines.append(Text("… preview truncated; c copies full JSON"))
        self.virtual_size = Size(
            max([self.size.width, *[line.cell_len + 5 for line in self.lines]]), len(self.lines)
        )
        if not preserve_scroll:
            self.scroll_to(x=0, y=0, animate=False)
        self.refresh()

    def render_line(self, y):
        line = y + self.scroll_offset.y
        if line >= len(self.lines):
            return Strip.blank(self.size.width, self.rich_style)
        text = Text()
        if self.line_numbers:
            text.append(f"{line + 1:>3} ", style=self.app.palette["muted"])
        text.append(self.lines[line])
        pattern = self.app.search_pattern()
        path = self.paths.get(line)
        eligible = (
            self.app.query_one("#full", ToggleChip).value
            or not path
            or (path[0] not in META_FIELDS | QUIET_FIELDS)
        )
        if pattern and eligible:
            text.highlight_regex(pattern, style=self.app.palette["match"])
        if path and path == self.selected_path:
            text.stylize("on " + self.app.palette["selected"])
        strip = Strip(text.render(self.app.console)).apply_style(self.rich_style)
        return strip.crop(
            self.scroll_offset.x, self.scroll_offset.x + self.size.width
        ).adjust_cell_length(self.size.width, self.rich_style)

    def on_click(self, event: events.Click):
        line = int(event.y) + self.scroll_offset.y
        path = self.paths.get(line)
        if path:
            self.selected_path = path
            self.refresh()
            self.app.open_aggregate(path)

    def action_aggregate(self):
        if self.selected_path:
            self.app.open_aggregate(self.selected_path)


class AggregatePane(Vertical):
    def __init__(self):
        super().__init__(id="aggregate")
        self.follow = True

    def compose(self):
        with Horizontal(classes="aggregate-heading"):
            yield Label("AGGREGATE", classes="section-label")
            yield Static("Click a console field or JSON key", id="aggregate-scope")
            yield Button("×", id="close-aggregate", compact=True, flat=True)
        with Horizontal(classes="aggregate-inputs"):
            yield Label("Field", classes="input-label")
            yield Input("level", id="aggregate-field", compact=True)
            yield Select(
                [("Value counts", "counts"), ("Numeric summary", "numeric")],
                value="counts",
                allow_blank=False,
                compact=True,
                id="aggregate-mode",
            )
            yield Label("Group", classes="input-label")
            yield Input(placeholder="logger, level", id="aggregate-group", compact=True)
        with Horizontal(classes="aggregate-inputs"):
            yield ToggleChip("Follow main", value=True, id="aggregate-follow")
            yield QueryInput(
                placeholder="Independent filter; Enter applies",
                compact=True,
                id="aggregate-filter",
                disabled=True,
            )
            yield Button("Run", id="run-aggregate", compact=True, flat=True)
        yield OptionList(id="aggregate-suggestions", compact=True, markup=False)
        with VerticalScroll(id="aggregate-scroll"):
            yield Static("Select a field to start", id="aggregate-results")
        yield Static(
            "Exact for small scopes · larger scopes use an explicit bounded preview",
            id="aggregate-note",
        )


def aggregate_preview(store, field_text, group_text, mode, follow, query, cancel):
    field = Parser(field_text).field()
    groups = [Parser(key.strip()).field() for key in group_text.split(",") if key.strip()]
    if mode == "counts" and not groups:
        groups = [field]
    expression = Parser(query).parse() if not follow and query.strip() else None
    records = []
    byte_count = 0
    limited = False
    view = store.view if follow else None
    for batch in store.batches(cancel, view):
        raw = [item[2] for item in batch]
        plan = scan(raw)
        if expression is not None:
            plan = plan.filter(expression)
        matched = plan.filter(field.exists()).execute().records
        for record in matched:
            size = len(json.dumps(record))
            if len(records) >= 10000 or byte_count + size > 4 * 1024 * 1024:
                limited = True
                break
            transformed = dict(record)
            for i, key in enumerate(groups):
                present, value = get_value(record, key.path)
                if present:
                    transformed[f"__prototype_group_{i}"] = value
            records.append(transformed)
            byte_count += size
        if limited:
            break
    check_cancel(cancel)
    plan = scan(records)
    if groups:
        plan = plan.group_by(*(f"__prototype_group_{i}" for i in range(len(groups))))
    metrics = {"count": count_rows()}
    if mode == "numeric":
        metrics.update(sum=sum_of(field), mean=mean_of(field), min=min_of(field), max=max_of(field))
    result = plan.aggregate(**metrics).execute().records
    labels = [path_spelling(group.path) for group in groups]
    table = Table(box=None, expand=True, padding=(0, 1), header_style="bold", show_edge=False)
    for column in [*labels, *metrics]:
        table.add_column(column, justify="left" if column in labels else "right")
    for row in result[:100]:
        values = [row.get(f"__prototype_group_{i}", "(missing)") for i in range(len(groups))]
        values += [row.get(key) for key in metrics]
        table.add_row(
            *(
                f"{value:,.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
                for value in values
            )
        )
    note = (
        f"{'PREVIEW · first' if limited else 'All'} {len(records):,} matching records"
        f" · exists({path_spelling(field.path)})"
    )
    if len(result) > 100:
        note += f" · showing 100/{len(result):,} groups"
    return table, note


class Preferences(ModalScreen):
    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    Preferences { align: center middle; background: $background 75%; }
    #preferences { width: 66; height: auto; max-height: 95%; background: $surface;
                   border: round $primary; padding: 1 2; }
    #preferences-title { height: 2; color: $primary; text-style: bold; }
    .preference-row { height: 2; }
    .preference-row Label { width: 25; padding-top: 0; }
    .preference-row Select { width: 1fr; height: 1; border: none; }
    .preference-row Button { width: 1fr; }
    #preference-cache { height: auto; color: $text-muted; margin-top: 1; margin-bottom: 1; }
    #preference-actions { height: 1; align-horizontal: right; }
    #preference-actions Button { margin-left: 1; }
    """

    def compose(self):
        with VerticalScroll(id="preferences"):
            yield Label("PREFERENCES", id="preferences-title")
            for label, key, choices, value in [
                ("Theme", "theme", [("Dark", "ixr-dark"), ("Light", "ixr-light")], self.app.theme),
                (
                    "Timestamp",
                    "timestamp",
                    [("Time", "time"), ("Date + time", "date"), ("Original timestamp", "raw")],
                    self.app.timestamp_mode,
                ),
                (
                    "Inspector width",
                    "width",
                    [
                        (f"{v}%", v)
                        for v in sorted({25, 28, 30, 35, 40, 45, self.app.inspector_percent})
                    ],
                    self.app.inspector_percent,
                ),
                (
                    "Browsing cache",
                    "ram",
                    [
                        (f"{v} MiB", v)
                        for v in sorted({16, 32, 64, 128, 256, 512, self.app.ram_mib})
                    ],
                    self.app.ram_mib,
                ),
            ]:
                with Horizontal(classes="preference-row"):
                    yield Label(label)
                    yield Select(
                        choices, value=value, allow_blank=False, compact=True, id="pref-" + key
                    )
            for label, key, value in [
                ("Wrap console rows", "wrap", self.app.viewport.wrap_rows),
                ("Show duration field", "duration", self.app.show_duration),
                ("JSON line numbers", "numbers", self.app.query_one(JSONInspector).line_numbers),
                ("Inspector visible", "inspector", self.app.query_one("#inspector").display),
            ]:
                with Horizontal(classes="preference-row"):
                    yield Label(label)
                    yield ToggleChip("On" if value else "Off", value=value, id="pref-" + key)
            yield Static(
                "Search defaults are saved from the Console / Full, Case, and Word controls.\n"
                "Cache: 10 GB default · 7-day expiry · active datasets protected",
                id="preference-cache",
            )
            with Horizontal(id="preference-actions"):
                yield Button("Clear unused", id="pref-clear", compact=True, flat=True)
                yield Button("Save defaults", id="pref-save", compact=True, flat=True)
                yield Button("Done", id="pref-close", compact=True, flat=True)

    @on(Select.Changed)
    def selected(self, event):
        if event.value is Select.NULL:
            return
        key = event.select.id
        if key == "pref-theme":
            self.app.set_theme(event.value)
        elif key == "pref-timestamp":
            self.app.timestamp_mode = event.value
        elif key == "pref-width":
            self.app.inspector_percent = event.value
            self.app.query_one("#inspector").styles.width = f"{event.value}%"
        elif key == "pref-ram":
            self.app.ram_mib = event.value
            if self.app.store:
                self.app.store.ram_limit = event.value * 1024 * 1024
                self.app.store.cache.clear()
                self.app.store.cache_bytes = 0
        self.app.viewport.refresh()

    @on(Button.Pressed)
    def button(self, event):
        event.stop()
        key = event.button.id
        if key == "pref-save":
            self.app.save_settings()
        elif key == "pref-clear":
            self.app.clear_unused_cache()
        elif key == "pref-close":
            self.dismiss()
        elif isinstance(event.button, ToggleChip):
            event.button.flip()
            event.button.caption = "On" if event.button.value else "Off"
            event.button.sync()
            if key == "pref-wrap":
                self.app.viewport.wrap_rows = event.button.value
                self.app.viewport.reset_size()
            elif key == "pref-duration":
                self.app.show_duration = event.button.value
                self.app.schedule_search()
            elif key == "pref-numbers":
                self.app.query_one(JSONInspector).line_numbers = event.button.value
                self.app.query_one(JSONInspector).refresh()
            elif key == "pref-inspector":
                self.app.query_one("#inspector").display = event.button.value
                self.app.inspector_override = True
            self.app.viewport.refresh()

    def action_close(self):
        self.dismiss()
