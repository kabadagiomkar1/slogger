"""Immutable finite-source record query plans."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ..sources import Order, Source
from .builders import Field
from .ixr import Expression, _boolean
from .runtime import SourceOrigin

__all__ = [
    "scan",
    "QueryPlan",
    "PlanResult",
    "GroupedPlan",
    "AggregateSpec",
    "count_rows",
    "sum_of",
    "mean_of",
    "min_of",
    "max_of",
]


@dataclass(frozen=True, eq=False)
class Scan:
    sources: Source | Sequence[Source] = field(repr=False, compare=False)
    order: Order = "concat"


@dataclass(frozen=True)
class Filter:
    input: PlanNode
    expression: Expression


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


@dataclass(frozen=True)
class AggregateSpec:
    """An immutable numeric reduction or row count."""

    op: str
    field: Field | None = None


@dataclass(frozen=True)
class Aggregate:
    input: PlanNode
    keys: tuple[str, ...]
    aggregates: tuple[tuple[str, AggregateSpec], ...]


PlanNode = Scan | Filter | Project | Limit | Aggregate | Sort


def count_rows() -> AggregateSpec:
    """Count input rows, including rows with missing or null fields."""
    return AggregateSpec("count")


def _numeric(op: str, field: Field) -> AggregateSpec:
    if not isinstance(field, Field):
        raise TypeError("numeric aggregate requires a Field")
    return AggregateSpec(op, field)


def sum_of(field: Field) -> AggregateSpec:
    return _numeric("sum", field)


def mean_of(field: Field) -> AggregateSpec:
    return _numeric("mean", field)


def min_of(field: Field) -> AggregateSpec:
    return _numeric("min", field)


def max_of(field: Field) -> AggregateSpec:
    return _numeric("max", field)


@dataclass(frozen=True)
class GroupedPlan:
    """Non-executable grouping builder; complete with aggregate()."""

    _input: QueryPlan
    _keys: tuple[str, ...]

    def aggregate(self, **named: AggregateSpec) -> QueryPlan:
        return _aggregate_plan(self._input, self._keys, named)


def _aggregate_plan(
    plan: QueryPlan, keys: tuple[str, ...], named: Mapping[str, AggregateSpec]
) -> QueryPlan:
    if not named:
        raise ValueError("aggregate requires at least one named aggregate")
    if any(not name or name in keys for name in named):
        raise ValueError("aggregate aliases must be nonempty and not collide with keys")
    for spec in named.values():
        if not isinstance(spec, AggregateSpec):
            raise TypeError("aggregate values must be aggregate specifications")
        if spec.op not in ("count", "sum", "mean", "min", "max"):
            raise ValueError("unknown aggregate operation")
        if (spec.op == "count" and spec.field is not None) or (
            spec.op != "count" and not isinstance(spec.field, Field)
        ):
            raise ValueError("invalid aggregate field")
    return QueryPlan(Aggregate(plan._node, keys, tuple(named.items())))


@dataclass
class PlanResult:
    """Materialized output, user-field schema and execution accounting.

    Schema lists possible application output keys. Origins are aligned with records,
    separately identifying file/stdin physical lines (one-based) or iterable
    positions (zero-based). Aggregate output has no single-record origin.
    Missing projected fields remain absent in records. Metadata describes records
    yielded by finite sources; skipped-line counts can include time-order read-ahead.
    No independent total-input count is performed.
    """

    records: list[dict[str, Any]]
    schema: tuple[str, ...]
    origins: list[SourceOrigin | None] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryPlan:
    """A reusable immutable logical plan over a finite record source.

    Call order is semantic. Construction/explain do not read sources. execute
    materializes output; use limit to bound it. One-shot input iterators are consumed
    by execute and must be supplied again for a subsequent execution.
    """

    _node: PlanNode = field(repr=False)

    def filter(self, expression: Expression) -> QueryPlan:
        """Keep records matching a boolean IXR expression."""
        if not _boolean(expression):
            raise TypeError("filter requires a boolean IXR expression")
        return QueryPlan(Filter(self._node, expression))

    def select(self, *fields: str) -> QueryPlan:
        """Select literal top-level fields, preserving origin alongside output."""
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

    def group_by(self, *keys: str) -> GroupedPlan:
        """Group by literal scalar field names, preserving first appearance."""
        if not keys or any(not isinstance(key, str) or not key for key in keys):
            raise ValueError("group_by requires nonempty user field names")
        if len(set(keys)) != len(keys):
            raise ValueError("group_by keys must be unique")
        return GroupedPlan(self, keys)

    def aggregate(self, **named: AggregateSpec) -> QueryPlan:
        """Reduce all input rows into one result, including empty input."""
        return _aggregate_plan(self, (), named)

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
        from .execution import execute

        return execute(self, backend=backend)

    def explain(self, *, backend: str = "python") -> dict[str, Any]:
        """Explain capabilities/properties without opening or consuming sources."""
        from .execution import explain

        return explain(self, backend=backend)


def scan(sources: Source | Sequence[Source], *, order: Order = "concat") -> QueryPlan:
    """Create a plan using file paths, globs, stdin and finite iterables."""
    if isinstance(sources, (Mapping, bytes, bytearray)) or not isinstance(
        sources, (str, os.PathLike, Iterable)
    ):
        raise TypeError("scan requires a record source or sequence of sources")
    if order not in ("concat", "time"):
        raise ValueError("scan order must be 'concat' or 'time'")
    return QueryPlan(Scan(sources, order))
