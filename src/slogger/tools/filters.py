"""Filter predicates for structured log records."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from slogger.tools.reader import parse_timestamp

_OPS = ("!=", ">=", "<=", "!~", "=", ">", "<", "~")
_OP_CHARS = set("=!~<>")
_RELATIVE = re.compile(r"^(\d+)([smhd])$")


@dataclass(frozen=True)
class Where:
    """One compact ``KEYOPVALUE`` clause (``user=ada``, ``amount>=99``, …)."""

    key: str
    op: Literal["=", "!=", ">", "<", ">=", "<=", "~", "!~"]
    value: str


def parse_where(token: str) -> Where:
    """Parse a compact ``KEYOPVALUE`` token. Raises :class:`ValueError` on bad input."""
    if not token or any(ch.isspace() for ch in token):
        raise ValueError(f"invalid --where token (use compact KEYOPVALUE): {token!r}")
    for op in _OPS:
        index = token.find(op)
        if index == -1:
            continue
        key = token[:index]
        value = token[index + len(op) :]
        if not key or any(ch in _OP_CHARS for ch in key):
            raise ValueError(f"invalid --where token: {token!r}")
        return Where(key=key, op=op, value=value)  # type: ignore[arg-type]
    raise ValueError(f"invalid --where token (no operator): {token!r}")


def level_number(name_or_int: str | int) -> int:
    """Resolve a level name or integer. Raises :class:`ValueError` if unknown."""
    if isinstance(name_or_int, int):
        return name_or_int
    text = name_or_int.strip()
    if text.startswith("="):
        text = text[1:]
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    mapping = _level_names()
    try:
        return mapping[text.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown log level: {name_or_int!r}") from exc


def _level_names() -> dict[str, int]:
    if hasattr(logging, "getLevelNamesMapping"):
        return logging.getLevelNamesMapping()
    return {name: value for name, value in logging._nameToLevel.items() if isinstance(value, int)}


def parse_relative_or_iso(text: str, *, now: datetime | None = None) -> datetime:
    """Parse an ISO-8601 timestamp or a relative ``Ns``/``Nm``/``Nh``/``Nd`` offset."""
    match = _RELATIVE.fullmatch(text.strip())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        base = now if now is not None else datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        delta = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return base - delta
    moment = parse_timestamp(text)
    if moment is None:
        raise ValueError(f"invalid time: {text!r}")
    return moment


def _json_compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _as_number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _match_where(record: Mapping[str, Any], clause: Where) -> bool:
    if clause.key not in record:
        return False
    value = record[clause.key]
    op = clause.op
    raw = clause.value

    if op in ("~", "!~"):
        target = (
            _json_compact(value)
            if isinstance(value, (dict, list))
            else "null"
            if value is None
            else "true"
            if value is True
            else "false"
            if value is False
            else str(value)
        )
        found = re.search(raw, target) is not None
        return found if op == "~" else not found

    if isinstance(value, bool):
        if op in ("<", ">", "<=", ">="):
            return False
        expected = raw.lower()
        if expected not in {"true", "false"}:
            return False
        actual = "true" if value else "false"
        return (actual == expected) if op == "=" else (actual != expected)

    if value is None:
        if op in ("<", ">", "<=", ">="):
            return False
        return (raw == "null") if op == "=" else (raw != "null")

    if isinstance(value, (dict, list)):
        if op in ("<", ">", "<=", ">="):
            return False
        compact = _json_compact(value)
        return (compact == raw) if op == "=" else (compact != raw)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = _as_number(raw)
        if number is None:
            return False
        if op == "=":
            return float(value) == number
        if op == "!=":
            return float(value) != number
        if op == ">":
            return float(value) > number
        if op == "<":
            return float(value) < number
        if op == ">=":
            return float(value) >= number
        if op == "<=":
            return float(value) <= number
        return False

    # Strings and everything else: compare as strings.
    text = str(value)
    if op == "=":
        return text == raw
    if op == "!=":
        return text != raw
    if op == ">":
        return text > raw
    if op == "<":
        return text < raw
    if op == ">=":
        return text >= raw
    if op == "<=":
        return text <= raw
    return False


def _iso_z(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    text = moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


@dataclass
class Filters:
    """Predicate shared by the CLI and :mod:`slogger.tools` readers.

    Multiple clauses are ANDed. ``--where`` / :class:`Where` operators are
    ``= != > < >= <= ~ !~``. A missing key never matches a comparison (use
    ``missing``). ``logger`` matches an exact name or a stdlib-style prefix.
    """

    level_min: int | None = None
    level_exact: int | None = None
    logger: str | None = None
    where: tuple[Where, ...] = ()
    has: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    grep: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    span: str | None = None
    trace: str | None = None
    exclude_events: bool = False
    _grep_re: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.grep is None:
            return
        try:
            self._grep_re = re.compile(self.grep)
        except re.error as exc:
            raise ValueError(f"invalid --grep pattern: {self.grep!r}") from exc

    def explain(self) -> dict[str, Any]:
        """Return a normalised, JSON-serialisable description of this predicate.

        Relative ``since`` / ``until`` values must already be resolved to absolute
        datetimes (as :func:`slogger.cli.filters_from_args` does).
        """
        return {
            "schema_version": 1,
            "filters": {
                "level_min": self.level_min,
                "level_exact": self.level_exact,
                "logger": self.logger,
                "where": [
                    {"key": clause.key, "op": clause.op, "value": clause.value}
                    for clause in self.where
                ],
                "has": list(self.has),
                "missing": list(self.missing),
                "grep": self.grep,
                "since": _iso_z(self.since),
                "until": _iso_z(self.until),
                "span": self.span,
                "trace": self.trace,
                "exclude_events": self.exclude_events,
            },
            "notes": [
                "multiple --where clauses are ANDed",
                "missing keys never match comparisons",
            ],
        }

    def matches(self, record: Mapping[str, Any]) -> bool:
        if self.exclude_events and record.get("event") in ("span.start", "span.end"):
            return False

        if self.level_exact is not None or self.level_min is not None:
            level_name = record.get("level")
            if not isinstance(level_name, str):
                return False
            try:
                level = level_number(level_name)
            except ValueError:
                return False
            if self.level_exact is not None and level != self.level_exact:
                return False
            if self.level_min is not None and level < self.level_min:
                return False

        if self.logger is not None:
            name = record.get("logger")
            if not isinstance(name, str):
                return False
            if name != self.logger and not name.startswith(self.logger + "."):
                return False

        for key in self.has:
            if key not in record:
                return False
        for key in self.missing:
            if key in record:
                return False

        for clause in self.where:
            if not _match_where(record, clause):
                return False

        if self.grep is not None:
            message = record.get("message")
            if not isinstance(message, str):
                return False
            assert self._grep_re is not None
            if self._grep_re.search(message) is None:
                return False

        if self.since is not None or self.until is not None:
            moment = parse_timestamp(record.get("timestamp"))
            if moment is None:
                return False
            if self.since is not None and moment < self.since:
                return False
            if self.until is not None and moment > self.until:
                return False

        if self.span is not None and record.get("span") != self.span:
            return False
        if self.trace is not None and record.get("trace_id") != self.trace:
            return False

        return True
