"""THROWAWAY infix-to-IXR parser and disk-backed result experiments."""

from __future__ import annotations

import json
import re

from native_store import check_cancel, connect

from slogger.tools import Field, all_of, any_of, logger_prefix, not_, scan

TOKEN = re.compile(
    r'\s*("(?:\\.|[^"\\])*"|>=|<=|!=|==|[=><().\[\]{},:]|'
    r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][\w-]*)"
)


class Parser:
    def __init__(self, text):
        self.tokens = []
        offset = 0
        while offset < len(text):
            match = TOKEN.match(text, offset)
            if not match:
                if not text[offset:].strip():
                    break
                raise ValueError(f"Unexpected character near {text[offset : offset + 20]!r}")
            self.tokens.append(match[1])
            offset = match.end()
        self.i = 0

    def take(self, expected=None):
        token = self.tokens[self.i] if self.i < len(self.tokens) else ""
        if not token or expected is not None and token != expected:
            raise ValueError(f"Expected {expected or 'expression'}, got {token or 'end of input'}")
        self.i += 1
        return token

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else ""

    def field(self):
        parts = []
        while True:
            if self.peek() == "[":
                self.take("[")
                key = json.loads(self.take())
                if not isinstance(key, str):
                    raise ValueError("Bracket field components must be quoted strings")
                self.take("]")
            else:
                key = self.take()
                if not re.fullmatch(r"[A-Za-z_][\w-]*", key):
                    raise ValueError("Expected field name")
            parts.append(key)
            if self.peek() == ".":
                self.take(".")
            elif self.peek() != "[":
                break
        return Field(*parts)

    def value(self):
        start = self.i
        opening = self.peek()
        if opening in ("[", "{"):
            depth = 0
            while True:
                token = self.take()
                depth += token in ("[", "{")
                depth -= token in ("]", "}")
                if depth == 0:
                    break
            return json.loads(" ".join(self.tokens[start : self.i]))
        return json.loads(self.take())

    def atom(self):
        if self.peek() == "not":
            self.take()
            return not_(self.atom())
        if self.peek() == "(":
            self.take()
            expression = self.or_expr()
            self.take(")")
            return expression
        if self.peek() in ("exists", "missing", "logger_prefix"):
            function = self.take()
            self.take("(")
            if function == "logger_prefix":
                expression = logger_prefix(self.value())
            else:
                field = self.field()
                expression = field.exists() if function == "exists" else field.missing()
            self.take(")")
            return expression
        field = self.field()
        operator = self.take()
        if operator == "not":
            self.take("in")
            operator = "not in"
        value = self.value()
        methods = {
            "=": "eq",
            "==": "eq",
            "!=": "ne",
            ">": "gt",
            ">=": "ge",
            "<": "lt",
            "<=": "le",
            "in": "in_",
            "not in": "not_in",
            "contains_any": "contains_any",
            "contains_all": "contains_all",
        }
        if operator in methods:
            return getattr(field, methods[operator])(value)
        if operator in ("contains", "matches"):
            if not isinstance(value, str):
                raise ValueError(f"{operator} requires a string")
            return field.regex(re.escape(value) if operator == "contains" else value)
        raise ValueError(f"Unknown operator: {operator}")

    def and_expr(self):
        children = [self.atom()]
        while self.peek() == "and":
            self.take()
            children.append(self.atom())
        return all_of(*children)

    def or_expr(self):
        children = [self.and_expr()]
        while self.peek() == "or":
            self.take()
            children.append(self.and_expr())
        return any_of(*children)

    def parse(self):
        expression = self.or_expr()
        if self.peek():
            raise ValueError(f"Unexpected token: {self.peek()}")
        return expression


def filter_store(store, query, cancel, progress):
    expression = Parser(query).parse() if query.strip() else None
    name = store.new_table("filter_")
    matched = scanned = 0
    try:
        with connect(store.db_path) as db:
            for batch in store.batches(cancel):
                if expression is None:
                    selected = range(len(batch))
                else:
                    result = scan([item[2] for item in batch]).filter(expression).execute()
                    # IXR collection origins index the supplied batch. Map back to
                    # capture IDs instead of exposing regenerated memory origins.
                    selected = [origin.position for origin in result.origins]
                rows = []
                for index in selected:
                    matched += 1
                    rows.append((matched, batch[index][0]))
                db.executemany(f'INSERT INTO "{name}" VALUES (?,?)', rows)
                db.commit()
                store.check_budget()
                scanned += len(batch)
                progress("Filtering", scanned, store.count, matched)
            db.execute(f'CREATE INDEX "{name}_rid" ON "{name}" (rid)')
        store.check_budget()
        check_cancel(cancel)
        return name, matched
    except BaseException:
        store.drop(name)
        raise


