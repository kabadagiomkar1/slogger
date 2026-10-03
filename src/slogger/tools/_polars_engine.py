"""Optional native scalar execution; logical nodes contain no Polars objects."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from typing import Any

from ._execution import ExecutionResult, RecordRow, RecordSource
from ._planning import ValidatedPlan
from .errors import ToolError
from .ixr import And, Compare, Exists, Expression, In, Not, Or
from .plan import Filter, Limit, Project

_BATCH_SIZE = 1024


class PolarsAdapter:
    def prepare(self, plan: ValidatedPlan) -> PreparedPolars:
        try:
            import polars
        except ImportError as exc:
            raise ToolError(
                "dependency_missing", "Polars execution requires the tools-polars extra"
            ) from exc
        for node in plan.operations[1:]:
            if isinstance(node, Filter):
                _check_expression(node.predicate.to_ixr())
            elif not isinstance(node, (Project, Limit)):
                raise ToolError("operation_unsupported", "Polars cannot execute this operation")
        return PreparedPolars(plan, polars)


class PreparedPolars:
    def __init__(self, plan: ValidatedPlan, polars: Any) -> None:
        self.plan = plan
        self.pl = polars

    def explain(self) -> dict[str, Any]:
        return {
            "backend": "polars",
            "mode": "native batches",
            "output": "materialized",
            "batch_size": _BATCH_SIZE,
            "pending_data_checks": ["homogeneous scalar fields", "exact numeric representation"],
        }

    def run(self, source: RecordSource) -> ExecutionResult:
        rows: Iterable[RecordRow] = source
        for node in self.plan.operations[1:]:
            if isinstance(node, Filter):
                rows = self._filter(rows, node.predicate.to_ixr())
            elif isinstance(node, Project):
                rows = _project(rows, node.fields)
            elif isinstance(node, Limit):
                rows = self._limit(rows, node.count)
        output = list(rows)
        schema = self.plan.properties.schema
        if schema is None:
            schema = tuple(dict.fromkeys(k for row in output for k in row.record if k != "_id"))
        return ExecutionResult(output, schema)

    def _filter(self, rows: Iterable[RecordRow], expression: Expression) -> Iterator[RecordRow]:
        for batch in _batches(rows):
            columns: dict[str, Any] = {"ordinal": self.pl.Series(range(len(batch)))}
            bindings: dict[tuple[str, ...], tuple[str, str]] = {}
            for index, path in enumerate(sorted(expression.required_fields())):
                name = f"field_{index}"
                values = []
                for row in batch:
                    if path[0] not in row.record:
                        raise ToolError(
                            "data_incompatible",
                            "sparse fields are not supported by this adapter",
                            field=list(path),
                        )
                    values.append(row.record[path[0]])
                kind, dtype = _profile(values, self.pl, path)
                columns[name] = self.pl.Series(name, values, dtype=dtype, strict=True)
                bindings[path] = (name, kind)
            frame = self.pl.DataFrame(columns)
            mask = _lower(expression, bindings, frame, self.pl)
            selected = frame.lazy().filter(mask).select("ordinal").collect()["ordinal"]
            for index in selected:
                yield batch[index]

    def _limit(self, rows: Iterable[RecordRow], count: int) -> Iterator[RecordRow]:
        if count == 0:
            return
        remaining = count
        iterator = iter(rows)
        while remaining:
            batch = []
            for _ in range(min(remaining, _BATCH_SIZE)):
                try:
                    batch.append(next(iterator))
                except StopIteration:
                    break
            if not batch:
                return
            # Bounded slices keep arbitrary Python counts out of backend index conversion.
            selected = self.pl.Series(range(len(batch))).slice(0, min(remaining, len(batch)))
            for index in selected:
                yield batch[index]
            remaining -= len(batch)


def _batches(rows: Iterable[RecordRow]) -> Iterator[list[RecordRow]]:
    iterator = iter(rows)
    while True:
        batch = []
        for _ in range(_BATCH_SIZE):
            try:
                batch.append(next(iterator))
            except StopIteration:
                break
        if not batch:
            return
        yield batch


def _project(rows: Iterable[RecordRow], fields: tuple[str, ...]) -> Iterator[RecordRow]:
    for row in rows:
        record = {name: row.record[name] for name in fields if name in row.record}
        if row.record_id is not None:
            record["_id"] = row.record_id
        yield RecordRow(record, row.ordinal, row.record_id)


def _check_expression(node: Expression) -> None:
    if isinstance(node, (And, Or)):
        for child in node.children:
            _check_expression(child)
        return
    if isinstance(node, Not):
        _check_expression(node.child)
        return
    if not isinstance(node, (Compare, In, Exists)):
        raise ToolError("expression_unsupported", "Polars supports scalar expressions only")
    path = node.left.path if isinstance(node, Compare) else node.field.path
    if len(path) != 1:
        raise ToolError(
            "expression_unsupported", "nested fields are not supported", field=list(path)
        )
    values = (
        [node.right.value]
        if isinstance(node, Compare)
        else [literal.value for literal in node.candidates]
        if isinstance(node, In)
        else []
    )
    for value in values:
        if value is not None and type(value) not in (bool, int, float, str):
            raise ToolError("expression_unsupported", "structural comparison is not supported")
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ToolError("expression_unsupported", "integer operand is outside Int64 range")


def _profile(values: list[Any], pl: Any, path: tuple[str, ...]) -> tuple[str, Any]:
    kinds = {type(value) for value in values if value is not None}
    if len(kinds) > 1 or not kinds.issubset({bool, int, float, str}):
        raise ToolError(
            "data_incompatible", "field must contain homogeneous scalars", field=list(path)
        )
    kind = next(iter(kinds), type(None))
    for value in values:
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ToolError(
                "data_incompatible", "integer field is outside Int64 range", field=list(path)
            )
        if type(value) is float and not math.isfinite(value):
            raise ToolError("data_incompatible", "nonfinite numeric field", field=list(path))
    return {
        bool: ("bool", pl.Boolean),
        int: ("int", pl.Int64),
        float: ("float", pl.Float64),
        str: ("str", pl.String),
        type(None): ("null", pl.Null),
    }[kind]


def _compatible(kind: str, value: Any) -> bool:
    if kind in ("int", "float"):
        return type(value) in (int, float)
    return {"bool": bool, "str": str, "null": type(None)}[kind] is type(value)


def _comparison(
    name: str,
    kind: str,
    value: Any,
    op: str,
    frame: Any,
    pl: Any,
) -> Any:
    column = pl.col(name)
    if value is None:
        return column.is_null() if op == "eq" else pl.lit(False)
    if not _compatible(kind, value):
        return pl.lit(False)
    if (kind == "int" and type(value) is float) or (kind == "float" and type(value) is int):
        if abs(value) >= 2**53 or any(
            item is not None and abs(item) >= 2**53 for item in frame[name]
        ):
            raise ToolError(
                "data_incompatible", "mixed numeric comparison may lose integer precision"
            )
    if op == "eq":
        result = column == value
    elif op == "ne":
        result = column != value
    elif op == "gt":
        result = column > value
    elif op == "ge":
        result = column >= value
    elif op == "lt":
        result = column < value
    else:
        result = column <= value
    return result.fill_null(False)


def _lower(node: Expression, bindings: dict[Any, Any], frame: Any, pl: Any) -> Any:
    if isinstance(node, (And, Or)):
        result = pl.lit(isinstance(node, And))
        for child in node.children:
            lowered = _lower(child, bindings, frame, pl)
            result = result & lowered if isinstance(node, And) else result | lowered
        return result
    if isinstance(node, Not):
        return ~_lower(node.child, bindings, frame, pl)
    if isinstance(node, Compare):
        name, kind = bindings[node.left.path]
        return _comparison(name, kind, node.right.value, node.op, frame, pl)
    if isinstance(node, Exists):
        return pl.lit(True)
    assert isinstance(node, In)
    name, kind = bindings[node.field.path]
    found = pl.lit(False)
    compatible = pl.lit(not node.candidates)
    for literal in node.candidates:
        found = found | _comparison(name, kind, literal.value, "eq", frame, pl)
        compatibility = (
            pl.col(name).is_null()
            if literal.value is None
            else pl.col(name).is_not_null()
            if _compatible(kind, literal.value)
            else pl.lit(False)
        )
        compatible = compatible | compatibility
    return compatible & ~found if node.negated else found
