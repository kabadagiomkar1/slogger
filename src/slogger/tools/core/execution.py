"""Execution seam, source lifecycle, adapter dispatch and output reconstruction."""

from __future__ import annotations

from typing import Any

from ..errors import ToolError
from ..sources import Sources
from .optimization import normalize
from .plan import Limit, PlanResult, QueryPlan
from .planning import describe, validate
from .runtime import ExecutionAdapter


def _adapter(backend: str) -> ExecutionAdapter:
    if backend == "python":
        from ..backends.python.execution import PythonAdapter

        return PythonAdapter()
    if backend == "polars":
        from ..backends.polars.execution import PolarsAdapter

        return PolarsAdapter()
    raise ToolError("backend_unsupported", f"unsupported execution backend: {backend!r}")


def explain(plan: QueryPlan, *, backend: str) -> dict[str, Any]:
    validated = normalize(validate(plan), backend=backend)
    prepared = _adapter(backend).prepare(validated)
    return {**describe(validated), "execution": prepared.explain()}


def execute(plan: QueryPlan, *, backend: str) -> PlanResult:
    validated = normalize(validate(plan), backend=backend)
    prepared = _adapter(backend).prepare(validated)
    source: Sources | None = None
    try:
        # A zero limit annihilates all preceding input, including blocking stages.
        # Keep subsequent operations (e.g. empty ungrouped aggregation) executable.
        inputs = (
            []
            if any(isinstance(node, Limit) and node.count == 0 for node in validated.operations)
            else validated.scan.sources
        )
        source = Sources(inputs, order=validated.scan.order)
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
        origins=[row.origin for row in output.rows],
        warnings=list(source.warnings),
        metadata={
            "backend": backend,
            "input_rows": source.consumed,
            "output_rows": len(output.rows),
            "skipped_lines": source.skipped_lines,
            "ordering": validated.properties.ordering,
            "preserves_record_identity": validated.properties.preserves_record_identity,
        },
    )
