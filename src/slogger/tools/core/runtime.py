"""Shared execution contracts independent of dispatch and source implementation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .._planning import ValidatedPlan


@dataclass(frozen=True)
class SourceOrigin:
    """Concrete input location; file/stdin lines are one-based, iterable positions zero-based."""

    source: str
    position: int
    kind: str


@dataclass(frozen=True)
class RecordRow:
    record: dict[str, Any]
    ordinal: int
    origin: SourceOrigin | None


class RecordSource(Protocol):
    """Rows supplied by a finite source; adapters need no Reader implementation."""

    def __iter__(self) -> Iterator[RecordRow]: ...


@dataclass
class ExecutionResult:
    rows: list[RecordRow]
    schema: tuple[str, ...]


class PreparedExecution(Protocol):
    def run(self, source: RecordSource) -> ExecutionResult: ...
    def explain(self) -> dict[str, Any]: ...


class ExecutionAdapter(Protocol):
    def prepare(self, plan: ValidatedPlan) -> PreparedExecution: ...
