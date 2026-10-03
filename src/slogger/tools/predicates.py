"""Composable typed predicates for reading structured logs."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from typing import Literal as TypingLiteral

from .backends.python.expressions import compile_expression
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
    _describe,
    _equal,
    _numeric,
    _Object,
    _snapshot,
)

__all__ = ["Field", "Predicate", "all_of", "any_of", "logger_prefix", "not_"]
Matcher = Callable[[Mapping[str, Any]], bool]


class Predicate(ABC):
    """Expression built by Field methods and composition functions.

    Use matches() for individual records or compile() for a reusable callable.
    Logical nodes are available through to_ixr() and slogger.tools.ixr.
    """

    def __bool__(self) -> bool:
        raise TypeError("use all_of(), any_of(), or not_() to compose predicates")

    @abstractmethod
    def compile(self) -> Matcher:
        """Lazily compile and return a reusable cached record matcher."""
        ...

    def to_ixr(self) -> Expression:
        """Return logical IXR, or reject a custom predicate without representation."""
        raise TypeError(f"{type(self).__name__} does not support IXR extraction")

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
    _matcher: Matcher | None = field(default=None, init=False, repr=False, compare=False)
    _logical: Expression | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._op == "regex":
            try:
                re.compile(self._value)
            except re.error as exc:
                raise ValueError(f"invalid predicate regex: {self._value!r}") from exc
        if all(
            isinstance(child, _Expression) and child._logical is not None
            for child in self._children
        ):
            object.__setattr__(self, "_logical", self._build_ixr())

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
        if self._matcher is None:
            if self._logical is not None:
                matcher = compile_expression(self._logical)
            elif self._op in ("all", "any", "not"):
                children = tuple(child.compile() for child in self._children)
                matcher = (
                    (lambda r: all(c(r) for c in children))
                    if self._op == "all"
                    else (lambda r: any(c(r) for c in children))
                    if self._op == "any"
                    else (lambda r: not children[0](r))
                )
            else:
                matcher = compile_expression(self.to_ixr())
            object.__setattr__(self, "_matcher", matcher)
        assert self._matcher is not None
        return self._matcher

    def explain(self) -> dict[str, Any]:
        """Return a JSON-compatible inspection description (not an input syntax)."""
        if self._op in ("all", "any", "not"):
            return {"op": self._op, "children": [child.explain() for child in self._children]}
        result: dict[str, Any] = {"op": self._op, "path": list(self._path)}
        if self._op not in ("exists", "missing"):
            result["value"] = _describe(self._value)
        return result

    def to_ixr(self) -> Expression:
        if self._logical is None:
            object.__setattr__(self, "_logical", self._build_ixr())
        assert self._logical is not None
        return self._logical

    def _build_ixr(self) -> Expression:
        op = self._op
        if op in ("all", "any"):
            children = tuple(c.to_ixr() for c in self._children)
            return And(children) if op == "all" else Or(children)
        if op == "not":
            return Not(self._children[0].to_ixr())
        ref = FieldRef(self._path)
        if op in ("exists", "missing"):
            return Exists(ref) if op == "exists" else Not(Exists(ref))
        if op in ("in", "not_in", "contains_any", "contains_all"):
            candidates = tuple(Literal(_describe(v)) for v in self._value)
            return (
                In(ref, candidates, op == "not_in")
                if op in ("in", "not_in")
                else ArrayContains("any" if op == "contains_any" else "all", ref, candidates)
            )
        if op == "logger_prefix":
            return Or(
                (
                    Compare("eq", ref, Literal(self._value)),
                    StringMatch("starts_with", ref, self._value + "."),
                )
            )
        if op in ("regex", "starts_with"):
            return StringMatch(op, ref, self._value)
        return Compare(
            cast(TypingLiteral["eq", "ne", "gt", "ge", "lt", "le"], op),
            ref,
            Literal(_describe(self._value)),
        )


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
