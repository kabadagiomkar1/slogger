"""Compact keyboard-accessible presentation and resource settings."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static, Switch

from ..errors import ToolError
from ..investigation import ResourceLimits
from .preferences import NativePreferences
from .presentation import ConsoleOptions

if TYPE_CHECKING:
    from .app import InvestigationApp

_MIB = 1024**2


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("ctrl+enter", "apply", "Apply session", priority=True),
        Binding("ctrl+s", "save", "Save defaults", priority=True),
    ]
    DEFAULT_CSS = """
    SettingsScreen { align: center middle; background: $background 75%; }
    #settings-dialog { width: 76; max-width: 95%; height: 90%; max-height: 42;
        padding: 1; border: round $primary; background: $surface; }
    #settings-title { height: 1; text-style: bold; color: $text; }
    #settings-help { height: auto; max-height: 4; color: $text-muted; }
    #settings-fields { height: 1fr; }
    .settings-row { height: auto; min-height: 1; margin-bottom: 0; }
    .settings-label { width: 25; height: 1; color: $text-muted; }
    .settings-row Switch { height: 1; width: 1fr; border: none; padding: 0; }
    .settings-row Select { height: 3; width: 1fr; }
    .settings-row Input { height: 1; width: 1fr; border: none; padding: 0 1; }
    .settings-row Input:focus { background: $primary-muted; }
    #settings-usage { height: auto; color: $text-muted; margin-top: 1; }
    #settings-status { height: auto; min-height: 1; max-height: 4; color: $text; }
    #settings-status.error { color: $error; }
    .settings-actions { height: 1; margin-top: 1; }
    .settings-actions Button { height: 1; min-width: 1; width: auto; border: none;
        padding: 0 1; margin-right: 1; background: $panel; color: $text; }
    .settings-actions Button:focus { background: $primary; color: $text; text-style: bold; }
    """

    def __init__(self, owner: InvestigationApp) -> None:
        super().__init__(id="settings")
        self.owner = owner

    def compose(self) -> ComposeResult:
        options = self.owner.preferences
        with Vertical(id="settings-dialog"):
            yield Static("Settings", id="settings-title")
            yield Static(
                "Ctrl+Enter applies this session · Ctrl+S saves current defaults\n"
                "Esc returns · Tab moves through options",
                id="settings-help",
            )
            with VerticalScroll(id="settings-fields"):
                with Horizontal(classes="settings-row"):
                    yield Static("Theme", classes="settings-label")
                    yield Select(
                        [("Dark", "dark"), ("Light", "light")],
                        value=options.theme,
                        allow_blank=False,
                        id="preference-theme",
                    )
                for label, key, value in (
                    ("Wrap console", "wrap", options.console.wrap),
                    ("Show duration", "duration", options.console.show_duration),
                    ("JSON line numbers", "json-lines", options.json_line_numbers),
                    ("Show JSON pane", "json-visible", options.inspector_visible),
                    ("Show aggregate pane", "aggregates", options.aggregate_visible),
                ):
                    with Horizontal(classes="settings-row"):
                        yield Static(label, classes="settings-label")
                        yield Switch(value, id=f"preference-{key}")
                with Horizontal(classes="settings-row"):
                    yield Static("Timestamp", classes="settings-label")
                    yield Select(
                        [("Time", "time"), ("Date and time", "datetime"), ("Original", "original")],
                        value=options.console.timestamp_mode,
                        allow_blank=False,
                        id="preference-timestamp",
                    )
                for label, key, value in (
                    ("JSON width (%)", "width", options.inspector_percent),
                    ("Disk budget (MiB)", "disk_bytes", options.limits.disk_bytes / _MIB),
                    (
                        "Browsing RAM (MiB)",
                        "ram_cache_bytes",
                        options.limits.ram_cache_bytes / _MIB,
                    ),
                    (
                        "Max record (MiB)",
                        "max_record_bytes",
                        options.limits.max_record_bytes / _MIB,
                    ),
                    (
                        "Working memory (MiB)",
                        "working_memory_bytes",
                        options.limits.working_memory_bytes / _MIB,
                    ),
                    (
                        "Page memory (MiB)",
                        "page_memory_bytes",
                        options.limits.page_memory_bytes / _MIB,
                    ),
                    ("Records per page", "max_page_records", options.limits.max_page_records),
                    ("Cache expiry (days)", "expiry", options.cache_expiry_seconds / 86400),
                ):
                    with Horizontal(classes="settings-row"):
                        yield Static(label, classes="settings-label")
                        yield Input(f"{value:g}", type="number", id=f"preference-{key}")
                yield Static(self.usage_text(), id="settings-usage", markup=False)
                with Horizontal(classes="settings-actions"):
                    yield Button("Clear expired", id="clear-expired", compact=True)
                    yield Button("Clear unused", id="clear-unused", compact=True)
                yield Static(
                    "Active datasets and results are protected. Browsing RAM is not process RSS.",
                    markup=False,
                )
            yield Static(
                "Session changes are temporary until Save defaults.",
                id="settings-status",
                markup=False,
            )
            with Horizontal(classes="settings-actions"):
                yield Button("Apply session", id="settings-apply", compact=True)
                yield Button("Save defaults", id="settings-save", compact=True)
                yield Button("Close", id="settings-close", compact=True)

    def usage_text(self) -> str:
        usage = self.owner.session.resources
        return (
            f"Managed disk {usage.managed_disk_bytes / _MIB:,.2f} MiB / "
            f"{self.owner.session.limits.disk_bytes / _MIB:,.2f} MiB\n"
            f"Allocated {usage.disk_bytes / _MIB:,.2f} · "
            f"reserved {usage.reserved_disk_bytes / _MIB:,.2f} "
            f"· catalog reserve {usage.catalog_reserve_bytes / _MIB:,.2f} MiB\n"
            f"Encoded browsing cache {usage.ram_cache_bytes / _MIB:,.2f} MiB / "
            f"{self.owner.session.limits.ram_cache_bytes / _MIB:,.2f} MiB"
        )

    def on_mount(self) -> None:
        self.query_one("#preference-theme", Select).focus()
        self.set_interval(0.5, self.refresh_usage)

    def refresh_usage(self) -> None:
        if self.is_mounted and self.owner.is_running:
            self.query_one("#settings-usage", Static).update(self.usage_text())

    def status(self, message: str, *, error: bool = False) -> None:
        label = self.query_one("#settings-status", Static)
        label.set_class(error, "error")
        label.update(message)

    def read_options(self) -> NativePreferences:
        def toggle(key: str) -> bool:
            return self.query_one(f"#preference-{key}", Switch).value

        def number(key: str) -> float:
            return float(self.query_one(f"#preference-{key}", Input).value)

        limits = ResourceLimits(
            **{
                key: int(number(key) * (1 if key == "max_page_records" else _MIB))
                for key in self.owner.session.limits.__dict__
            }
        )
        theme = str(self.query_one("#preference-theme", Select).value)
        timestamp = str(self.query_one("#preference-timestamp", Select).value)
        if theme not in ("dark", "light") or timestamp not in ("time", "datetime", "original"):
            raise ValueError("choose a theme and timestamp mode")
        return replace(
            self.owner.preferences,
            theme=theme,
            console=ConsoleOptions(toggle("wrap"), timestamp, toggle("duration")),
            json_line_numbers=toggle("json-lines"),
            inspector_visible=toggle("json-visible"),
            aggregate_visible=toggle("aggregates"),
            inspector_percent=int(number("width")),
            limits=limits,
            cache_expiry_seconds=number("expiry") * 86400,
        )

    def action_apply(self) -> None:
        try:
            self.owner.apply_preferences(self.read_options())
        except (ToolError, OSError, ValueError, OverflowError) as error:
            self.status(f"Settings unchanged: {error}", error=True)
        else:
            self.status("Applied to this session. Saved defaults unchanged.")
            self.refresh_usage()

    def action_save(self) -> None:
        try:
            self.owner.preferences_store.save(self.owner.preferences)
        except (ToolError, OSError, ValueError) as error:
            self.status(str(error), error=True)
        else:
            self.status(f"Current session defaults saved to {self.owner.preferences_store.path}.")

    def on_button_pressed(self, message: Button.Pressed) -> None:
        message.stop()
        if message.button.id == "settings-apply":
            self.action_apply()
        elif message.button.id == "settings-save":
            self.action_save()
        elif message.button.id == "settings-close":
            self.dismiss()
        else:
            cache = self.owner.session.cache_store
            if cache is None:
                self.status("Temporary storage has no reusable cache to clear.")
                return
            try:
                result = cache.clear(expired_only=message.button.id == "clear-expired")
            except (ToolError, OSError) as error:
                self.status(str(error), error=True)
            else:
                self.status(
                    f"Cleared {result.removed_entries} entries; "
                    f"{result.protected_entries} active entries protected. "
                    f"Reclaimed {result.reclaimed_bytes / _MIB:,.2f} MiB."
                )
                self.refresh_usage()
