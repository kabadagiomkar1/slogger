"""``python -m slogger`` entry point."""

from __future__ import annotations

import sys

from slogger.cli import main

if __name__ == "__main__":
    sys.exit(main())
