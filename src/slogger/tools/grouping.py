"""Normalise record fields into group keys for ``--group-by``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def group_value(record: Mapping[str, Any], key: str) -> tuple[str, object] | None:
    """Return ``(type_name, normalised_value)`` or ``None`` when ``key`` is missing."""
    if key not in record:
        return None
    value = record[key]
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("number", float(value))
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, list):
        return (
            "array",
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str),
        )
    if isinstance(value, dict):
        return (
            "object",
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str),
        )
    return ("str", str(value))


def parse_group_selector(token: str) -> tuple[str, str]:
    """Parse ``KEY=VALUE`` for ``trace --group-by``. Raises :class:`ValueError`."""
    if "=" not in token:
        raise ValueError(f"invalid --group-by selector (expected KEY=VALUE): {token!r}")
    key, _, value = token.partition("=")
    if not key:
        raise ValueError(f"invalid --group-by selector: {token!r}")
    return key, value
