"""Out-of-band exact field binding for captured reductions; no record injection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .builders import Field
from .fields import resolve_field


@dataclass(frozen=True)
class FieldBinding:
    """Bind one literal key or explicit mapping path independently of output names."""

    path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.path, tuple):
            raise TypeError("FieldBinding requires an explicit tuple of path components")
        object.__setattr__(self, "path", Field(*self.path).path)

    def resolve(self, record: Mapping[str, Any]) -> Any:
        return resolve_field(record, self.path)
