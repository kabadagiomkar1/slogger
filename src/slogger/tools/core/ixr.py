"""Immutable execution-independent expression representation (inspection version 1)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Literal as TypingLiteral

from .fields import _MISSING as _MISSING

__all__ = [
    "Expression",
    "FieldRef",
    "Literal",
    "Compare",
    "In",
    "Exists",
    "StringMatch",
    "ArrayContains",
    "And",
    "Or",
    "Not",
]


def _snapshot(value: Any, active: set[int] | None = None) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (list, tuple, Mapping)):
        active = set() if active is None else active
        identity = id(value)
        if identity in active:
            raise TypeError("predicate operands cannot contain cycles")
        active.add(identity)
        try:
            if isinstance(value, (list, tuple)):
                return tuple(_snapshot(item, active) for item in value)
            if all(isinstance(key, str) for key in value):
                return _Object(
                    tuple((key, _snapshot(item, active)) for key, item in sorted(value.items()))
                )
        finally:
            active.remove(identity)
    raise TypeError("predicate operands must be finite JSON-compatible values")


@dataclass(frozen=True)
class _Object:
    items: tuple[tuple[str, Any], ...]


def _describe(value: Any) -> Any:
    if isinstance(value, _Object):
        return {key: _describe(item) for key, item in value.items}
    if isinstance(value, tuple):
        return [_describe(item) for item in value]
    return value


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _compatible(left: Any, right: Any) -> bool:
    if _numeric(left) and _numeric(right):
        return True
    if isinstance(right, _Object):
        return isinstance(left, Mapping)
    if isinstance(right, tuple):
        return isinstance(left, (list, tuple))
    return type(left) is type(right)


def _equal(left: Any, right: Any) -> bool:
    if not _compatible(left, right):
        return False
    if isinstance(right, _Object):
        return len(left) == len(right.items) and all(
            key in left and _equal(left[key], value) for key, value in right.items
        )
    if isinstance(right, tuple):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


class Expression:
    """Immutable logical nodes; execution is owned by adapters."""

    def __bool__(self) -> bool:
        raise TypeError("use all_of(), any_of(), not_(), &, |, or ~ to compose expressions")

    def __and__(self, other: Expression) -> Expression:
        return And((self, other))

    def __or__(self, other: Expression) -> Expression:
        return Or((self, other))

    def __invert__(self) -> Expression:
        return Not(self)

    def __post_init__(self) -> None:
        """Reject malformed version-one nodes before an adapter sees them."""
        if isinstance(self, FieldRef):
            if (
                not isinstance(self.path, tuple)
                or not self.path
                or any(not isinstance(segment, str) or not segment for segment in self.path)
            ):
                raise ValueError("FieldRef requires a tuple of nonempty path segments")
        elif isinstance(self, Compare):
            if self.op not in ("eq", "ne", "gt", "ge", "lt", "le"):
                raise ValueError("unknown comparison operator")
            if not isinstance(self.left, FieldRef) or not isinstance(self.right, Literal):
                raise TypeError("IXR version 1 comparisons require a field and literal")
            if self.op in ("gt", "ge", "lt", "le") and not (
                _numeric(self.right.value) or isinstance(self.right.value, str)
            ):
                raise TypeError("ordering operands must be numbers or strings")
        elif isinstance(self, (And, Or)):
            if not isinstance(self.children, tuple) or any(
                not _boolean(child) for child in self.children
            ):
                raise TypeError("boolean composition requires a tuple of boolean expressions")
        elif isinstance(self, Not):
            if not _boolean(self.child):
                raise TypeError("Not requires a boolean expression")
        elif isinstance(self, (In, Exists, StringMatch, ArrayContains)):
            if not isinstance(self.field, FieldRef):
                raise TypeError("expression requires a FieldRef")
            if isinstance(self, (In, ArrayContains)):
                if not isinstance(self.candidates, tuple) or any(
                    not isinstance(c, Literal) or isinstance(c.value, (tuple, _Object))
                    for c in self.candidates
                ):
                    raise TypeError("membership requires a tuple of scalar literals")
            if isinstance(self, In) and not isinstance(self.negated, bool):
                raise TypeError("membership negated must be boolean")
            if isinstance(self, ArrayContains) and self.mode not in ("any", "all"):
                raise ValueError("unknown array membership mode")
            if isinstance(self, StringMatch):
                if self.op not in ("regex", "starts_with"):
                    raise ValueError("unknown string operator")
                if not isinstance(self.pattern, str):
                    raise TypeError("string matching requires a string pattern")
                if self.op == "regex":
                    try:
                        re.compile(self.pattern)
                    except re.error as exc:
                        raise ValueError("invalid predicate regex") from exc

    def required_fields(self) -> frozenset[tuple[str, ...]]:
        return _dependencies(self)

    def explain(self) -> dict[str, Any]:
        return {"version": 1, "expression": _inspect(self)}


@dataclass(frozen=True)
class FieldRef(Expression):
    path: tuple[str, ...]


@dataclass(frozen=True, init=False, eq=False)
class Literal(Expression):
    value: Any

    def __init__(self, value: Any) -> None:
        object.__setattr__(self, "value", _snapshot(value))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Literal) and _equal(_describe(self.value), other.value)


@dataclass(frozen=True)
class Compare(Expression):
    op: TypingLiteral["eq", "ne", "gt", "ge", "lt", "le"]
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class In(Expression):
    field: FieldRef
    candidates: tuple[Literal, ...]
    negated: bool = False


@dataclass(frozen=True)
class Exists(Expression):
    field: FieldRef


@dataclass(frozen=True)
class StringMatch(Expression):
    op: TypingLiteral["regex", "starts_with"]
    field: FieldRef
    pattern: str


@dataclass(frozen=True)
class ArrayContains(Expression):
    mode: TypingLiteral["any", "all"]
    field: FieldRef
    candidates: tuple[Literal, ...]


@dataclass(frozen=True)
class And(Expression):
    children: tuple[Expression, ...]


@dataclass(frozen=True)
class Or(Expression):
    children: tuple[Expression, ...]


@dataclass(frozen=True)
class Not(Expression):
    child: Expression


def _boolean(node: Expression) -> bool:
    return isinstance(node, (Compare, In, Exists, StringMatch, ArrayContains, And, Or, Not))


def _dependencies(node: Expression) -> frozenset[tuple[str, ...]]:
    if isinstance(node, FieldRef):
        return frozenset((node.path,))
    if isinstance(node, Literal):
        return frozenset()
    if isinstance(node, (And, Or)):
        return frozenset(path for child in node.children for path in child.required_fields())
    if isinstance(node, Not):
        return node.child.required_fields()
    if isinstance(node, Compare):
        return node.left.required_fields() | node.right.required_fields()
    if isinstance(node, (In, Exists, StringMatch, ArrayContains)):
        return node.field.required_fields()
    raise TypeError("unsupported IXR expression")


def _inspect(node: Expression) -> dict[str, Any]:
    if isinstance(node, FieldRef):
        return {"op": "field", "path": list(node.path)}
    if isinstance(node, Literal):
        value = node.value
        kind = (
            "object"
            if isinstance(value, _Object)
            else "array"
            if isinstance(value, tuple)
            else "null"
            if value is None
            else "bool"
            if isinstance(value, bool)
            else "number"
            if _numeric(value)
            else "string"
        )
        return {"op": "literal", "type": kind, "value": _describe(value)}
    if isinstance(node, Compare):
        return {"op": node.op, "left": _inspect(node.left), "right": _inspect(node.right)}
    if isinstance(node, (And, Or)):
        return {
            "op": "all" if isinstance(node, And) else "any",
            "children": [_inspect(c) for c in node.children],
        }
    if isinstance(node, Not):
        return {"op": "not", "children": [_inspect(node.child)]}
    if not isinstance(node, (In, Exists, StringMatch, ArrayContains)):
        raise TypeError("unsupported IXR expression")
    result: dict[str, Any] = {"op": "exists", "field": _inspect(node.field)}
    if isinstance(node, (In, ArrayContains)):
        result["op"] = (
            ("not_in" if node.negated else "in")
            if isinstance(node, In)
            else "contains_" + node.mode
        )
        result["candidates"] = [_inspect(c) for c in node.candidates]
    if isinstance(node, StringMatch):
        result.update(op=node.op, pattern=node.pattern)
    return result
