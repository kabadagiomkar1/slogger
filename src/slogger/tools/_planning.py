"""Static plan validation; never resolves or reads a source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ToolError
from .plan import Filter, Limit, PlanNode, Project, QueryPlan, Scan


@dataclass(frozen=True)
class PlanProperties:
    schema: tuple[str, ...] | None
    ordering: str
    preserves_record_identity: bool = True
    finite_source_required: bool = True
    output_bound: int | None = None


@dataclass(frozen=True)
class ValidatedPlan:
    root: PlanNode
    scan: Scan
    properties: PlanProperties
    required_fields: frozenset[tuple[str, ...]]
    operations: tuple[PlanNode, ...]


def validate(plan: QueryPlan) -> ValidatedPlan:
    """Validate lineage against open scans and closed projected schemas."""
    operations = _operations(plan._node)
    source = operations[0]
    assert isinstance(source, Scan)
    schema: tuple[str, ...] | None = None
    bound: int | None = None
    required: set[tuple[str, ...]] = set()
    for index, node in enumerate(operations[1:], 1):
        if isinstance(node, Filter):
            try:
                dependencies = node.predicate.to_ixr().required_fields()
            except TypeError as exc:
                raise ToolError(
                    "expression_unsupported",
                    "plan filters require representable IXR",
                    operation=index,
                ) from exc
            _check_fields(dependencies, schema, index)
            required.update(dependencies)
        elif isinstance(node, Project):
            dependencies = frozenset((name,) for name in node.fields)
            _check_fields(dependencies, schema, index)
            required.update(dependencies)
            schema = node.fields
        elif isinstance(node, Limit):
            bound = node.count if bound is None else min(bound, node.count)
        else:
            raise ToolError("plan_invalid", "unsupported logical plan node", operation=index)
    return ValidatedPlan(
        plan._node,
        source,
        PlanProperties(schema, source.order, output_bound=bound),
        frozenset(required),
        operations,
    )


def _check_fields(
    dependencies: frozenset[tuple[str, ...]],
    schema: tuple[str, ...] | None,
    index: int,
) -> None:
    if schema is None:
        return
    for path in dependencies:
        if path[0] not in schema:
            raise ToolError(
                "plan_invalid",
                f"field {path!r} is unavailable after projection",
                operation=index,
                field=list(path),
            )


def _operations(root: PlanNode) -> tuple[PlanNode, ...]:
    nodes: list[PlanNode] = []
    node = root
    while not isinstance(node, Scan):
        nodes.append(node)
        node = node.input
    nodes.append(node)
    return tuple(reversed(nodes))


def describe(plan: ValidatedPlan) -> dict[str, Any]:
    """Return detached, source-free logical inspection."""
    operations: list[dict[str, Any]] = []
    for node in plan.operations:
        if isinstance(node, Scan):
            operations.append({"op": "scan", "order": node.order})
        elif isinstance(node, Filter):
            operations.append({"op": "filter", "expression": node.predicate.to_ixr().explain()})
        elif isinstance(node, Project):
            operations.append({"op": "project", "fields": list(node.fields)})
        elif isinstance(node, Limit):
            operations.append({"op": "limit", "count": node.count})
    properties = plan.properties
    return {
        "version": 1,
        "operations": operations,
        "required_fields": [list(path) for path in sorted(plan.required_fields)],
        "properties": {
            "schema": None if properties.schema is None else list(properties.schema),
            "schema_open": properties.schema is None,
            "ordering": properties.ordering,
            "preserves_record_identity": properties.preserves_record_identity,
            "finite_source_required": properties.finite_source_required,
            "output_bound": properties.output_bound,
        },
        "pending_data_checks": ["source availability", "finite input"],
    }
