"""Global reference sorting with exact values and opaque stable tie identity."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from ...core.runtime import RecordRow
from ...errors import ToolError
from ...plan import Sort


def sort_rows(rows: Iterable[RecordRow], node: Sort, *, operation: int) -> list[RecordRow]:
    """Materialize the input domain and order values without coercion."""
    values: list[RecordRow] = []
    missing: list[RecordRow] = []
    nulls: list[RecordRow] = []
    domain: str | None = None
    for row in rows:
        if node.field not in row.record:
            missing.append(row)
            continue
        value = row.record[node.field]
        if value is None:
            nulls.append(row)
            continue
        kind = _domain(value, field=node.field, operation=operation)
        if domain is not None and domain != kind:
            raise ToolError(
                "data_incompatible",
                f"sort field {node.field!r} mixes numeric and string values",
                field=[node.field],
                operation=operation,
            )
        domain = kind
        values.append(row)
    # Establish original identity before a stable value sort, including repeated Sorts.
    values.sort(key=lambda row: row.ordinal)
    values.sort(key=lambda row: row.record[node.field], reverse=node.descending)
    missing.sort(key=lambda row: row.ordinal)
    nulls.sort(key=lambda row: row.ordinal)
    output: list[RecordRow] = []
    if node.missing == "first":
        output.extend(missing)
    if node.nulls == "first":
        output.extend(nulls)
    output.extend(values)
    if node.nulls == "last":
        output.extend(nulls)
    if node.missing == "last":
        output.extend(missing)
    return output


def _domain(value: Any, *, field: str, operation: int) -> str:
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not isinstance(value, float) or math.isfinite(value):
            return "number"
    raise ToolError(
        "data_incompatible",
        f"sort field {field!r} requires finite numbers or strings",
        field=[field],
        operation=operation,
        value_type=type(value).__name__,
    )
