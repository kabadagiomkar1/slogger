"""Shared infix spelling of existing IXR predicates and mapping field paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..errors import ToolError
from .builders import Field, all_of, any_of, logger_prefix, not_
from .ixr import Expression

_IDENTIFIER = re.compile(r"[^\W\d]\w*", re.UNICODE)
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d*)?(?:[eE][+-]?\d*)?")


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

    def hint(self, kind: str, *, field: Field | None = None, value_kind: str | None = None) -> None:
        """Expose grammar position to completion without changing IXR parsing."""

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
        self.hint(token)
        if not self.take(token):
            raise self.error(f"Expected {token!r}; close the expression or supply its operand")

    def value(self, kind: str = "json", field: Field | None = None) -> Any:
        self.hint("value", field=field, value_kind=kind)
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
            self.hint("field", field=Field(*segments) if segments else None)
            self.space()
            if self.take("["):
                component = self.value("path_component")
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
        self.hint("connector")
        while self.take("AND", word=True):
            children.append(self.negation())
        return first if len(children) == 1 else all_of(*children)

    def negation(self) -> Expression:
        self.hint("expression")
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
                    value = self.value("string", Field("logger"))
                    self.expect(")")
                    return logger_prefix(value)
                field = self.path()
                if name in ("exists", "missing"):
                    self.expect(")")
                    return field.exists() if name == "exists" else field.missing()
                self.expect(",")
                value = self.value(_value_kind(name), field)
                self.expect(")")
                return self.operation(field, name, value)
            self.position = start
        field = self.path()
        self.hint("operator", field=field)
        for spelling, method in (
            ("==", field.eq),
            ("!=", field.ne),
            (">=", field.ge),
            ("<=", field.le),
            (">", field.gt),
            ("<", field.lt),
        ):
            if self.take(spelling):
                return method(self.value("json" if spelling in ("==", "!=") else "ordered", field))
        if self.take("NOT", word=True):
            self.hint("IN", field=field)
            if not self.take("IN", word=True):
                raise self.error("Expected IN after a field followed by NOT")
            return self.operation(field, "not_in", self.value("array", field))
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
                return self.operation(field, spelling, self.value(_value_kind(spelling), field))
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


@dataclass(frozen=True)
class FilterChoice:
    """One syntax insertion, with a cursor offset for editable JSON templates."""

    label: str
    insertion: str
    description: str = ""
    cursor_offset: int | None = None


@dataclass(frozen=True)
class FilterCompletion:
    """Immutable grammar response scoped to an exact draft and cursor."""

    text: str
    cursor: int
    generation: int
    start: int
    end: int
    prefix: str
    kind: str
    field_path: tuple[str, ...] | None
    value_kind: str | None
    choices: tuple[FilterChoice, ...]
    guidance: str

    def apply(
        self, choice: FilterChoice, *, text: str, cursor: int, generation: int
    ) -> tuple[str, int] | None:
        """Reject stale responses; preserve all text outside the replacement span."""
        if (text, cursor, generation) != (self.text, self.cursor, self.generation):
            return None
        if choice not in self.choices:
            return None
        suffix = text[self.end :]
        insertion = choice.insertion
        if insertion in (")", "]", ",") and suffix.startswith(insertion):
            suffix = suffix[1:]
        if choice.cursor_offset is None and (not suffix or not suffix[0].isspace()):
            insertion += " "
        result = text[: self.start] + insertion + suffix
        offset = len(insertion) if choice.cursor_offset is None else choice.cursor_offset
        return result, self.start + offset


def _value_kind(operator: str) -> str:
    return "array" if operator in ("in", "not_in", "contains_any", "contains_all") else "string"


class _CompletionPoint(Exception):
    def __init__(self, kind: str, field: Field | None, value_kind: str | None):
        self.kind = kind
        self.field = field
        self.value_kind = value_kind


class _CompletionParser(_Parser):
    def __init__(self, text: str):
        super().__init__(text)
        self.open_parentheses = 0

    def take(self, token: str, *, word: bool = False) -> bool:
        taken = super().take(token, word=word)
        if taken and token == "(":
            self.open_parentheses += 1
        elif taken and token == ")":
            self.open_parentheses -= 1
        return taken

    def hint(self, kind: str, *, field: Field | None = None, value_kind: str | None = None) -> None:
        self.space()
        if self.position == len(self.text):
            raise _CompletionPoint(kind, field, value_kind)

    def value(self, kind: str = "json", field: Field | None = None) -> Any:
        self.space()
        start = self.position
        try:
            return super().value(kind, field)
        except FilterSyntaxError:
            fragment = self.text[start:]
            if kind not in ("array", "json") or not fragment.startswith("["):
                raise
            position = 1
            while True:
                while position < len(fragment) and fragment[position].isspace():
                    position += 1
                if position == len(fragment):
                    raise _CompletionPoint(
                        "value", field, "scalar" if kind == "array" else "json"
                    ) from None
                # Use JSON's own scalar/structural decoder. This is guidance for
                # an unfinished operand, never another predicate evaluator.
                _, position = self.decoder.raw_decode(fragment, position)
                while position < len(fragment) and fragment[position].isspace():
                    position += 1
                if position == len(fragment):
                    raise _CompletionPoint("array_separator", field, kind) from None
                if fragment[position] != ",":
                    raise self.error(
                        "Expected ',' between JSON array values, or ']' to close it"
                    ) from None
                position += 1


_OPERATORS = (
    "==",
    "!=",
    ">=",
    "<=",
    ">",
    "<",
    "IN",
    "NOT IN",
    "contains",
    "contains_any",
    "contains_all",
    "matches",
    "regex",
    "starts_with",
    "exists",
    "missing",
)
_FUNCTIONS = (
    "exists",
    "missing",
    "in",
    "not_in",
    "contains_any",
    "contains_all",
    "contains",
    "matches",
    "regex",
    "starts_with",
    "logger_prefix",
)


def _active_span(text: str, cursor: int) -> tuple[int, int]:
    # JSON strings are a single edit span, including escaped quotes. Completed
    # literals to the left of the cursor remain part of the parsed expression.
    quote_start: int | None = None
    escaped = False
    for position, char in enumerate(text[:cursor]):
        if quote_start is None:
            if char == '"':
                quote_start = position
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quote_start = None
    if quote_start is not None:
        end = cursor
        while end < len(text):
            char = text[end]
            end += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                break
        return quote_start, end
    number = re.search(r"(?<![\w.])(" + _NUMBER.pattern + r")$", text[:cursor])
    if number is not None:
        start = number.start(1)
        whole = _NUMBER.match(text, start)
        return start, whole.end() if whole is not None else cursor
    start, end = cursor, cursor
    if start and text[start - 1] in "=!<>":
        while start and text[start - 1] in "=!<>":
            start -= 1
        while end < len(text) and text[end] in "=!<>":
            end += 1
    else:
        while start and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
    return start, end


def complete_filter(
    text: str, cursor: int | None = None, *, generation: int = 0
) -> FilterCompletion:
    """Complete syntax with the same grammar used by parse_filter.

    Choices are independent of captured data. Exact draft/cursor/generation and
    replacement bounds let asynchronous field discovery safely extend them.
    """
    if cursor is None:
        cursor = len(text)
    if not 0 <= cursor <= len(text):
        raise ValueError("completion cursor must be inside the draft")
    start, end = _active_span(text, cursor)
    prefix = text[start:cursor]
    parser = _CompletionParser(text[:start])
    kind, field, value_kind, guidance = "none", None, None, ""
    try:
        parser.expression()
        parser.space()
        if parser.position != len(parser.text):
            raise parser.error("Unexpected input; connect predicates with AND or OR")
    except _CompletionPoint as point:
        kind, field, value_kind = point.kind, point.field, point.value_kind
    except (FilterSyntaxError, TypeError, ValueError) as error:
        guidance = str(error)
    choices: list[FilterChoice] = []
    if kind == "operator":
        choices = [FilterChoice(word, word) for word in _OPERATORS]
        guidance = "Choose a comparison, membership, string, or presence operator"
    elif kind == "expression":
        choices = [FilterChoice("(", "(", cursor_offset=1), FilterChoice("NOT", "NOT")]
        choices.extend(
            FilterChoice(name + "(", name + "(", cursor_offset=len(name) + 1) for name in _FUNCTIONS
        )
        guidance = "Enter a field path, NOT, a group, or a function"
    elif kind == "field":
        guidance = 'Enter a field path; dots nest and ["literal.key"] selects an exact key'
    elif kind == "connector":
        choices = [FilterChoice("AND", "AND"), FilterChoice("OR", "OR")]
        if parser.open_parentheses:
            choices.append(FilterChoice(")", ")", cursor_offset=1))
        guidance = "Enter applies; AND/OR adds a predicate"
    elif kind == "array_separator":
        choices = [FilterChoice(",", ",", cursor_offset=1), FilterChoice("]", "]", cursor_offset=1)]
        guidance = "Add another JSON array value with a comma, or close with ]"
    elif kind == "IN":
        choices = [FilterChoice("IN", "IN")]
        guidance = "Complete NOT IN, then enter a JSON array of scalar candidates"
    elif kind in (",", ")", "]"):
        choices = [FilterChoice(kind, kind, cursor_offset=1)]
        guidance = "Separate function arguments" if kind == "," else "Close the expression"
    elif kind == "value":
        if value_kind in ("string", "path_component"):
            choices = [FilterChoice('""', '""', cursor_offset=1)]
            guidance = "Enter a JSON string; quote text and escape embedded quotes/backslashes"
        elif value_kind == "array":
            choices = [FilterChoice("[]", "[]", cursor_offset=1)]
            guidance = "Enter a JSON array of scalar candidates"
        else:
            choices = [FilterChoice('""', '""', cursor_offset=1), FilterChoice("0", "0")]
            guidance = "Ordering requires a JSON number or string"
            if value_kind in ("json", "scalar"):
                choices.extend(FilterChoice(word, word) for word in ("true", "false", "null"))
                if value_kind == "json":
                    choices.extend(
                        FilterChoice(word, word, cursor_offset=1) for word in ("[]", "{}")
                    )
                guidance = (
                    "Enter a typed JSON value" if value_kind == "json" else "Enter a JSON scalar"
                )
                guidance += "; quoted strings differ from numbers/true/null"
    choices = [
        choice for choice in choices if choice.label.casefold().startswith(prefix.casefold())
    ]
    if kind == "value" and prefix.startswith('"') and len(prefix) > 1:
        guidance = "Finish the JSON string with a closing quote; escape embedded quotes/backslashes"
    return FilterCompletion(
        text,
        cursor,
        generation,
        start,
        end,
        prefix,
        kind,
        field.path if field else None,
        value_kind,
        tuple(choices),
        guidance,
    )
