"""One missing-value sentinel and mapping-only nested field resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MISSING = object()


def resolve_field(record: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for segment in path:
        if not isinstance(value, Mapping) or segment not in value:
            return _MISSING
        value = value[segment]
    return value
