"""Lossless referenced-field conversion; original records stay authoritative."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ._execution import RecordRow
from ._field_access import _MISSING
from ._field_access import resolve_field as _resolve
from .errors import ToolError


@dataclass(frozen=True)
class FieldBinding:
    path: tuple[str, ...]
    presence: str
    nulls: str
    lanes: Mapping[str, str]


def bind_batch(
    rows: list[RecordRow],
    paths: frozenset[tuple[str, ...]],
    pl: Any,
    *,
    presence_only: frozenset[tuple[str, ...]] = frozenset(),
) -> tuple[Any, dict[tuple[str, ...], FieldBinding]]:
    """Build only referenced columns with explicit types and per-row masks.

    Physical slots never share a namespace with user keys. Every batch is profiled
    independently, so late fields/type lanes are neither discarded nor coerced.
    """
    columns: dict[str, Any] = {"ordinal": pl.Series(range(len(rows)))}
    bindings = {}
    dtypes = {
        bool: ("bool", pl.Boolean),
        int: ("int", pl.Int64),
        float: ("float", pl.Float64),
        str: ("str", pl.String),
    }
    for index, path in enumerate(sorted(paths)):
        values = [_resolve(row.record, path) for row in rows]
        presence, nulls = f"field_{index}_present", f"field_{index}_null"
        columns[presence] = pl.Series(presence, [v is not _MISSING for v in values], pl.Boolean)
        columns[nulls] = pl.Series(nulls, [v is None for v in values], pl.Boolean)
        if path in presence_only:
            bindings[path] = FieldBinding(path, presence, nulls, MappingProxyType({}))
            continue
        kinds = {type(v) for v in values if v is not _MISSING and v is not None}
        scalar_kinds = kinds - {list, tuple}
        if not scalar_kinds.issubset(dtypes):
            raise ToolError(
                "data_incompatible",
                "referenced field contains unsupported values",
                field=list(path),
            )
        lanes = {}
        for kind in scalar_kinds:
            lane, dtype = dtypes[kind]
            name = f"field_{index}_{lane}"
            selected = [v if type(v) is kind else None for v in values]
            for value in selected:
                if kind is int and value is not None and not -(2**63) <= value < 2**63:
                    raise ToolError(
                        "data_incompatible",
                        "integer field is outside Int64 range",
                        field=list(path),
                    )
                if kind is float and value is not None and not math.isfinite(value):
                    raise ToolError(
                        "data_incompatible", "nonfinite numeric field", field=list(path)
                    )
            columns[name] = pl.Series(name, selected, dtype=dtype, strict=True)
            lanes[lane] = name
        array_kinds = [
            _array_kind(v, path) if isinstance(v, (list, tuple)) else None for v in values
        ]
        array_dtypes = {
            "bool": pl.Boolean,
            "int": pl.Int64,
            "float": pl.Float64,
            "str": pl.String,
            "null": pl.Null,
        }
        for kind in set(array_kinds) - {None}:
            assert kind is not None
            name = f"field_{index}_array_{kind}"
            selected_arrays = [
                list(value) if array_kind == kind else None
                for value, array_kind in zip(values, array_kinds, strict=True)
            ]
            columns[name] = pl.Series(
                name, selected_arrays, dtype=pl.List(array_dtypes[kind]), strict=True
            )
            lanes[f"array_{kind}"] = name
        bindings[path] = FieldBinding(path, presence, nulls, MappingProxyType(lanes))
    return pl.DataFrame(columns), bindings


def _array_kind(value: list[Any] | tuple[Any, ...], path: tuple[str, ...]) -> str:
    kinds = {type(item) for item in value if item is not None}
    if len(kinds) > 1 or not kinds.issubset({bool, int, float, str}):
        raise ToolError(
            "data_incompatible", "arrays require homogeneous scalar members", field=list(path)
        )
    kind = next(iter(kinds), type(None))
    for item in value:
        if type(item) is int and not -(2**63) <= item < 2**63:
            raise ToolError(
                "data_incompatible", "array integer is outside Int64 range", field=list(path)
            )
        if type(item) is float and not math.isfinite(item):
            raise ToolError("data_incompatible", "nonfinite array number", field=list(path))
    return {bool: "bool", int: "int", float: "float", str: "str", type(None): "null"}[kind]
