"""Out-of-band exact field binding for captured reductions; no record injection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .builders import Field
from .fields import resolve_field
from .filter_language import format_field_path


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


@dataclass(frozen=True)
class GroupBinding(FieldBinding):
    """Bind an exact grouping path to a separate derived output name."""

    name: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.name is None:
            object.__setattr__(self, "name", format_field_path(self.path))
        elif not isinstance(self.name, str) or not self.name:
            raise ValueError("GroupBinding name must be a nonempty string")

    @property
    def label(self) -> str:
        assert self.name is not None
        return self.name
