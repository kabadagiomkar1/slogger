"""Extract episodes from structured log sources using a sequence profile."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Reader, parse_timestamp
from slogger.tools.seq.model import (
    Completion,
    Duration,
    Episode,
    Invocation,
    Links,
    Outcome,
    OutcomeValue,
    RecordRef,
    SeqEvent,
    Span,
)
from slogger.tools.seq.profile import (
    CompleteWhenEnd,
    CompleteWhenInvocations,
    EpisodeOutcomeAggregate,
    EpisodeOutcomeField,
    Profile,
    SpanRoleSpec,
    classify,
    format_token_value,
    role_by_name,
)


@dataclass
class EpisodesResult:
    episodes: list[Episode]
    total: int
    returned: int
    truncated: bool
    episodes_capped: bool
    unassigned_records: int
    skipped_lines: int
    next_cursor: str | None
    warnings: list[str] = field(default_factory=list)
    order_basis: Literal["reading"] = "reading"


def episode_key_for(
    profile: Profile, record: Mapping[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """Return ``(rendered_key, key_fields)`` or ``None`` when unassigned."""
    fields = _key_fields(profile.episode_key, record)
    if fields is None:
        for fallback in profile.fallback_keys:
            fields = _key_fields(fallback, record)
            if fields is not None:
                break
    if fields is None:
        return None
    return _render_key(fields), fields


def _key_fields(
    keys: Sequence[str], record: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not keys:
        return None
    if any(key not in record for key in keys):
        return None
    return {key: record[key] for key in keys}


def _render_key(fields: Mapping[str, Any]) -> str:
    if len(fields) == 1:
        return format_token_value(next(iter(fields.values())))
    return "&".join(f"{key}={format_token_value(value)}" for key, value in fields.items())


def _record_ref(record: Mapping[str, Any]) -> RecordRef:
    source_line = record.get("source_line")
    return RecordRef(
        id=str(record.get("_id", "")),
        timestamp=record.get("timestamp") if isinstance(record.get("timestamp"), str) else None,
        source_line=source_line if isinstance(source_line, int) else None,
    )


def _keep_attrs(profile: Profile, record: Mapping[str, Any]) -> dict[str, Any]:
    attrs = {key: record[key] for key in profile.keep_attrs if key in record}
    # Always retain span identity fields when present (path --granularity span).
    for key in ("event", "span", "span_role", "span_enrichment"):
        if key in record and key not in attrs:
            attrs[key] = record[key]
    return attrs


def _ms_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() * 1000.0


def _occurrence_label(profile: Profile, record: Mapping[str, Any]) -> str | None:
    for key in profile.occurrence_key:
        if key in record:
            return format_token_value(record[key])
    return None


def _match_when(when: Sequence[Any], record: Mapping[str, Any]) -> bool:
    if not when:
        return False
    return Filters(where=tuple(when)).matches(record)


@dataclass
class _SpanState:
    index: int
    role: str
    name: str | None
    parent_index: int | None
    start: RecordRef | None = None
    start_order: int | None = None
    end: RecordRef | None = None
    end_order: int | None = None
    complete: bool = False
    event_indexes: list[int] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    outcome_records: list[tuple[int, dict[str, Any], RecordRef]] = field(
        default_factory=list
    )


def _nearest_span(
    spans: list[_SpanState],
    *,
    role: str | None,
    name_field: str | None,
    order: int,
    name_field_value: object | None,
) -> int | None:
    candidates = [s for s in spans if role is None or s.role == role]
    if name_field is not None and name_field_value is not None:
        named = [s for s in candidates if s.name == name_field_value]
        if named:
            candidates = named
    if not candidates:
        return None
    best: _SpanState | None = None
    best_dist: float | None = None
    for span in candidates:
        start = span.start_order if span.start_order is not None else span.index
        end = span.end_order if span.end_order is not None else (
            span.start_order if span.start_order is not None else span.index
        )
        if start <= order <= end:
            dist = 0.0
        elif order < start:
            dist = float(start - order)
        else:
            dist = float(order - end)
        if best is None or best_dist is None or dist < best_dist:
            best = span
            best_dist = dist
    return best.index if best is not None else candidates[-1].index


def _span_outcome(
    profile: Profile,
    state: _SpanState,
    events: list[SeqEvent],
    records: list[dict[str, Any]],
) -> Outcome:
    candidates: list[tuple[dict[str, Any], RecordRef]] = [
        (rec, ref) for _, rec, ref in state.outcome_records
    ]
    for event_index in state.event_indexes:
        record = records[event_index]
        ref = events[event_index].ref
        candidates.append((record, ref))

    seen_refs: set[str] = set()
    unique: list[tuple[dict[str, Any], RecordRef]] = []
    for record, ref in candidates:
        if ref.id in seen_refs:
            continue
        seen_refs.add(ref.id)
        unique.append((record, ref))

    for rule in profile.outcome_invocation:
        for record, ref in unique:
            if _match_when(rule.when, record):
                return Outcome(value=rule.value, rule=rule.id, evidence=[ref])
    return Outcome(value="unknown", rule="no_evidence", evidence=[])


def _aggregate_episode_outcome(
    profile: Profile,
    invocations: list[Invocation],
    completion: Completion,
) -> Outcome:
    spec = profile.outcome_episode
    if isinstance(spec, EpisodeOutcomeField):
        return Outcome(value="unknown", rule="no_evidence", evidence=[])

    require = set(spec.require_outcome_from) if isinstance(spec, EpisodeOutcomeAggregate) else set()
    values = [inv.outcome.value for inv in invocations]

    def _evidence_for(value: OutcomeValue) -> list[RecordRef]:
        return [
            e
            for inv in invocations
            if inv.outcome.value == value
            for e in inv.outcome.evidence
        ]

    if any(v == "aborted" for v in values):
        return Outcome(value="aborted", rule="aggregate", evidence=_evidence_for("aborted"))
    if any(v == "error" for v in values):
        return Outcome(value="error", rule="aggregate", evidence=_evidence_for("error"))
    if any(v == "ok_with_warning" for v in values):
        return Outcome(
            value="ok_with_warning",
            rule="aggregate",
            evidence=_evidence_for("ok_with_warning"),
        )

    if require:
        relevant = [inv for inv in invocations if inv.name in require]
        if (
            completion == "complete"
            and relevant
            and all(inv.outcome.value == "ok" for inv in relevant)
        ):
            evidence = [e for inv in relevant for e in inv.outcome.evidence]
            return Outcome(value="ok", rule="aggregate", evidence=evidence)
        return Outcome(value="unknown", rule="aggregate", evidence=[])

    if (
        completion == "complete"
        and invocations
        and all(inv.outcome.value == "ok" for inv in invocations)
    ):
        evidence = [e for inv in invocations for e in inv.outcome.evidence]
        return Outcome(value="ok", rule="aggregate", evidence=evidence)
    return Outcome(value="unknown", rule="aggregate", evidence=[])


def _field_episode_outcome(
    profile: Profile, records: Sequence[Mapping[str, Any]], events: list[SeqEvent]
) -> Outcome:
    spec = profile.outcome_episode
    if not isinstance(spec, EpisodeOutcomeField):
        return Outcome(value="unknown", rule="no_evidence", evidence=[])
    for event, record in zip(events, records, strict=True):
        if not _match_when(spec.on, record):
            continue
        raw = record.get(spec.field)
        if raw == "running":
            value: OutcomeValue = "unknown"
        elif raw in ("ok", "ok_with_warning", "error", "aborted", "incomplete", "unknown"):
            value = raw  # type: ignore[assignment]
        else:
            value = "unknown"
        return Outcome(value=value, rule="episode_field", evidence=[event.ref])
    return Outcome(value="unknown", rule="no_evidence", evidence=[])


def _completion_for(
    profile: Profile, invocations: list[Invocation], saw_episode_end: bool
) -> Completion:
    when = profile.complete_when
    if when is None:
        return "unknown"
    if isinstance(when, CompleteWhenEnd):
        return "complete" if saw_episode_end else "incomplete"
    if isinstance(when, CompleteWhenInvocations):
        by_name = {inv.name: inv for inv in invocations if inv.name is not None}
        for name in when.invocations:
            inv = by_name.get(name)
            if inv is None or not inv.complete:
                return "incomplete"
        return "complete"
    return "unknown"


def _span_duration(
    state: _SpanState,
    events: list[SeqEvent],
    records: Sequence[Mapping[str, Any]],
    *,
    api_role: bool,
) -> tuple[Duration, list[str], dict[str, str]]:
    """Return duration, evidence ids, and boundary kinds."""
    boundaries = {
        "start": "observed" if state.start is not None else "unavailable",
        "end": "observed" if state.end is not None else "unavailable",
    }
    evidence: list[str] = []

    start_line = state.start.source_line if state.start is not None else None
    if api_role:
        for event, record in zip(events, records, strict=True):
            if record.get("event") != "span.end":
                continue
            if record.get("span_role") != "api_invocation":
                continue
            if start_line is not None and record.get("source_line_start") == start_line:
                if "span_boundary_start" in record:
                    boundaries["start"] = str(record["span_boundary_start"])
                if "span_boundary_end" in record:
                    boundaries["end"] = str(record["span_boundary_end"])
                ms = record.get("duration_ms")
                if isinstance(ms, (int, float)):
                    kind = (
                        "derived"
                        if record.get("duration_ms_provenance")
                        else "measured"
                    )
                    evidence.append(event.ref.id)
                    return Duration(float(ms), kind), evidence, boundaries  # type: ignore[arg-type]

    if state.start is None or state.end is None:
        return Duration(None, "unavailable"), evidence, boundaries
    start_ts = parse_timestamp(state.start.timestamp)
    end_ts = parse_timestamp(state.end.timestamp)
    ms = _ms_between(start_ts, end_ts)
    if ms is None:
        return Duration(None, "unavailable"), evidence, boundaries
    return Duration(ms, "derived"), evidence, boundaries


def _interval_complete(spec: SpanRoleSpec, record: Mapping[str, Any]) -> bool:
    if spec.incomplete_when and _match_when(spec.incomplete_when, record):
        return False
    if spec.end_attr is not None and spec.end_attr not in record:
        return False
    return True


def _open_parent_index(
    open_by_role: Mapping[str, int],
    roles: Mapping[str, SpanRoleSpec],
    parent_role: str | None,
) -> int | None:
    if parent_role is None:
        return None
    if parent_role in open_by_role:
        return open_by_role[parent_role]
    # Walk up declared parents if the direct parent role is already closed.
    current = roles.get(parent_role)
    while current is not None and current.parent is not None:
        if current.parent in open_by_role:
            return open_by_role[current.parent]
        current = roles.get(current.parent)
    return open_by_role.get("episode")


def _attach_target(
    profile: Profile,
    open_by_role: Mapping[str, int],
    *,
    on: str | None,
    opened_index: int | None,
) -> int | None:
    if opened_index is not None:
        return opened_index
    if on is not None:
        if on in open_by_role:
            return open_by_role[on]
        roles = role_by_name(profile)
        current = roles.get(on)
        while current is not None and current.parent is not None:
            if current.parent in open_by_role:
                return open_by_role[current.parent]
            current = roles.get(current.parent)
    if profile.invocation_role and profile.invocation_role in open_by_role:
        return open_by_role[profile.invocation_role]
    return open_by_role.get("episode")


def _invocation_index_for(
    span_states: Sequence[_SpanState],
    span_index: int | None,
    *,
    invocation_role: str | None,
) -> int | None:
    if span_index is None or invocation_role is None:
        return None
    cursor: int | None = span_index
    while cursor is not None:
        state = span_states[cursor]
        if state.role == invocation_role:
            inv_i = 0
            for other in span_states:
                if other.role != invocation_role:
                    continue
                if other.index == state.index:
                    return inv_i
                inv_i += 1
            return None
        cursor = state.parent_index
    return None


def _episode_duration_and_boundaries(
    events: list[SeqEvent],
    records: Sequence[Mapping[str, Any]],
    first: RecordRef,
    last: RecordRef,
) -> tuple[Duration, float | None, dict[str, str], list[str]]:
    boundaries = {"start": "inferred", "end": "inferred"}
    evidence: list[str] = []
    for event, record in zip(events, records, strict=True):
        if record.get("event") != "span.end":
            continue
        if record.get("span_role") != "multi_api_episode" and record.get("span") != "episode":
            continue
        if "span_boundary_start" in record:
            boundaries["start"] = str(record["span_boundary_start"])
        if "span_boundary_end" in record:
            boundaries["end"] = str(record["span_boundary_end"])
        ms = record.get("duration_ms")
        if isinstance(ms, (int, float)):
            kind = "derived" if record.get("duration_ms_provenance") else "measured"
            evidence.append(event.ref.id)
            return Duration(float(ms), kind), None, boundaries, evidence  # type: ignore[arg-type]

    start_ts = parse_timestamp(first.timestamp)
    end_ts = parse_timestamp(last.timestamp)
    ms = _ms_between(start_ts, end_ts)
    if ms is None:
        return Duration(None, "unavailable"), None, boundaries, evidence
    # Synthetic measured root span without provenance already handled above.
    # Observed episodes: derived from first/last.
    return Duration(ms, "derived"), None, boundaries, evidence


def build_episode(
    profile: Profile,
    *,
    key: str,
    key_fields: dict[str, Any],
    variant: str,
    records: list[dict[str, Any]],
    global_orders: list[int],
) -> Episode:
    """Build one :class:`Episode` from reading-ordered records."""
    events: list[SeqEvent] = []
    span_states: list[_SpanState] = []
    open_by_role: dict[str, int] = {}
    warnings: list[str] = []
    occurrence_counts: dict[tuple[int, str], int] = {}
    saw_episode_end = False
    prev_ts: datetime | None = None
    non_monotonic = 0
    roles = role_by_name(profile)
    name_field = profile.invocation.name if profile.invocation is not None else None
    rule_on = {rule.id: rule.on for rule in profile.rules}

    root = _SpanState(index=0, role="episode", name=None, parent_index=None)
    span_states.append(root)
    open_by_role["episode"] = 0

    for local_i, (record, order) in enumerate(zip(records, global_orders, strict=True)):
        ts = parse_timestamp(record.get("timestamp"))
        if prev_ts is not None and ts is not None and ts < prev_ts:
            non_monotonic += 1
        if ts is not None:
            prev_ts = ts

        category, token, rule_id = classify(profile, record)
        ref = _record_ref(record)
        if category == "episode_end":
            saw_episode_end = True

        opened_index: int | None = None

        if category == "invocation_start" and profile.invocation_role is not None:
            role = profile.invocation_role
            name_val = record.get(name_field) if name_field else None
            name = format_token_value(name_val) if name_val is not None else None
            if role in open_by_role:
                current = span_states[open_by_role[role]]
                if current.name == name and not current.complete:
                    warnings.append("invocation_restart")
                open_by_role.pop(role, None)
            parent_index = _open_parent_index(
                open_by_role, roles, roles[role].parent
            )
            state = _SpanState(
                index=len(span_states),
                role=role,
                name=name,
                parent_index=parent_index,
                start=ref,
                start_order=order,
            )
            span_states.append(state)
            if parent_index is not None:
                span_states[parent_index].children.append(state.index)
            open_by_role[role] = state.index
            opened_index = state.index
        elif category == "invocation_end" and profile.invocation_role is not None:
            role = profile.invocation_role
            name_val = record.get(name_field) if name_field else None
            name = format_token_value(name_val) if name_val is not None else None
            open_index = open_by_role.get(role)
            if open_index is not None and span_states[open_index].name == name:
                span_states[open_index].end = ref
                span_states[open_index].end_order = order
                span_states[open_index].complete = True
                opened_index = open_index
                open_by_role.pop(role, None)
            else:
                warnings.append("unmatched_invocation_end")
        else:
            for spec in profile.span_roles:
                if spec.bounds != "interval":
                    continue
                if not _match_when(spec.when, record):
                    continue
                if spec.role in open_by_role:
                    prev = span_states[open_by_role[spec.role]]
                    if not prev.complete:
                        prev.end = ref
                        prev.end_order = order
                    open_by_role.pop(spec.role, None)
                parent_index = _open_parent_index(open_by_role, roles, spec.parent)
                name_token = None
                token_field = spec.token or spec.name
                if token_field is not None and token_field in record:
                    name_token = format_token_value(record[token_field])
                complete = _interval_complete(spec, record)
                end_ref = ref if complete and spec.end_attr and spec.end_attr in record else (
                    ref if complete else None
                )
                # Interval end is the end_timestamp field's instant when present;
                # the record itself remains the start/anchor ref.
                if complete and spec.end_attr and isinstance(record.get(spec.end_attr), str):
                    end_ref = RecordRef(
                        id=ref.id,
                        timestamp=str(record[spec.end_attr]),
                        source_line=ref.source_line,
                    )
                state = _SpanState(
                    index=len(span_states),
                    role=spec.role,
                    name=name_token,
                    parent_index=parent_index,
                    start=ref,
                    start_order=order,
                    end=end_ref,
                    end_order=order if complete else None,
                    complete=complete,
                )
                span_states.append(state)
                if parent_index is not None:
                    span_states[parent_index].children.append(state.index)
                if not complete:
                    open_by_role[spec.role] = state.index
                opened_index = state.index
                break

        on_role = rule_on.get(rule_id) if rule_id else None
        if category == "outcome" and profile.invocation_role is not None:
            name_val = record.get(name_field) if name_field else None
            span_index = _nearest_span(
                [s for s in span_states if s.role == profile.invocation_role],
                role=profile.invocation_role,
                name_field=name_field,
                order=order,
                name_field_value=format_token_value(name_val)
                if name_val is not None
                else None,
            )
        else:
            span_index = _attach_target(
                profile,
                open_by_role,
                on=on_role,
                opened_index=opened_index,
            )

        inv_index = _invocation_index_for(
            span_states, span_index, invocation_role=profile.invocation_role
        )
        # One-level profiles (no invocation role): treat the root as invocation 0.
        if profile.invocation_role is None:
            inv_index = 0

        occ_n = 0
        occ_label = None
        occ_scope = inv_index if inv_index is not None else span_index
        if token is not None and occ_scope is not None:
            occ_key = (occ_scope, token)
            occurrence_counts[occ_key] = occurrence_counts.get(occ_key, 0) + 1
            occ_n = occurrence_counts[occ_key]
            occ_label = _occurrence_label(profile, record)

        event = SeqEvent(
            ref=ref,
            order=order,
            ts=ts,
            category=category,
            token=token,
            rule=rule_id,
            occurrence_n=occ_n,
            occurrence_label=occ_label,
            span_index=span_index,
            invocation_index=inv_index,
            attrs=_keep_attrs(profile, record),
        )
        events.append(event)
        if span_index is not None:
            span_states[span_index].event_indexes.append(local_i)
            if category in ("outcome", "abort", "error", "observation", "step"):
                span_states[span_index].outcome_records.append((local_i, record, ref))
            # Outcome rules for the invocation role also see events attached to
            # nested children (motion/gripper), so bubble those records up.
            if (
                profile.invocation_role is not None
                and span_states[span_index].role != profile.invocation_role
                and category in ("outcome", "abort", "error", "observation", "step")
            ):
                inv_span = _invocation_index_for(
                    span_states, span_index, invocation_role=profile.invocation_role
                )
                if inv_span is not None:
                    # Map invocation list index back to span index.
                    inv_i = 0
                    for state in span_states:
                        if state.role != profile.invocation_role:
                            continue
                        if inv_i == inv_span:
                            state.outcome_records.append((local_i, record, ref))
                            state.event_indexes.append(local_i)
                            break
                        inv_i += 1

    if non_monotonic:
        warnings.append(f"non_monotonic:{non_monotonic}")

    app_events = [e for e in events if e.category != "span_event"]
    anchor_events = app_events or events
    if isinstance(profile.complete_when, CompleteWhenEnd):
        span_states[0].complete = saw_episode_end
    else:
        span_states[0].complete = True
    if profile.invocation_role is None:
        if isinstance(profile.complete_when, CompleteWhenEnd):
            span_states[0].complete = saw_episode_end
        else:
            span_states[0].complete = bool(events)
    if anchor_events:
        span_states[0].start = anchor_events[0].ref
        span_states[0].start_order = anchor_events[0].order
        span_states[0].end = anchor_events[-1].ref
        span_states[0].end_order = anchor_events[-1].order

    spans: list[Span] = []
    inv_boundaries: list[dict[str, str]] = []
    duration_evidence_by_inv: list[list[str]] = []
    invocations: list[Invocation] = []
    inv_list_index = 0
    for state in span_states:
        is_inv = (
            profile.invocation_role is not None and state.role == profile.invocation_role
        ) or (profile.invocation_role is None and state.role == "episode")
        outcome = (
            _span_outcome(profile, state, events, records)
            if is_inv or state.role == "episode"
            else Outcome(value="unknown", rule="no_evidence", evidence=[])
        )
        duration, evidence, boundaries = _span_duration(
            state, events, records, api_role=is_inv and state.role != "episode"
        )
        if profile.invocation_role is None and state.role == "episode":
            if isinstance(profile.complete_when, CompleteWhenEnd):
                state.complete = saw_episode_end
            else:
                state.complete = bool(events)
        elif state.role == profile.invocation_role:
            state.complete = state.start is not None and state.end is not None

        spans.append(
            Span(
                index=state.index,
                role=state.role,
                name=state.name,
                parent_index=state.parent_index,
                start=state.start,
                end=state.end if state.complete or state.end is not None else state.end,
                complete=state.complete,
                outcome=outcome,
                duration=duration,
                children=list(state.children),
                events=list(state.event_indexes),
            )
        )
        if is_inv:
            invocations.append(
                Invocation(
                    index=inv_list_index,
                    name=state.name,
                    start=state.start,
                    end=(
                        state.end
                        if state.complete or profile.invocation_role is not None
                        else None
                    ),
                    complete=state.complete,
                    outcome=outcome,
                    duration=duration,
                    events=list(state.event_indexes),
                    span_index=state.index,
                )
            )
            inv_boundaries.append(boundaries)
            duration_evidence_by_inv.append(evidence)
            inv_list_index += 1

    completion = _completion_for(profile, invocations, saw_episode_end)
    if isinstance(profile.outcome_episode, EpisodeOutcomeField):
        outcome = _field_episode_outcome(profile, records, events)
        if not saw_episode_end and isinstance(profile.complete_when, CompleteWhenEnd):
            outcome = Outcome(value="unknown", rule="no_evidence", evidence=outcome.evidence)
    else:
        outcome = _aggregate_episode_outcome(profile, invocations, completion)

    first = anchor_events[0].ref
    last = anchor_events[-1].ref
    duration, elapsed_override, ep_boundaries, ep_evidence = _episode_duration_and_boundaries(
        events, records, first, last
    )
    elapsed_ms: float | None = None
    if isinstance(profile.complete_when, CompleteWhenEnd) and not saw_episode_end:
        duration = Duration(None, "unavailable")
        elapsed_ms = _ms_between(parse_timestamp(first.timestamp), parse_timestamp(last.timestamp))
    elif elapsed_override is not None:
        elapsed_ms = elapsed_override

    recovery_of = None
    triggered = None
    if profile.links_recovery_of:
        for record in records:
            if profile.links_recovery_of in record and record[profile.links_recovery_of]:
                recovery_of = format_token_value(record[profile.links_recovery_of])
                break
    if profile.links_triggered_recovery:
        for record in records:
            if (
                profile.links_triggered_recovery in record
                and record[profile.links_triggered_recovery]
            ):
                triggered = format_token_value(record[profile.links_triggered_recovery])
                break

    episode = Episode(
        key=key,
        key_fields=key_fields,
        variant=variant,
        events=events,
        spans=spans,
        root=0,
        invocations=invocations,
        outcome=outcome,
        completion=completion,
        links=Links(recovery_of=recovery_of, triggered_recovery=triggered),
        first=first,
        last=last,
        duration=duration,
        warnings=warnings,
        truncated=False,
    )
    episode._seq_meta = {  # type: ignore[attr-defined]
        "elapsed_ms": elapsed_ms,
        "boundaries": ep_boundaries,
        "invocation_boundaries": inv_boundaries,
        "duration_evidence": ep_evidence,
        "invocation_duration_evidence": duration_evidence_by_inv,
        "span_events": sum(1 for e in events if e.category == "span_event"),
    }
    return episode


def episode_summary(ep: Episode) -> dict[str, Any]:
    """JSON-serialisable summary used by ``episodes`` / ``_episode`` control lines."""
    meta = getattr(ep, "_seq_meta", {})
    inv_boundaries = meta.get("invocation_boundaries", [{} for _ in ep.invocations])
    inv_evidence = meta.get("invocation_duration_evidence", [[] for _ in ep.invocations])
    invocations = []
    for inv, boundaries, evidence in zip(
        ep.invocations, inv_boundaries, inv_evidence, strict=False
    ):
        invocations.append(
            {
                "index": inv.index,
                "name": inv.name,
                "complete": inv.complete,
                "outcome": {
                    "value": inv.outcome.value,
                    "rule": inv.outcome.rule,
                    "evidence": [_ref_dict(r) for r in inv.outcome.evidence],
                },
                "duration": {"ms": inv.duration.ms, "kind": inv.duration.kind},
                "duration_evidence": evidence,
                "boundaries": boundaries,
                "start": _ref_dict(inv.start) if inv.start else None,
                "end": _ref_dict(inv.end) if inv.end else None,
                "event_count": len(inv.events),
                "span_index": inv.span_index,
            }
        )
    span_rows = []
    for span in ep.spans:
        span_rows.append(
            {
                "index": span.index,
                "role": span.role,
                "name": span.name,
                "parent_index": span.parent_index,
                "complete": span.complete,
                "children": list(span.children),
                "event_count": len(span.events),
                "start": _ref_dict(span.start) if span.start else None,
                "end": _ref_dict(span.end) if span.end else None,
                "duration": {"ms": span.duration.ms, "kind": span.duration.kind},
            }
        )
    payload: dict[str, Any] = {
        "key": ep.key,
        "key_fields": ep.key_fields,
        "variant": ep.variant,
        "root": ep.root,
        "spans": span_rows,
        "span_count": len(ep.spans),
        "invocations": invocations,
        "invocation_count": len(ep.invocations),
        "outcome": {
            "value": ep.outcome.value,
            "rule": ep.outcome.rule,
            "evidence": [_ref_dict(r) for r in ep.outcome.evidence],
        },
        "completion": ep.completion,
        "links": {
            "recovery_of": ep.links.recovery_of,
            "triggered_recovery": ep.links.triggered_recovery,
        },
        "first": _ref_dict(ep.first),
        "last": _ref_dict(ep.last),
        "duration": {"ms": ep.duration.ms, "kind": ep.duration.kind},
        "duration_evidence": meta.get("duration_evidence", []),
        "elapsed_ms": meta.get("elapsed_ms"),
        "boundaries": meta.get("boundaries", {"start": "inferred", "end": "inferred"}),
        "span_events": meta.get("span_events", 0),
        "event_count": len(ep.events),
        "warnings": list(ep.warnings),
        "truncated": ep.truncated,
    }
    return payload


def _ref_dict(ref: RecordRef) -> dict[str, Any]:
    return {
        "id": ref.id,
        "timestamp": ref.timestamp,
        "source_line": ref.source_line,
    }


@dataclass
class _OpenEpisode:
    key: str
    key_fields: dict[str, Any]
    variant: str
    records: list[dict[str, Any]] = field(default_factory=list)
    orders: list[int] = field(default_factory=list)
    selection_hit: bool = False
    overflow: int = 0


def extract_episodes(
    sources: str
    | Any
    | Sequence[Any]
    | Iterable[Mapping[str, Any]],
    *,
    profile: Profile,
    filters: Filters | None = None,
    episode_keys: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    completion: str | None = None,
    variant: str | None = None,
    order: Order = "concat",
    after: str | None = None,
    max_open_episodes: int = 10_000,
    max_events_per_episode: int = 100_000,
    top: int | None = 50,
) -> EpisodesResult:
    """Group records into episodes, classify, and compute outcomes."""
    reader = Reader(sources, after=after, complete=True, order=order)
    open_map: dict[tuple[str, str], _OpenEpisode] = {}
    finished_order: list[tuple[str, str]] = []
    seen_slots: set[tuple[str, str]] = set()
    warnings: list[str] = []
    unassigned = 0
    capped_new_keys = 0
    global_order = 0
    last_cursor: str | None = None
    variant_seen: dict[str, set[str]] = {}

    for record in reader:
        last_cursor = reader.cursor()
        keyed = episode_key_for(profile, record)
        if keyed is None:
            unassigned += 1
            global_order += 1
            continue
        key, key_fields = keyed
        rec_variant = "default"
        if profile.variant_key and profile.variant_key in record:
            rec_variant = format_token_value(record[profile.variant_key])

        variants_for_key = variant_seen.setdefault(key, set())
        if variants_for_key and rec_variant not in variants_for_key:
            warning = f"variant_collision:{key}"
            if warning not in warnings:
                warnings.append(warning)
        variants_for_key.add(rec_variant)

        slot = (rec_variant, key)
        if slot not in seen_slots:
            seen_slots.add(slot)
            if len(open_map) >= max_open_episodes:
                capped_new_keys += 1
            else:
                open_map[slot] = _OpenEpisode(
                    key=key, key_fields=key_fields, variant=rec_variant
                )
                finished_order.append(slot)

        bucket = open_map.get(slot)
        if bucket is None:
            global_order += 1
            continue
        if filters is not None and filters.matches(record):
            bucket.selection_hit = True
        if len(bucket.records) < max_events_per_episode:
            bucket.records.append(dict(record))
            bucket.orders.append(global_order)
        else:
            bucket.overflow += 1
        global_order += 1

    skipped = getattr(reader, "skipped_lines", 0)
    for item in list(getattr(reader, "warnings", []) or []):
        if item not in warnings:
            warnings.append(item)

    built: list[Episode] = []
    for slot in finished_order:
        bucket = open_map[slot]
        episode = build_episode(
            profile,
            key=bucket.key,
            key_fields=bucket.key_fields,
            variant=bucket.variant,
            records=bucket.records,
            global_orders=bucket.orders,
        )
        if bucket.overflow:
            episode.truncated = True
            episode.warnings.append(f"max_events:{bucket.overflow}")
        if filters is not None and not bucket.selection_hit:
            continue
        if episode_keys and episode.key not in set(episode_keys):
            continue
        if outcomes and episode.outcome.value not in set(outcomes):
            continue
        if completion is not None and episode.completion != completion:
            continue
        if variant is not None and episode.variant != variant:
            continue
        built.append(episode)

    total = len(seen_slots)
    episodes_capped = capped_new_keys > 0
    truncated = False
    next_cursor = None
    if top is not None and len(built) > top:
        truncated = True
        built = built[:top]
        next_cursor = last_cursor

    return EpisodesResult(
        episodes=built,
        total=total,
        returned=len(built),
        truncated=truncated,
        episodes_capped=episodes_capped,
        unassigned_records=unassigned,
        skipped_lines=int(skipped) if skipped else 0,
        next_cursor=next_cursor,
        warnings=warnings,
        order_basis="reading",
    )


def get_episode(
    sources: Any,
    key: str,
    *,
    profile: Profile,
    variant: str | None = None,
    order: Order = "concat",
    max_events_per_episode: int = 100_000,
) -> tuple[Episode, list[dict[str, Any]]]:
    """Return one episode and its original records. Raises ``episode_not_found``."""
    result = extract_episodes(
        sources,
        profile=profile,
        episode_keys=(key,),
        variant=variant,
        order=order,
        max_events_per_episode=max_events_per_episode,
        top=None,
    )
    matches = [
        ep
        for ep in result.episodes
        if ep.key == key and (variant is None or ep.variant == variant)
    ]
    if not matches:
        raise ToolError("episode_not_found", f"episode not found: {key}", key=key)
    episode = matches[0]
    # Re-read records for this key
    records: list[dict[str, Any]] = []
    reader = Reader(sources, complete=True, order=order)
    for record in reader:
        keyed = episode_key_for(profile, record)
        if keyed is None:
            continue
        rec_key, _ = keyed
        if rec_key != key:
            continue
        rec_variant = "default"
        if profile.variant_key and profile.variant_key in record:
            rec_variant = format_token_value(record[profile.variant_key])
        if episode.variant != rec_variant:
            continue
        records.append(dict(record))
        if len(records) >= max_events_per_episode:
            break
    return episode, records
