"""Shared dataclasses for sequence analysis tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Category = Literal[
    "episode_start",
    "episode_end",
    "invocation_start",
    "invocation_end",
    "step",
    "observation",
    "outcome",
    "error",
    "abort",
    "link",
    "background",
    "span_event",
    "other",
    "unassigned",
]
DurationKind = Literal["measured", "derived", "unavailable"]
OutcomeValue = Literal[
    "ok", "ok_with_warning", "error", "aborted", "incomplete", "unknown"
]
Completion = Literal["complete", "incomplete", "unknown"]

FINGERPRINT_VERSION: int = 1

CATEGORIES: frozenset[str] = frozenset(
    {
        "episode_start",
        "episode_end",
        "invocation_start",
        "invocation_end",
        "step",
        "observation",
        "outcome",
        "error",
        "abort",
        "link",
        "background",
        "span_event",
        "other",
        "unassigned",
    }
)
OUTCOME_VALUES: frozenset[str] = frozenset(
    {"ok", "ok_with_warning", "error", "aborted", "incomplete", "unknown"}
)


@dataclass(frozen=True)
class RecordRef:
    id: str
    timestamp: str | None
    source_line: int | None


@dataclass
class Duration:
    ms: float | None
    kind: DurationKind


@dataclass
class SeqEvent:
    ref: RecordRef
    order: int
    ts: datetime | None
    category: Category
    token: str | None
    rule: str | None
    occurrence_n: int
    occurrence_label: str | None
    span_index: int | None
    invocation_index: int | None
    attrs: dict[str, Any]


@dataclass
class Outcome:
    value: OutcomeValue
    rule: str | None
    evidence: list[RecordRef] = field(default_factory=list)


@dataclass
class Span:
    """One node in the episode span tree.

    Nesting is profile-declared: ``parent_index`` points at the open parent
    role named by the profile ``parent`` field when this span opened. Roles
    with different parents are siblings even when their wall times overlap.
    """

    index: int
    role: str
    name: str | None
    parent_index: int | None
    start: RecordRef | None
    end: RecordRef | None
    complete: bool
    outcome: Outcome
    duration: Duration
    children: list[int] = field(default_factory=list)
    events: list[int] = field(default_factory=list)


@dataclass
class Invocation:
    """Compatibility view of a span in the profile's invocation role.

    Prefer :class:`Span` for new code. ``index`` is the position among
    invocation-role spans, not the span-tree index.
    """

    index: int
    name: str | None
    start: RecordRef | None
    end: RecordRef | None
    complete: bool
    outcome: Outcome
    duration: Duration
    events: list[int] = field(default_factory=list)
    span_index: int | None = None


@dataclass
class Links:
    recovery_of: str | None
    triggered_recovery: str | None


@dataclass
class Episode:
    key: str
    key_fields: dict[str, Any]
    variant: str
    events: list[SeqEvent]
    spans: list[Span]
    root: int
    invocations: list[Invocation]
    outcome: Outcome
    completion: Completion
    links: Links
    first: RecordRef
    last: RecordRef
    duration: Duration
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
