"""Optional native scalar execution; logical nodes contain no Polars objects."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ._columnar import FieldBinding, bind_batch
from ._execution import ExecutionResult, RecordRow, RecordSource
from ._planning import ValidatedPlan
from .errors import ToolError
from .ixr import And, Compare, Exists, Expression, In, Not, Or, StringMatch
from .plan import Filter, Limit, Project, Sort

_BATCH_SIZE = 1024
_REGEX_SYNTAX = frozenset(r".^$*+?{}[]\|()")


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
            elif not isinstance(node, (Project, Limit, Sort)):
                raise ToolError("operation_unsupported", "Polars cannot execute this operation")
        return PreparedPolars(plan, polars)


class PreparedPolars:
    def __init__(self, plan: ValidatedPlan, polars: Any) -> None:
        self.plan = plan
        self.pl = polars

    def explain(self) -> dict[str, Any]:
        return {
            "backend": "polars",
            "mode": "native global"
            if any(isinstance(n, Sort) for n in self.plan.operations)
            else "native batches",
            "working_memory": "input_proportional"
            if any(isinstance(n, Sort) for n in self.plan.operations)
            else "batch_and_output",
            "output": "materialized",
            "batch_size": _BATCH_SIZE,
            "pending_data_checks": [
                "supported referenced value types",
                "exact numeric representation",
            ],
        }

    def run(self, source: RecordSource) -> ExecutionResult:
        rows: Iterable[RecordRow] = source
        for index, node in enumerate(self.plan.operations[1:], 1):
            if isinstance(node, Filter):
                rows = self._filter(rows, node.predicate.to_ixr())
            elif isinstance(node, Project):
                rows = _project(rows, node.fields)
            elif isinstance(node, Limit):
                rows = self._limit(rows, node.count)
            elif isinstance(node, Sort):
                from ._polars_sorting import sort_rows

                rows = sort_rows(rows, node, operation=self.plan.operation_index(index), pl=self.pl)
        output = list(rows)
        schema = self.plan.properties.schema
        if schema is None:
            schema = tuple(dict.fromkeys(k for row in output for k in row.record if k != "_id"))
        return ExecutionResult(output, schema)

    def _filter(self, rows: Iterable[RecordRow], expression: Expression) -> Iterator[RecordRow]:
        for batch in _batches(rows):
            frame, bindings = bind_batch(batch, expression.required_fields(), self.pl)
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
    if isinstance(node, StringMatch):
        if node.op == "regex" and any(char in _REGEX_SYNTAX for char in node.pattern):
            raise ToolError(
                "expression_unsupported",
                "Polars regex supports plain literal patterns only",
                pattern=node.pattern,
                field=list(node.field.path),
            )
        return
    if not isinstance(node, (Compare, In, Exists)):
        raise ToolError("expression_unsupported", "Polars supports scalar expressions only")
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


def _comparison(
    name: str,
    kind: str,
    value: Any,
    op: str,
    frame: Any,
    pl: Any,
) -> Any:
    column = pl.col(name)
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


def _comparison_mask(binding: FieldBinding, value: Any, op: str, frame: Any, pl: Any) -> Any:
    if value is None:
        return pl.col(binding.nulls) if op == "eq" else pl.lit(False)
    kinds = (
        ("int", "float")
        if type(value) in (int, float)
        else ("bool" if type(value) is bool else "str",)
    )
    result = pl.lit(False)
    for kind in kinds:
        name = binding.lanes.get(kind)
        if name is not None:
            result = result | _comparison(name, kind, value, op, frame, pl)
    return result


def _lower(
    node: Expression,
    bindings: dict[tuple[str, ...], FieldBinding],
    frame: Any,
    pl: Any,
) -> Any:
    if isinstance(node, (And, Or)):
        result = pl.lit(isinstance(node, And))
        for child in node.children:
            lowered = _lower(child, bindings, frame, pl)
            result = result & lowered if isinstance(node, And) else result | lowered
        return result
    if isinstance(node, Not):
        return ~_lower(node.child, bindings, frame, pl)
    if isinstance(node, Compare):
        return _comparison_mask(bindings[node.left.path], node.right.value, node.op, frame, pl)
    if isinstance(node, Exists):
        return pl.col(bindings[node.field.path].presence)
    if isinstance(node, StringMatch):
        name = bindings[node.field.path].lanes.get("str")
        if name is None:
            return pl.lit(False)
        column = pl.col(name).str
        result = (
            column.starts_with(node.pattern)
            if node.op == "starts_with"
            else column.contains(node.pattern, literal=True)
        )
        return result.fill_null(False)
    assert isinstance(node, In)
    binding = bindings[node.field.path]
    found = pl.lit(False)
    compatible = pl.col(binding.presence) if not node.candidates else pl.lit(False)
    for literal in node.candidates:
        value = literal.value
        found = found | _comparison_mask(binding, value, "eq", frame, pl)
        if value is None:
            compatible = compatible | pl.col(binding.nulls)
        else:
            kinds = (
                ("int", "float")
                if type(value) in (int, float)
                else ("bool" if type(value) is bool else "str",)
            )
            for kind in kinds:
                name = binding.lanes.get(kind)
                if name is not None:
                    compatible = compatible | pl.col(name).is_not_null()
    return compatible & ~found if node.negated else found
