"""Explicit native defaults; importing/selecting paths never creates files."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..errors import ToolError
from ..investigation import ResourceLimits
from ..investigation.cache import DEFAULT_EXPIRY_SECONDS
from .presentation import ConsoleOptions


def default_preferences_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "slogger" / "tui-preferences.json"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "slogger"
        / "tui-preferences.json"
    )


@dataclass(frozen=True)
class NativePreferences:
    """Only defaults, never investigation queries/search/navigation history."""

    theme: Literal["dark", "light"] = "dark"
    console: ConsoleOptions = field(default_factory=ConsoleOptions)
    json_line_numbers: bool = False
    inspector_visible: bool = True
    inspector_percent: int = 33
    aggregate_visible: bool = False
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    cache_expiry_seconds: float = DEFAULT_EXPIRY_SECONDS

    def __post_init__(self) -> None:
        if self.theme not in ("dark", "light"):
            raise ValueError("theme must be dark or light")
        if type(self.inspector_percent) is not int or not 20 <= self.inspector_percent <= 60:
            raise ValueError("JSON width must be between 20 and 60 percent")
        if any(
            type(value) is not bool
            for value in (
                self.json_line_numbers,
                self.inspector_visible,
                self.aggregate_visible,
                self.console.wrap,
                self.console.show_duration,
            )
        ):
            raise ValueError("presentation toggles must be booleans")
        if not math.isfinite(self.cache_expiry_seconds) or self.cache_expiry_seconds < 0:
            raise ValueError("cache expiry must be finite and nonnegative")


class PreferencesStore:
    """No writes before explicit save; replacement is atomic on the local filesystem."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else default_preferences_path()

    def load(self) -> NativePreferences:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = handle.read(65537)
            if len(raw) > 65536:
                raise ValueError("preferences exceed 64 KiB")
            document = json.loads(raw)
            if document["version"] != 1 or set(document) != {"version", "preferences"}:
                raise ValueError("unsupported preferences format")
            values = document["preferences"]
            console = ConsoleOptions(**values.pop("console"))
            limits = ResourceLimits(**values.pop("limits"))
            return NativePreferences(console=console, limits=limits, **values)

        except FileNotFoundError:
            return NativePreferences()
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ToolError(
                "preferences_invalid", f"Cannot load defaults from {self.path}: {error}"
            ) from error

    def save(self, preferences: NativePreferences) -> None:
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".tui-preferences-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"version": 1, "preferences": asdict(preferences)}, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise ToolError(
                "preferences_failed", f"Cannot save defaults to {self.path}: {error}"
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
