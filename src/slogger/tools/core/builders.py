"""Convenient builders for immutable IXR expressions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from typing import Literal as TypingLiteral

from .ixr import (
    And,
    ArrayContains,
    Compare,
    Exists,
    Expression,
    FieldRef,
    In,
    Literal,
    Not,
    Or,
    StringMatch,
)

__all__ = ["Field", "all_of", "any_of", "logger_prefix", "not_"]


@dataclass(frozen=True, init=False)
class Field:
    """A literal key or explicit mapping path: Field('request', 'method')."""

    path: tuple[str, ...]

    def __init__(self, *path: str) -> None:
        if not path or any(not isinstance(segment, str) or not segment for segment in path):
            raise ValueError("Field requires one or more nonempty string path segments")
        object.__setattr__(self, "path", path)

    def _comparison(self, op: str, value: Any) -> Expression:
        return Compare(
            cast(TypingLiteral["eq", "ne", "gt", "ge", "lt", "le"], op),
            FieldRef(self.path),
            Literal(value),
        )

    def eq(self, value: Any) -> Expression:
        """Match typed equality, including structural JSON equality."""
        return self._comparison("eq", value)

    def ne(self, value: Any) -> Expression:
        """Match unequal compatible values; missing fields do not match."""
        return self._comparison("ne", value)

    def gt(self, value: Any) -> Expression:
        """Match values greater than value."""
        return self._comparison("gt", value)

    def ge(self, value: Any) -> Expression:
        """Match values greater than or equal to value."""
        return self._comparison("ge", value)

    def lt(self, value: Any) -> Expression:
        """Match values less than value."""
        return self._comparison("lt", value)

    def le(self, value: Any) -> Expression:
        """Match values less than or equal to value."""
        return self._comparison("le", value)

    def _membership(self, op: str, values: Iterable[Any]) -> Expression:
        if isinstance(values, (str, bytes, Mapping)):
            raise TypeError("membership requires an iterable of scalar candidates")
        operands = tuple(Literal(value) for value in values)
        ref = FieldRef(self.path)
        return (
            In(ref, operands, op == "not_in")
            if op in ("in", "not_in")
            else ArrayContains("any" if op == "contains_any" else "all", ref, operands)
        )

    def in_(self, values: Iterable[Any]) -> Expression:
        """Match a scalar against any candidate."""
        return self._membership("in", values)

    def not_in(self, values: Iterable[Any]) -> Expression:
        """Exclude candidates; missing and incompatible values do not match."""
        return self._membership("not_in", values)

    def contains_any(self, values: Iterable[Any]) -> Expression:
        """Match arrays containing at least one candidate."""
        return self._membership("contains_any", values)

    def contains_all(self, values: Iterable[Any]) -> Expression:
        """Match arrays containing every candidate, without multiplicity checks."""
        return self._membership("contains_all", values)

    def exists(self) -> Expression:
        """Match present fields, including null."""
        return Exists(FieldRef(self.path))

    def missing(self) -> Expression:
        """Match absent fields or unresolved mapping paths."""
        return Not(Exists(FieldRef(self.path)))

    def regex(self, pattern: str) -> Expression:
        """Search string fields with a Python regular expression."""
        if not isinstance(pattern, str):
            raise TypeError("regex requires a string pattern")
        return StringMatch("regex", FieldRef(self.path), pattern)

    def starts_with(self, prefix: str) -> Expression:
        """Match strings starting with prefix."""
        if not isinstance(prefix, str):
            raise TypeError("starts_with requires a string prefix")
        return StringMatch("starts_with", FieldRef(self.path), prefix)


def all_of(*predicates: Expression) -> Expression:
    """Match every child; zero children match all records."""
    return And(predicates)


def any_of(*predicates: Expression) -> Expression:
    """Match any child; zero children match no records."""
    return Or(predicates)


def not_(expression: Expression) -> Expression:
    """Logically negate a predicate, including its missing-field result."""
    return Not(expression)


def logger_prefix(name: str) -> Expression:
    """Match an exact logger name or its stdlib hierarchy descendants."""
    if not isinstance(name, str) or not name:
        raise ValueError("logger_prefix requires a nonempty string name")
    return Or((Field("logger").eq(name), Field("logger").starts_with(name + ".")))
