"""Optional native launcher; importing this module does not import Textual."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import replace

from ..errors import ToolError
from ..investigation import Investigation, ResourceLimits, default_cache_dir

__all__ = ["launch", "main"]


def launch(
    paths: Sequence[str | os.PathLike[str]],
    *,
    storage_dir: str | os.PathLike[str] | None = None,
    limits: ResourceLimits | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    cache_expiry_seconds: float | None = None,
    use_cache: bool = True,
    preferences_path: str | os.PathLike[str] | None = None,
) -> None:
    try:
        from .app import InvestigationApp
        from .preferences import PreferencesStore
    except ImportError as error:
        raise ToolError(
            "dependency_missing",
            "Native TUI requires the tools-tui extra. "
            'From this repository install: pip install -e ".[tools-tui]"',
        ) from error
    preferences = PreferencesStore(preferences_path).load()
    preferences = replace(
        preferences,
        limits=limits or preferences.limits,
        cache_expiry_seconds=preferences.cache_expiry_seconds
        if cache_expiry_seconds is None
        else cache_expiry_seconds,
    )
    with Investigation.open(
        paths,
        storage_dir=storage_dir,
        limits=preferences.limits,
        background=True,
        cache_dir=(cache_dir if cache_dir is not None else default_cache_dir())
        if use_cache
        else None,
        cache_expiry_seconds=preferences.cache_expiry_seconds,
    ) as session:
        InvestigationApp(session, preferences=preferences, preferences_path=preferences_path).run()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open finite JSONL files in a stable native investigation."
    )
    parser.add_argument(
        "files", nargs="+", help="regular files, in supplied order; repeats are retained"
    )
    parser.add_argument(
        "--storage-dir", help="parent directory for session-owned temporary storage"
    )
    parser.add_argument("--cache-dir", help="durable managed cache directory")
    parser.add_argument("--cache-expiry-days", type=float, help="override saved cache expiry")
    parser.add_argument("--preferences-file", help="explicit saved native defaults path")
    parser.add_argument("--no-cache", action="store_true", help="use temporary session storage")
    parser.add_argument("--disk-budget-mib", type=int)
    parser.add_argument("--ram-cache-mib", type=int)
    parser.add_argument("--max-record-mib", type=int)
    options = parser.parse_args(argv)
    try:
        limits = None
        overrides = {
            key: value * 1024**2
            for key, value in (
                ("disk_bytes", options.disk_budget_mib),
                ("ram_cache_bytes", options.ram_cache_mib),
                ("max_record_bytes", options.max_record_mib),
            )
            if value is not None
        }
        if overrides:
            try:
                from .preferences import PreferencesStore
            except ImportError as error:
                raise ToolError(
                    "dependency_missing", "Native TUI requires the tools-tui extra."
                ) from error
            limits = replace(PreferencesStore(options.preferences_file).load().limits, **overrides)
        launch(
            options.files,
            storage_dir=options.storage_dir,
            limits=limits,
            cache_dir=options.cache_dir,
            cache_expiry_seconds=options.cache_expiry_days * 86400
            if options.cache_expiry_days is not None
            else None,
            preferences_path=options.preferences_file,
            use_cache=not options.no_cache,
        )
    except (ToolError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ToolError) else "launch_failed"
        print(f"slogger-tui: {code}: {error}", file=sys.stderr)
        return 2
    return 0
