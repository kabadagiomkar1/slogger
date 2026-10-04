"""Shared infix spelling of existing IXR predicates and mapping field paths."""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ToolError
from .builders import Field, all_of, any_of, logger_prefix, not_
from .ixr import Expression

_IDENTIFIER = re.compile(r"[^\W\d]\w*", re.UNICODE)


class FilterSyntaxError(ToolError):
    """A located draft error, independent of any editor or rendering library."""

    def __init__(self, text: str, offset: int, message: str, *, code: str = "filter_syntax"):
        line = text.count("\n", 0, offset) + 1
        column = offset - text.rfind("\n", 0, offset)
        super().__init__(
            code,
            f"{message} (line {line}, column {column})",
            offset=offset,
            line=line,
            column=column,
        )
        self.offset = offset
        self.line = line
        self.column = column


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.position = 0
        self.decoder = json.JSONDecoder()

    def space(self) -> None:
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def error(self, message: str) -> FilterSyntaxError:
        return FilterSyntaxError(self.text, self.position, message)

    def take(self, token: str, *, word: bool = False) -> bool:
        self.space()
        end = self.position + len(token)
        if self.text[self.position : end].casefold() != token.casefold():
            return False
        if word and end < len(self.text) and (self.text[end].isalnum() or self.text[end] == "_"):
            return False
        self.position = end
        return True

    def expect(self, token: str) -> None:
        if not self.take(token):
            raise self.error(f"Expected {token!r}; close the expression or supply its operand")

    def value(self) -> Any:
        self.space()
        try:
            value, end = self.decoder.raw_decode(self.text, self.position)
        except ValueError as error:
            raise self.error(
                'Expected a JSON value, e.g. "text", 1, true, null, [] or {}'
            ) from error
        self.position = end
        return value

    def path(self) -> Field:
        segments = []
        while True:
            self.space()
            if self.take("["):
                component = self.value()
                if not isinstance(component, str):
                    raise self.error(
                        'A bracket path component must be a quoted string, e.g. ["a.b"]'
                    )
                self.expect("]")
                segments.append(component)
            else:
                match = _IDENTIFIER.match(self.text, self.position)
                if match is None:
                    raise self.error(
                        'Expected a field path, e.g. request.method or ["literal.key"]'
                    )
                segments.append(match.group())
                self.position = match.end()
            self.space()
            if self.take("."):
                continue
            if self.position < len(self.text) and self.text[self.position] == "[":
                continue
            return Field(*segments)

    def expression(self) -> Expression:
        return self.disjunction()

    def disjunction(self) -> Expression:
        first = self.conjunction()
        children = [first]
        while self.take("OR", word=True):
            children.append(self.conjunction())
        return first if len(children) == 1 else any_of(*children)

    def conjunction(self) -> Expression:
        first = self.negation()
        children = [first]
        while self.take("AND", word=True):
            children.append(self.negation())
        return first if len(children) == 1 else all_of(*children)

    def negation(self) -> Expression:
        if self.take("NOT", word=True):
            return not_(self.negation())
        if self.take("("):
            node = self.expression()
            self.expect(")")
            return node
        self.space()
        start = self.position
        function = _IDENTIFIER.match(self.text, self.position)
        if function is not None:
            self.position = function.end()
            if self.take("("):
                name = function.group().casefold()
                if name == "logger_prefix":
                    value = self.value()
                    self.expect(")")
                    return logger_prefix(value)
                field = self.path()
                if name in ("exists", "missing"):
                    self.expect(")")
                    return field.exists() if name == "exists" else field.missing()
                self.expect(",")
                value = self.value()
                self.expect(")")
                return self.operation(field, name, value)
            self.position = start
        field = self.path()
        for spelling, method in (
            ("==", field.eq),
            ("!=", field.ne),
            (">=", field.ge),
            ("<=", field.le),
            (">", field.gt),
            ("<", field.lt),
        ):
            if self.take(spelling):
                return method(self.value())
        if self.take("NOT", word=True):
            if not self.take("IN", word=True):
                raise self.error("Expected IN after a field followed by NOT")
            return self.operation(field, "not_in", self.value())
        for spelling in (
            "in",
            "contains_any",
            "contains_all",
            "contains",
            "matches",
            "regex",
            "starts_with",
            "exists",
            "missing",
        ):
            if self.take(spelling, word=True):
                if spelling in ("exists", "missing"):
                    return field.exists() if spelling == "exists" else field.missing()
                return self.operation(field, spelling, self.value())
        raise self.error("Expected an operator, e.g. ==, IN, contains, exists or missing")

    def operation(self, field: Field, name: str, value: Any) -> Expression:
        if name in ("in", "not_in", "contains_any", "contains_all"):
            if not isinstance(value, list):
                raise TypeError(f"{name} requires a JSON array of scalar candidates")
            method = field.in_ if name == "in" else getattr(field, name)
            return method(value)
        if name in ("contains", "matches", "regex", "starts_with"):
            if not isinstance(value, str):
                raise TypeError(f"{name} requires a JSON string")
            if name == "starts_with":
                return field.starts_with(value)
            return field.regex(re.escape(value) if name == "contains" else value)
        raise self.error(
            f"Unknown function {name!r}; use exists, missing, starts_with or logger_prefix"
        )


def parse_filter(text: str) -> Expression:
    """Translate a complete infix draft to IXR. Empty text admits every record."""
    parser = _Parser(text)
    parser.space()
    if parser.position == len(text):
        return all_of()
    try:
        expression = parser.expression()
        parser.space()
        if parser.position != len(text):
            raise parser.error("Unexpected input; connect predicates with AND or OR")
        return expression
    except (TypeError, ValueError) as error:
        raise FilterSyntaxError(text, parser.position, str(error), code="filter_type") from error


def parse_field_path(text: str) -> tuple[str, ...]:
    """Parse one unambiguous mapping path, with no array-index traversal."""
    parser = _Parser(text)
    try:
        field = parser.path()
        parser.space()
        if parser.position != len(text):
            raise parser.error("Unexpected input after field path")
        return field.path
    except (TypeError, ValueError) as error:
        raise FilterSyntaxError(text, parser.position, str(error), code="filter_type") from error


def format_field_path(path: tuple[str, ...]) -> str:
    """Spell exact keys with JSON brackets and ordinary nested keys with dots."""
    Field(*path)
    parts = []
    for segment in path:
        if _IDENTIFIER.fullmatch(segment) and segment.casefold() not in {"not", "and", "or"}:
            parts.append(("." if parts else "") + segment)
        else:
            parts.append("[" + json.dumps(segment, ensure_ascii=False) + "]")
    return "".join(parts)
