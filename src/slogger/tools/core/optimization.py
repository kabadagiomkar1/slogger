"""Conservative backend-aware normalization after original-plan validation."""

from __future__ import annotations

from dataclasses import replace

from .ixr import And, Expression, Not, Or
from .plan import Filter, Limit, PlanNode, Project, Scan
from .planning import ValidatedPlan


def normalize(plan: ValidatedPlan, *, backend: str) -> ValidatedPlan:
    operations: list[PlanNode] = []
    origins: list[tuple[int, ...]] = []
    rewrites: list[str] = []
    for index, node in enumerate(plan.operations):
        if isinstance(node, Scan):
            operations.append(node)
            origins.append((index,))
            continue
        if isinstance(node, Filter):
            expression = node.expression
            simplified = _boolean(expression)
            if simplified is not expression:
                node = replace(node, expression=simplified)
                rewrites.append("normalize_boolean_composition")
        previous = operations[-1]
        if (
            isinstance(node, Limit)
            and isinstance(previous, Limit)
            and (backend == "python" or previous.count <= node.count or node.count == 0)
        ):
            # Polars limits read batches: an outer smaller positive limit can read
            # ahead through the inner limit. Preserve that accounting by retaining it.
            operations[-1] = Limit(previous.input, min(previous.count, node.count))
            origins[-1] += (index,)
            rewrites.append("combine_adjacent_limits")
        elif isinstance(node, Project) and isinstance(previous, Project):
            # Original validation already established closed-schema field lineage.
            operations[-1] = Project(previous.input, node.fields)
            origins[-1] += (index,)
            rewrites.append("collapse_adjacent_projections")
        elif backend == "python" and isinstance(node, Filter) and isinstance(previous, Filter):
            expression = _boolean(And((previous.expression, node.expression)))
            operations[-1] = Filter(
                previous.input,
                expression,
            )
            origins[-1] += (index,)
            rewrites.append("combine_python_filters")
        else:
            operations.append(replace(node, input=previous))
            origins.append((index,))
    # Recompute dependencies after projection collapse, retaining all predicate fields.
    dependencies: set[tuple[str, ...]] = set()
    for node in operations:
        if isinstance(node, Filter):
            dependencies.update(node.expression.required_fields())
        elif isinstance(node, Project):
            dependencies.update((name,) for name in node.fields)
        else:
            # Sort and Aggregate dependencies/properties have already been validated;
            # preserve them without another duplicate visitor here.
            from .plan import Aggregate, Sort

            if isinstance(node, Sort):
                dependencies.add((node.field,))
            elif isinstance(node, Aggregate):
                dependencies.update((name,) for name in node.keys)
                dependencies.update(
                    spec.field.path for _, spec in node.aggregates if spec.field is not None
                )
    return replace(
        plan,
        root=operations[-1],
        operations=tuple(operations),
        required_fields=frozenset(dependencies),
        operation_origins=tuple(origins),
        rewrites=tuple(dict.fromkeys(rewrites)),
        original_operation_count=len(plan.operations),
    )


def _boolean(node: Expression) -> Expression:
    """Preserve child order and every nonconstant leaf's dependency/error domain."""
    if isinstance(node, (And, Or)):
        children: list[Expression] = []
        changed = False
        for child in node.children:
            normalized = _boolean(child)
            changed |= normalized is not child
            if type(normalized) is type(node):
                assert isinstance(normalized, (And, Or))
                children.extend(normalized.children)
                changed = True
            else:
                children.append(normalized)
        if len(children) == 1:
            return children[0]
        if not changed:
            return node
        return And(tuple(children)) if isinstance(node, And) else Or(tuple(children))
    if isinstance(node, Not):
        child = _boolean(node.child)
        if isinstance(child, Not):
            return child.child
        return node if child is node.child else Not(child)
    return node