CORE_FIELDS = {"timestamp", "level", "logger", "message"}
META_FIELDS = {
    "filename",
    "lineno",
    "line",
    "pathname",
    "module",
    "funcName",
    "function",
    "process",
    "processName",
    "thread",
    "threadName",
    "exception",
    "stack_info",
    "exc_info",
    "traceback",
    "name",
    "created",
    "msecs",
    "relativeCreated",
}


def console_record(record):
    return {k: v for k, v in record.items() if k not in META_FIELDS}


def search_store(store, text, full, case, exact, view, cancel, progress):
    flags = 0 if case else re.IGNORECASE
    pattern = re.compile(
        (r"(?<!\w)" if exact else "") + re.escape(text) + (r"(?!\w)" if exact else ""), flags
    )
    name = store.new_table("search_")
    scanned = matches = 0
    try:
        with connect(store.db_path) as db:
            for batch in store.batches(cancel, view):
                rows = []
                for rid, seq, record in batch:
                    fields = record if full else console_record(record)
                    # Names and untruncated values are searched, not screen glyphs.
                    if pattern.search(json.dumps(fields, ensure_ascii=False)):
                        rows.append((seq, rid))
                        matches += 1
                db.executemany(f'INSERT INTO "{name}" VALUES (?,?)', rows)
                db.commit()
                store.check_budget()
                scanned += len(batch)
                progress("Searching", scanned, store.view_count, matches)
        check_cancel(cancel)
        return name, matches
    except BaseException:
        store.drop(name)
        raise


def completions(value, samples):
    """Small contextual suggestions, sampled on capture in this prototype."""
    # Capture keys use the same path spelling that Parser accepts.
    if not value.strip() or re.search(r"(?:\band|\bor|\bnot|\()\s*$", value):
        return len(value), [*sorted(samples)[:6], "exists(", "missing(", "logger_prefix("][:8]
    try:
        parser = Parser(value)
    except ValueError:
        # Incomplete quoted literals are normal while typing.
        parser = None
    if parser and parser.tokens:
        tokens = parser.tokens
        operators = [
            "= ",
            "!= ",
            ">= ",
            "<= ",
            "in ",
            "not in ",
            "contains ",
            "matches ",
            "contains_any ",
            "contains_all ",
        ]
        last = tokens[-1]
        if value.endswith(" "):
            if last in (
                "=",
                "!=",
                ">",
                ">=",
                "<",
                "<=",
                "in",
                "contains",
                "matches",
                "contains_any",
                "contains_all",
            ):
                field_text = re.split(r"\s+(?:and|or)\s+", value)[-1]
                field_text = re.split(
                    r"\s*(?:[=!<>]+|\bin\b|\bcontains\b|\bmatches\b)", field_text
                )[0].strip()
                values = samples.get(field_text, {})
                suggestions = sorted(values, key=lambda k: -values[k])[:8]
                return len(value), suggestions or ['""', "0", "true", "null", "[]"]
            try:
                Parser(value).parse()
                return len(value), ["and ", "or "]
            except (ValueError, TypeError):
                if last not in ("and", "or", "not"):
                    return len(value), operators[:8]
    match = re.search(r"[^\s()=<>!]+$", value)
    start = match.start() if match else len(value)
    prefix = value[start:]
    candidates = [
        *sorted(samples),
        "exists(",
        "missing(",
        "logger_prefix(",
        "and ",
        "or ",
        "not ",
        "in ",
        "not in ",
        "contains ",
        "matches ",
        "contains_any ",
        "contains_all ",
    ]
    # Value-prefix suggestions include quoted typed literals, not plain strings.
    candidates += list(dict.fromkeys(v for values in samples.values() for v in values))
    return start, [s for s in candidates if s.startswith(prefix) and s != prefix][:8]
