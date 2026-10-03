"""Streaming reference record-plan adapter."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..._planning import ValidatedPlan
from ...core.rows import project_rows as _project
from ...core.runtime import ExecutionResult, RecordRow, RecordSource
from ...errors import ToolError
from ...plan import Aggregate, Filter, Limit, Project, Sort
from ...predicates import Matcher


class PythonAdapter:
    def prepare(self, plan: ValidatedPlan) -> PreparedPython:
        return PreparedPython(plan)


class PreparedPython:
    def __init__(self, plan: ValidatedPlan) -> None:
        self.plan = plan
        self.matchers = {
            index: node.predicate.compile()
            for index, node in enumerate(plan.operations)
            if isinstance(node, Filter)
        }

    def explain(self) -> dict[str, Any]:
        blocking = any(isinstance(node, (Aggregate, Sort)) for node in self.plan.operations)
        return {
            "backend": "python",
            "mode": "blocking" if blocking else "streaming",
            "working_memory": "input_proportional" if blocking else "streaming",
            "output": "materialized",
        }

    def run(self, source: RecordSource) -> ExecutionResult:
        rows: Iterable[RecordRow] = source
        for index, node in enumerate(self.plan.operations[1:], 1):
            if isinstance(node, Filter):
                rows = _filter(rows, self.matchers[index])
            elif isinstance(node, Project):
                rows = _project(rows, node.fields)
            elif isinstance(node, Aggregate):
                from .aggregation import aggregate_rows

                rows = aggregate_rows(rows, node)

            elif isinstance(node, Sort):
                from .sorting import sort_rows

                rows = sort_rows(rows, node, operation=self.plan.operation_index(index))
            elif isinstance(node, Limit):
                rows = _limit(rows, node.count)
            else:
                raise ToolError("plan_invalid", "Python cannot execute logical plan node")
        output = list(rows)
        schema = self.plan.properties.schema
        if schema is None:
            schema = tuple(
                dict.fromkeys(key for row in output for key in row.record if key != "_id")
            )
        return ExecutionResult(output, schema)


def _filter(rows: Iterable[RecordRow], matcher: Matcher) -> Iterator[RecordRow]:
    for row in rows:
        if matcher(row.record):
            yield row


def _limit(rows: Iterable[RecordRow], count: int) -> Iterator[RecordRow]:
    iterator = iter(rows)
    for _ in range(count):
        try:
            row = next(iterator)
        except StopIteration:
            return
        yield row
