"""Composable typed predicates for reading structured logs."""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Field", "Predicate", "all_of", "any_of", "logger_prefix", "not_"]

Matcher = Callable[[Mapping[str, Any]], bool]
_MISSING = object()


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
                return _Object(tuple((key, _snapshot(item, active)) for key, item in value.items()))
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


def _resolve(record: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for segment in path:
        if not isinstance(value, Mapping) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


class Predicate(ABC):
    """Expression built by Field methods and composition functions.

    Use matches() for individual records or compile() for a reusable callable.
    Concrete immutable expression nodes are private implementation details.
    """

    def __bool__(self) -> bool:
        raise TypeError("use all_of(), any_of(), or not_() to compose predicates")

    @abstractmethod
    def compile(self) -> Matcher:
        """Return the reusable, precompiled record matcher."""
        ...

    def matches(self, record: Mapping[str, Any]) -> bool:
        """Evaluate this expression without mutating the record."""
        return self.compile()(record)

    @abstractmethod
    def explain(self) -> dict[str, Any]:
        """Return a detached JSON-compatible inspection description."""
        ...


@dataclass(frozen=True, eq=False)
class _Expression(Predicate):
    _op: str
    _path: tuple[str, ...] = ()
    _value: Any = None
    _children: tuple[Predicate, ...] = ()
    _matcher: Matcher = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_matcher", self._build_matcher())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _Expression):
            return NotImplemented
        return (
            self._op == other._op
            and self._path == other._path
            and self._children == other._children
            and _equal(_describe(self._value), other._value)
        )

    def compile(self) -> Matcher:
        return self._matcher

    def explain(self) -> dict[str, Any]:
        """Return a JSON-compatible inspection description (not an input syntax)."""
        if self._op in ("all", "any", "not"):
            return {"op": self._op, "children": [child.explain() for child in self._children]}
        result: dict[str, Any] = {"op": self._op, "path": list(self._path)}
        if self._op not in ("exists", "missing"):
            result["value"] = _describe(self._value)
        return result

    def _build_matcher(self) -> Matcher:
        op, path, expected = self._op, self._path, self._value
        children = tuple(child.compile() for child in self._children)
        if op == "all":
            return lambda record: all(match(record) for match in children)
        if op == "any":
            return lambda record: any(match(record) for match in children)
        if op == "not":
            return lambda record: not children[0](record)
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
                if op == "logger_prefix":
                    return value == expected or value.startswith(expected + ".")
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


@dataclass(frozen=True, init=False)
class Field:
    """A literal key or explicit mapping path: Field('request', 'method')."""

    path: tuple[str, ...]

    def __init__(self, *path: str) -> None:
        if not path or any(not isinstance(segment, str) or not segment for segment in path):
            raise ValueError("Field requires one or more nonempty string path segments")
        object.__setattr__(self, "path", path)

    def _comparison(self, op: str, value: Any) -> Predicate:
        operand = _snapshot(value)
        if op in ("gt", "ge", "lt", "le") and not (_numeric(operand) or isinstance(operand, str)):
            raise TypeError("ordering operands must be numbers or strings")
        return _Expression(op, self.path, operand)

    def eq(self, value: Any) -> Predicate:
        """Match typed equality, including structural JSON equality."""
        return self._comparison("eq", value)

    def ne(self, value: Any) -> Predicate:
        """Match unequal compatible values; missing fields do not match."""
        return self._comparison("ne", value)

    def gt(self, value: Any) -> Predicate:
        """Match values greater than value."""
        return self._comparison("gt", value)

    def ge(self, value: Any) -> Predicate:
        """Match values greater than or equal to value."""
        return self._comparison("ge", value)

    def lt(self, value: Any) -> Predicate:
        """Match values less than value."""
        return self._comparison("lt", value)

    def le(self, value: Any) -> Predicate:
        """Match values less than or equal to value."""
        return self._comparison("le", value)

    def _membership(self, op: str, values: Iterable[Any]) -> Predicate:
        if isinstance(values, (str, bytes, Mapping)):
            raise TypeError("membership requires an iterable of scalar candidates")
        operands = tuple(_snapshot(value) for value in values)
        if any(isinstance(value, (tuple, _Object)) for value in operands):
            raise TypeError("membership candidates must be JSON scalars")
        return _Expression(op, self.path, operands)

    def in_(self, values: Iterable[Any]) -> Predicate:
        """Match a scalar against any candidate."""
        return self._membership("in", values)

    def not_in(self, values: Iterable[Any]) -> Predicate:
        """Exclude candidates; missing and incompatible values do not match."""
        return self._membership("not_in", values)

    def contains_any(self, values: Iterable[Any]) -> Predicate:
        """Match arrays containing at least one candidate."""
        return self._membership("contains_any", values)

    def contains_all(self, values: Iterable[Any]) -> Predicate:
        """Match arrays containing every candidate, without multiplicity checks."""
        return self._membership("contains_all", values)

    def exists(self) -> Predicate:
        """Match present fields, including null."""
        return _Expression("exists", self.path)

    def missing(self) -> Predicate:
        """Match absent fields or unresolved mapping paths."""
        return _Expression("missing", self.path)

    def regex(self, pattern: str) -> Predicate:
        """Search string fields with a Python regular expression."""
        if not isinstance(pattern, str):
            raise TypeError("regex requires a string pattern")
        return _Expression("regex", self.path, pattern)

    def starts_with(self, prefix: str) -> Predicate:
        """Match strings starting with prefix."""
        if not isinstance(prefix, str):
            raise TypeError("starts_with requires a string prefix")
        return _Expression("starts_with", self.path, prefix)


def _compose(op: str, predicates: tuple[Predicate, ...]) -> Predicate:
    if any(not isinstance(predicate, Predicate) for predicate in predicates):
        raise TypeError("composition requires Predicate operands")
    return _Expression(op, _children=predicates)


def all_of(*predicates: Predicate) -> Predicate:
    """Match every child; zero children match all records."""
    return _compose("all", predicates)


def any_of(*predicates: Predicate) -> Predicate:
    """Match any child; zero children match no records."""
    return _compose("any", predicates)


def not_(predicate: Predicate) -> Predicate:
    """Logically negate a predicate, including its missing-field result."""
    return _compose("not", (predicate,))


def logger_prefix(name: str) -> Predicate:
    """Match an exact logger name or its stdlib hierarchy descendants."""
    if not isinstance(name, str) or not name:
        raise ValueError("logger_prefix requires a nonempty string name")
    return _Expression("logger_prefix", ("logger",), name)
