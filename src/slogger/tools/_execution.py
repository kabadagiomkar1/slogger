"""Execution seam, source lifecycle, adapter dispatch and output reconstruction."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from ._planning import ValidatedPlan, describe, validate
from .errors import ToolError
from .plan import PlanResult, QueryPlan
from .reader import Reader


@dataclass(frozen=True)
class RecordRow:
    record: dict[str, Any]
    ordinal: int
    record_id: str | None


class RecordSource:
    """Owned Reader iterator supplied to adapters with opaque record identity."""

    def __init__(self, reader: Reader) -> None:
        self.reader = reader
        self._iterator = iter(reader)
        self.consumed = 0

    def __iter__(self) -> Iterator[RecordRow]:
        for record in self._iterator:
            ordinal = self.consumed
            self.consumed += 1
            yield RecordRow(record, ordinal, record.get("_id"))

    def close(self) -> None:
        close = getattr(self._iterator, "close", None)
        if close is not None:
            close()


@dataclass
class ExecutionResult:
    rows: list[RecordRow]
    schema: tuple[str, ...]


class PreparedExecution(Protocol):
    def run(self, source: RecordSource) -> ExecutionResult: ...
    def explain(self) -> dict[str, Any]: ...


class ExecutionAdapter(Protocol):
    def prepare(self, plan: ValidatedPlan) -> PreparedExecution: ...


def _adapter(backend: str) -> ExecutionAdapter:
    if backend == "python":
        from ._python_plan import PythonAdapter

        return PythonAdapter()
    raise ToolError("backend_unsupported", f"unsupported execution backend: {backend!r}")


def explain(plan: QueryPlan, *, backend: str) -> dict[str, Any]:
    validated = validate(plan)
    prepared = _adapter(backend).prepare(validated)
    return {**describe(validated), "execution": prepared.explain()}


def execute(plan: QueryPlan, *, backend: str) -> PlanResult:
    validated = validate(plan)
    prepared = _adapter(backend).prepare(validated)
    source: RecordSource | None = None
    try:
        source = RecordSource(Reader(validated.scan.sources, order=validated.scan.order))
        output = prepared.run(source)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(
            "execution_failed", f"query execution failed: {exc}", backend=backend
        ) from exc
    finally:
        if source is not None:
            source.close()
    return PlanResult(
        records=[row.record for row in output.rows],
        schema=output.schema,
        warnings=list(source.reader.warnings),
        metadata={
            "backend": backend,
            "input_rows": source.consumed,
            "output_rows": len(output.rows),
            "skipped_lines": source.reader.skipped_lines,
            "ordering": validated.properties.ordering,
            "preserves_record_identity": validated.properties.preserves_record_identity,
            "source_cursor_eligible": validated.properties.source_cursor_eligible,
        },
    )
