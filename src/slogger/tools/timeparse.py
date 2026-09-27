"""Parse durations and bucket sizes for the CLI and tools API."""

from __future__ import annotations

import re

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m|h|d)?$", re.IGNORECASE)
_BUCKET = re.compile(r"^(\d+)(s|m|h|d)$", re.IGNORECASE)

_DURATION_MS = {
    None: 1000.0,  # bare number = seconds
    "ms": 1.0,
    "s": 1000.0,
    "m": 60_000.0,
    "h": 3_600_000.0,
    "d": 86_400_000.0,
}

_BUCKET_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def parse_duration_ms(text: str) -> float:
    """Parse ``500ms``, ``1.5s``, ``2m``, ``1h``, ``1d``, or a bare number of seconds."""
    match = _DURATION.fullmatch(text.strip())
    if not match:
        raise ValueError(f"invalid duration: {text!r}")
    amount = float(match.group(1))
    unit = match.group(2).lower() if match.group(2) else None
    return amount * _DURATION_MS[unit]


def parse_bucket(text: str) -> int:
    """Parse a bucket size such as ``30s``, ``1m``, ``1h``, ``1d`` into seconds."""
    match = _BUCKET.fullmatch(text.strip())
    if not match:
        raise ValueError(f"invalid bucket size: {text!r}")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise ValueError(f"invalid bucket size: {text!r}")
    return amount * _BUCKET_SECONDS[unit]
