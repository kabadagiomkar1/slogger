"""Reference IXR compiler; executable artifacts stay outside logical nodes."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from ._field_access import _MISSING
from ._field_access import resolve_field as _resolve
from .ixr import (
    And,
    ArrayContains,
    Compare,
    Exists,
    Expression,
    In,
    Not,
    Or,
    StringMatch,
    _compatible,
    _equal,
    _numeric,
)

Matcher = Callable[[Mapping[str, Any]], bool]


def compile_expression(node: Expression) -> Matcher:
    if isinstance(node, (And, Or)):
        children = tuple(compile_expression(c) for c in node.children)
        return (
            (lambda record: all(c(record) for c in children))
            if isinstance(node, And)
            else (lambda record: any(c(record) for c in children))
        )
    if isinstance(node, Not):
        child = compile_expression(node.child)
        return lambda record: not child(record)
    expected: Any
    if isinstance(node, Compare):
        op, path, expected = node.op, node.left.path, node.right.value
    elif isinstance(node, (In, ArrayContains)):
        op = (
            ("not_in" if node.negated else "in")
            if isinstance(node, In)
            else "contains_" + node.mode
        )
        path, expected = node.field.path, tuple(c.value for c in node.candidates)
    elif isinstance(node, Exists):
        op, path, expected = "exists", node.field.path, None
    elif isinstance(node, StringMatch):
        op, path, expected = node.op, node.field.path, node.pattern
    else:
        raise TypeError("unsupported IXR expression")
    try:
        pattern = re.compile(expected) if op == "regex" else None
    except re.error as exc:
        raise ValueError(f"invalid predicate regex: {expected!r}") from exc

    def match(record: Mapping[str, Any]) -> bool:
        value = _resolve(record, path)
        if op == "missing":
            return value is _MISSING
        if op == "exists":
            return value is not _MISSING
        if value is _MISSING:
            return False
        if op in ("eq", "ne"):
            equal = _equal(value, expected)
            return equal if op == "eq" else _compatible(value, expected) and not equal
        if op in ("in", "not_in"):
            if value is not None and not isinstance(value, (str, bool, int, float)):
                return False
            found = any(_equal(value, item) for item in expected)
            compatible = not expected or any(_compatible(value, item) for item in expected)
            return found if op == "in" else compatible and not found
        if op in ("contains_any", "contains_all"):
            if not isinstance(value, (list, tuple)):
                return False
            checks = (any(_equal(item, candidate) for item in value) for candidate in expected)
            return any(checks) if op == "contains_any" else all(checks)
        if op in ("regex", "starts_with", "logger_prefix"):
            if not isinstance(value, str):
                return False
            if op == "regex":
                return pattern is not None and pattern.search(value) is not None
            return value.startswith(expected)
        if not (
            (_numeric(value) and _numeric(expected))
            or (isinstance(value, str) and isinstance(expected, str))
        ):
            return False
        if op == "gt":
            return bool(value > expected)
        if op == "ge":
            return bool(value >= expected)
        if op == "lt":
            return bool(value < expected)
        return bool(value <= expected)

    return match
