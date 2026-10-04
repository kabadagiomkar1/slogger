"""Exact typed grouping and numeric reference reductions."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

from ...core.fields import _MISSING
from ...core.fields import resolve_field as _resolve
from ...core.plan import Aggregate
from ...core.runtime import RecordRow
from ...errors import ToolError


def _key(value: Any, field: str) -> tuple[str, Any]:
    if value is _MISSING:
        return ("missing", None)
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ToolError("data_incompatible", "group keys must be finite", field=field)
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    raise ToolError("data_incompatible", "group keys must be scalar", field=field)


def aggregate_rows(rows: Iterable[RecordRow], node: Aggregate) -> list[RecordRow]:
    groups: dict[tuple[Any, ...], tuple[dict[str, Any], list[list[Any]], int]] = {}
    if not node.keys:
        groups[()] = ({}, [[] for _ in node.aggregates], 0)
    for row in rows:
        values = tuple(row.record.get(key, _MISSING) for key in node.keys)
        identity = tuple(_key(value, key) for key, value in zip(node.keys, values, strict=True))
        if identity not in groups:
            groups[identity] = (
                {
                    key: value
                    for key, value in zip(node.keys, values, strict=True)
                    if value is not _MISSING
                },
                [[] for _ in node.aggregates],
                len(groups),
            )
        record, states, ordinal = groups[identity]
        for (_, spec), state in zip(node.aggregates, states, strict=True):
            if spec.op == "count":
                state.append(1)
                continue
            assert spec.field is not None
            value = _resolve(row.record, spec.field.path)
            if value is _MISSING or value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not math.isfinite(value))
            ):
                raise ToolError(
                    "data_incompatible",
                    "numeric aggregate requires finite numbers",
                    field=list(spec.field.path),
                    aggregate=spec.op,
                )
            state.append(value)
    output = []
    for record, states, ordinal in groups.values():
        result = dict(record)
        for (name, spec), state in zip(node.aggregates, states, strict=True):
            if spec.op == "count":
                value = len(state)
            elif spec.op == "sum":
                value = _checked_sum(state)
            elif not state:
                value = None
            elif spec.op == "mean":
                value = _checked_mean(state)
            elif spec.op == "min":
                value = min(state)
            else:
                value = max(state)
            if isinstance(value, float) and not math.isfinite(value):
                raise ToolError(
                    "data_incompatible", "numeric aggregate result is nonfinite", aggregate=spec.op
                )
            result[name] = value
        output.append(RecordRow(result, ordinal, None))
    return output


def _checked_sum(values: list[Any]) -> Any:
    return checked_numeric_sum(values, any(isinstance(value, float) for value in values))


def checked_numeric_sum(values: Iterable[Any], has_float: bool) -> Any:
    """Finalize an already validated original sequence, including disk replay."""
    try:
        result = math.fsum(values) if has_float else sum(values)
    except OverflowError as exc:
        raise ToolError("data_incompatible", "numeric aggregate overflow") from exc
    if isinstance(result, float) and not math.isfinite(result):
        raise ToolError("data_incompatible", "numeric aggregate sum is nonfinite")
    return result


def _checked_mean(values: list[Any]) -> float:
    try:
        return _checked_sum(values) / len(values)
    except OverflowError as exc:
        raise ToolError("data_incompatible", "numeric aggregate mean overflow") from exc


def scalar_group_identity(value: Any, label: str) -> bytes:
    """Lossless disk spelling of reference scalar equality, including numeric ties."""
    kind, scalar = _key(value, label)
    if kind == "number":
        numerator, denominator = (
            scalar.as_integer_ratio() if isinstance(scalar, float) else (scalar, 1)
        )
        identity = (kind, numerator, denominator)
    else:
        identity = (kind, scalar)
    return json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def checked_numeric_metric(op: str, values: Iterable[Any], count: int, has_float: bool) -> Any:
    """Shared reference finalization; callers supply a fresh original-order sequence."""
    if op == "sum":
        return checked_numeric_sum(values, has_float)
    if not count:
        return None
    if op == "mean":
        try:
            return checked_numeric_sum(values, has_float) / count
        except OverflowError as exc:
            raise ToolError("data_incompatible", "numeric aggregate mean overflow") from exc
    return min(values) if op == "min" else max(values)
