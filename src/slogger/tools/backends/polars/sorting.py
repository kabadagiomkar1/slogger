"""Native global sorting with explicit categories and authoritative row identity."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ...core.plan import Sort
from ...core.runtime import RecordRow
from ...errors import ToolError
from .binding import bind_batch


def sort_rows(
    rows: Iterable[RecordRow],
    node: Sort,
    *,
    operation: int,
    pl: Any,
) -> list[RecordRow]:
    """Sort all input at once; no per-batch result or implicit numeric coercion."""
    original = list(rows)
    if not original:
        return []
    try:
        frame, bindings = bind_batch(original, frozenset(((node.field,),)), pl)
    except ToolError as exc:
        raise ToolError(exc.code, exc.message, **{**exc.extra, "operation": operation}) from exc
    binding = bindings[(node.field,)]
    kinds = set(binding.lanes)
    if kinds - {"int", "float", "str"} or ("str" in kinds and len(kinds) > 1):
        raise ToolError(
            "data_incompatible",
            f"sort field {node.field!r} requires finite numbers or strings",
            field=[node.field],
            operation=operation,
        )
    if "int" in kinds and "float" in kinds:
        for name in binding.lanes.values():
            if any(value is not None and abs(value) >= 2**53 for value in frame[name]):
                raise ToolError(
                    "data_incompatible",
                    "mixed numeric sort may lose integer precision",
                    field=[node.field],
                    operation=operation,
                )
        value = pl.coalesce(
            pl.col(binding.lanes["int"]).cast(pl.Float64),
            pl.col(binding.lanes["float"]),
        )
    elif kinds:
        value = pl.col(next(iter(binding.lanes.values())))
    else:
        value = pl.lit(None, dtype=pl.Int64)
    category = (
        pl.when(~pl.col(binding.presence))
        .then(0 if node.missing == "first" else 4)
        .when(pl.col(binding.nulls))
        .then(1 if node.nulls == "first" else 3)
        .otherwise(2)
    )
    frame = frame.with_columns(
        category.alias("sort_category"),
        value.alias("sort_value"),
        pl.Series("source_ordinal", [row.ordinal for row in original], dtype=pl.UInt64),
    )
    selection = (
        frame.lazy()
        .sort(
            ["sort_category", "sort_value", "source_ordinal"],
            descending=[False, node.descending, False],
            nulls_last=True,
        )
        .select("ordinal")
        .collect()["ordinal"]
    )
    return [original[index] for index in selection]
