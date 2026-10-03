"""Lossless referenced-field conversion; original records stay authoritative."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ._execution import RecordRow
from .errors import ToolError
from .ixr import _MISSING


@dataclass(frozen=True)
class FieldBinding:
    path: tuple[str, ...]
    presence: str
    nulls: str
    lanes: Mapping[str, str]


def _resolve(record: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for segment in path:
        if not isinstance(value, Mapping) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


def bind_batch(
    rows: list[RecordRow],
    paths: frozenset[tuple[str, ...]],
    pl: Any,
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
        kinds = {type(v) for v in values if v is not _MISSING and v is not None}
        if not kinds.issubset(dtypes):
            raise ToolError(
                "data_incompatible",
                "referenced field contains unsupported values",
                field=list(path),
            )
        lanes = {}
        for kind in kinds:
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
        bindings[path] = FieldBinding(path, presence, nulls, MappingProxyType(lanes))
    return pl.DataFrame(columns), bindings
