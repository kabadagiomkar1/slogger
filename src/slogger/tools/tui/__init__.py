"""Optional native launcher; importing this module does not import Textual."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from ..errors import ToolError
from ..investigation import Investigation, ResourceLimits

__all__ = ["launch", "main"]


def launch(
    paths: Sequence[str | os.PathLike[str]],
    *,
    storage_dir: str | os.PathLike[str] | None = None,
    limits: ResourceLimits | None = None,
) -> None:
    try:
        from .app import InvestigationApp
    except ImportError as error:
        raise ToolError(
            "dependency_missing",
            "Native TUI requires the tools-tui extra. "
            'From this repository install: pip install -e ".[tools-tui]"',
        ) from error
    with Investigation.open(paths, storage_dir=storage_dir, limits=limits) as session:
        if not session.status.complete:
            diagnostic = session.diagnostics[-1]
            raise ToolError(diagnostic.code, diagnostic.message)
        InvestigationApp(session).run()


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
    parser.add_argument("--disk-budget-mib", type=int, default=10 * 1024)
    parser.add_argument("--ram-cache-mib", type=int, default=256)
    parser.add_argument("--max-record-mib", type=int, default=8)
    options = parser.parse_args(argv)
    try:
        limits = ResourceLimits(
            disk_bytes=options.disk_budget_mib * 1024**2,
            ram_cache_bytes=options.ram_cache_mib * 1024**2,
            max_record_bytes=options.max_record_mib * 1024**2,
        )
        launch(options.files, storage_dir=options.storage_dir, limits=limits)
    except (ToolError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ToolError) else "launch_failed"
        print(f"slogger-tui: {code}: {error}", file=sys.stderr)
        return 2
    return 0
