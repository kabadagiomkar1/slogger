"""Native global reductions with checked numeric lanes and lossless group output."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._columnar import FieldBinding, bind_batch
from ._execution import RecordRow
from .errors import ToolError
from .plan import Aggregate


def _numeric(binding: FieldBinding, frame: Any, pl: Any) -> tuple[Any, bool]:
    if set(binding.lanes) - {"int", "float"}:
        raise ToolError(
            "data_incompatible",
            "numeric aggregate requires finite numbers",
            field=list(binding.path),
        )
    if "int" in binding.lanes and "float" in binding.lanes:
        for name in binding.lanes.values():
            if any(value is not None and abs(value) >= 2**53 for value in frame[name]):
                raise ToolError(
                    "data_incompatible",
                    "mixed numeric reduction may lose precision",
                    field=list(binding.path),
                )
        return pl.coalesce(
            [pl.col(binding.lanes["int"]).cast(pl.Float64), pl.col(binding.lanes["float"])]
        ), False
    if "float" in binding.lanes:
        return pl.col(binding.lanes["float"]), False
    if "int" in binding.lanes:
        return pl.col(binding.lanes["int"]), True
    return pl.lit(None).cast(pl.Int64), True


def aggregate_rows(rows: Iterable[RecordRow], node: Aggregate, pl: Any) -> list[RecordRow]:
    """Materialize the full upstream input; never finalize per-batch groups."""
    batch = list(rows)
    paths = frozenset((key,) for key in node.keys) | frozenset(
        spec.field.path for _, spec in node.aggregates if spec.field is not None
    )
    frame, bindings = bind_batch(batch, paths, pl)
    group_columns = []
    for index, key in enumerate(node.keys):
        binding = bindings[(key,)]
        group_columns.extend([binding.presence, binding.nulls])
        for kind in ("bool", "str"):
            if kind in binding.lanes:
                group_columns.append(binding.lanes[kind])
        numeric_lanes = {
            kind: name for kind, name in binding.lanes.items() if kind in ("int", "float")
        }
        if numeric_lanes:
            numeric_binding = FieldBinding(
                binding.path, binding.presence, binding.nulls, numeric_lanes
            )
            number, _ = _numeric(numeric_binding, frame, pl)
            name = f"group_number_{index}"
            frame = frame.with_columns(number.alias(name))
            group_columns.append(name)
    reductions = [pl.col("ordinal").min().alias("first_ordinal")]
    integer_sums = []
    for index, (_, spec) in enumerate(node.aggregates):
        name = f"aggregate_{index}"
        if spec.op == "count":
            expression = pl.len()
        else:
            assert spec.field is not None
            number, integer = _numeric(bindings[spec.field.path], frame, pl)
            if spec.op == "sum":
                if integer:
                    # A finite materialized Int64 source cannot realistically overflow
                    # Int128; still check the result before output conversion.
                    expression = number.cast(pl.Int128).sum()
                    integer_sums.append(name)
                else:
                    expression = number.sum()
            elif spec.op == "mean":
                expression = number.mean()
            elif spec.op == "min":
                expression = number.min()
            else:
                expression = number.max()
        reductions.append(expression.alias(name))
    if node.keys:
        result = frame.lazy().group_by(group_columns, maintain_order=True).agg(reductions).collect()
    else:
        result = frame.lazy().select(reductions).collect()
    output = []
    for ordinal, values in enumerate(result.iter_rows(named=True)):
        for name in integer_sums:
            if not -(2**63) <= values[name] < 2**63:
                raise ToolError("data_incompatible", "integer sum is outside Int64 range")
        first = values["first_ordinal"]
        record = (
            {}
            if first is None
            else {key: batch[first].record[key] for key in node.keys if key in batch[first].record}
        )
        for index, (name, _) in enumerate(node.aggregates):
            record[name] = values[f"aggregate_{index}"]
        output.append(RecordRow(record, ordinal, None))
    return output
