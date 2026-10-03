"""Immutable finite-source record query plans."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .predicates import Predicate
from .reader import Order, Source

__all__ = ["scan", "QueryPlan", "PlanResult"]


@dataclass(frozen=True, eq=False)
class Scan:
    sources: Source | Sequence[Source] = field(repr=False, compare=False)
    order: Order = "concat"


@dataclass(frozen=True)
class Filter:
    input: PlanNode
    predicate: Predicate


@dataclass(frozen=True)
class Project:
    input: PlanNode
    fields: tuple[str, ...]


@dataclass(frozen=True)
class Limit:
    input: PlanNode
    count: int


@dataclass(frozen=True)
class Sort:
    input: PlanNode
    field: str
    descending: bool = False
    missing: Literal["first", "last"] = "last"
    nulls: Literal["first", "last"] = "last"


PlanNode = Scan | Filter | Project | Limit | Sort


@dataclass
class PlanResult:
    """Materialized output, user-field schema and execution accounting.

    Schema lists possible output keys, excluding preserved hidden source identity.
    Missing projected fields remain absent in records. Metadata describes records
    yielded by Reader; skipped-line counts can include time-order read-ahead.
    No independent total-input count is performed.
    """

    records: list[dict[str, Any]]
    schema: tuple[str, ...]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryPlan:
    """A reusable immutable logical plan over a finite Reader source.

    Call order is semantic. Construction/explain do not read sources. execute
    materializes output; use limit to bound it. One-shot input iterators are consumed
    by execute and must be supplied again for a subsequent execution.
    """

    _node: PlanNode = field(repr=False)

    def filter(self, predicate: Predicate) -> QueryPlan:
        """Keep records matching a typed predicate."""
        if not isinstance(predicate, Predicate):
            raise TypeError("filter requires a Predicate")
        return QueryPlan(Filter(self._node, predicate))

    def select(self, *fields: str) -> QueryPlan:
        """Select literal top-level fields, preserving hidden source identity."""
        if not fields or any(not isinstance(name, str) or not name for name in fields):
            raise ValueError("select requires nonempty string field names")
        if len(set(fields)) != len(fields):
            raise ValueError("select field names must be unique")
        return QueryPlan(Project(self._node, fields))

    def limit(self, count: int) -> QueryPlan:
        """Keep at most count rows; zero returns no rows."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("limit requires a nonnegative integer")
        return QueryPlan(Limit(self._node, count))

    def sort_by(
        self,
        field: str,
        *,
        descending: bool = False,
        missing: Literal["first", "last"] = "last",
        nulls: Literal["first", "last"] = "last",
    ) -> QueryPlan:
        """Globally sort one literal field; ties retain original source order.

        Present values must be compatible finite numbers or strings. Null/missing
        placement is independent of direction. Sorting materializes its input.
        """
        if not isinstance(field, str) or not field:
            raise ValueError("sort_by requires a nonempty literal field name")
        if not isinstance(descending, bool):
            raise TypeError("descending must be boolean")
        if missing not in ("first", "last") or nulls not in ("first", "last"):
            raise ValueError("missing and nulls must be 'first' or 'last'")
        return QueryPlan(Sort(self._node, field, descending, missing, nulls))

    def execute(self, *, backend: str = "python") -> PlanResult:
        """Execute with the selected adapter, returning materialized output."""
        from ._execution import execute

        return execute(self, backend=backend)

    def explain(self, *, backend: str = "python") -> dict[str, Any]:
        """Explain capabilities/properties without opening or consuming sources."""
        from ._execution import explain

        return explain(self, backend=backend)


def scan(sources: Source | Sequence[Source], *, order: Order = "concat") -> QueryPlan:
    """Create a plan using existing Reader paths, globs, stdin and finite iterables."""
    if isinstance(sources, (Mapping, bytes, bytearray)) or not isinstance(
        sources, (str, os.PathLike, Iterable)
    ):
        raise TypeError("scan requires a Reader source or sequence of sources")
    if order not in ("concat", "time"):
        raise ValueError("scan order must be 'concat' or 'time'")
    return QueryPlan(Scan(sources, order))
