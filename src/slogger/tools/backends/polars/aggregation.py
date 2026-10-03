"""Native global reductions with checked numeric lanes and lossless group output."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from ...core.plan import Aggregate
from ...core.runtime import RecordRow
from ...errors import ToolError
from .binding import FieldBinding, bind_batch


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
        if set(binding.lanes) - {"bool", "str", "int", "float"}:
            raise ToolError("data_incompatible", "group keys must be scalar", field=key)
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
    finite_sums = []
    for index, (_, spec) in enumerate(node.aggregates):
        name = f"aggregate_{index}"
        if spec.op == "count":
            expression = pl.len()
        else:
            assert spec.field is not None
            number, integer = _numeric(bindings[spec.field.path], frame, pl)
            total: Any = None
            if spec.op in ("sum", "mean") and not integer:
                frame, total = _scaled_float_sum(number, frame, pl, index, spec.field.path)
            if spec.op == "sum":
                if integer:
                    # A finite materialized Int64 source cannot realistically overflow
                    # Int128; still check the result before output conversion.
                    expression = number.cast(pl.Int128).sum()
                    integer_sums.append(name)
                else:
                    expression = total
            elif spec.op == "mean":
                numerator = number.cast(pl.Int128).sum().cast(pl.Float64) if integer else total
                expression = (
                    pl.when(number.count() > 0).then(numerator / number.count()).otherwise(None)
                )
                if not integer:
                    check_name = f"mean_sum_{index}"
                    reductions.append(total.alias(check_name))
                    finite_sums.append(check_name)
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
        for name in finite_sums:
            value = values[name]
            if value is not None and not math.isfinite(value):
                raise ToolError("data_incompatible", "numeric aggregate mean sum is nonfinite")
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
            value = values[f"aggregate_{index}"]
            if isinstance(value, float) and not math.isfinite(value):
                raise ToolError("data_incompatible", "numeric aggregate result is nonfinite")
            record[name] = value
        output.append(RecordRow(record, ordinal, None))
    return output


def _scaled_float_sum(
    number: Any, frame: Any, pl: Any, index: int, path: tuple[str, ...]
) -> tuple[Any, Any]:
    """Convert exact binary ratios to a checked fixed-point native Int128 lane.

    Python performs representation conversion and range checks only. Polars sums
    the lane globally/per group, so cancellation and repeated-fraction accumulation
    never depend on a backend floating reduction algorithm.
    """
    values = frame.select(number.alias("values"))["values"].to_list()
    ratios = [None if value is None else value.as_integer_ratio() for value in values]
    scale = max((ratio[1] for ratio in ratios if ratio is not None), default=1)
    scaled = [None if ratio is None else ratio[0] * (scale // ratio[1]) for ratio in ratios]
    maximum = max((abs(value) for value in scaled if value is not None), default=0)
    if scale > 2**1023 or maximum * len(values) >= 2**127:
        raise ToolError(
            "data_incompatible",
            "floating reduction exceeds exact native lane range",
            field=list(path),
        )
    name = f"scaled_float_{index}"
    frame = frame.with_columns(pl.Series(name, scaled, dtype=pl.Int128, strict=True))
    return frame, pl.col(name).sum().cast(pl.Float64) / float(scale)
