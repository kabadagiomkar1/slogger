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
)
from slogger.tools.seq.profile import (
    CompleteWhenEnd,
    CompleteWhenInvocations,
    EpisodeOutcomeAggregate,
    EpisodeOutcomeField,
    Profile,
    classify,
    format_token_value,
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
class _InvState:
    index: int
    name: str | None
    start: RecordRef | None = None
    start_order: int | None = None
    end: RecordRef | None = None
    end_order: int | None = None
    event_indexes: list[int] = field(default_factory=list)
    outcome_records: list[tuple[int, dict[str, Any], RecordRef]] = field(default_factory=list)


def _nearest_invocation(
    invs: list[_InvState],
    *,
    name: str | None,
    order: int,
    name_field_value: object | None,
) -> int | None:
    if not invs:
        return None
    if name is not None and name_field_value is not None:
        candidates = [inv for inv in invs if inv.name == name_field_value]
    else:
        candidates = list(invs)
    if not candidates:
        return invs[-1].index
    best: _InvState | None = None
    best_dist: float | None = None
    for inv in candidates:
        start = inv.start_order if inv.start_order is not None else inv.index
        end = inv.end_order if inv.end_order is not None else (
            inv.start_order if inv.start_order is not None else inv.index
        )
        if start <= order <= end:
            dist = 0.0
        elif order < start:
            dist = float(start - order)
        else:
            dist = float(order - end)
        if best is None or best_dist is None or dist < best_dist:
            best = inv
            best_dist = dist
    return best.index if best is not None else invs[-1].index


def _invocation_outcome(
    profile: Profile,
    inv: _InvState,
    events: list[SeqEvent],
    records: list[dict[str, Any]],
) -> Outcome:
    # Prefer outcome_records attached via same_name_nearest; also scan event attrs.
    candidates: list[tuple[dict[str, Any], RecordRef]] = [
        (rec, ref) for _, rec, ref in inv.outcome_records
    ]
    for event_index in inv.event_indexes:
        event = events[event_index]
        if event.category in ("outcome", "abort", "error", "observation"):
            # Reconstruct minimal record from attrs + known fields for rule matching.
            # Rules match against original records stored alongside.
            pass
    # Use original records referenced by event order via side channel
    for event_index in inv.event_indexes:
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


def _invocation_duration(
    profile: Profile,
    inv: _InvState,
    events: list[SeqEvent],
    records: Sequence[Mapping[str, Any]],
) -> tuple[Duration, list[str], dict[str, str]]:
    """Return duration, evidence ids, and boundary kinds."""
    boundaries = {
        "start": "observed" if inv.start is not None else "unavailable",
        "end": "observed" if inv.end is not None else "unavailable",
    }
    evidence: list[str] = []

    # Enriched proposed span may supply derived duration + inferred boundaries.
    start_line = inv.start.source_line if inv.start is not None else None
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

    if inv.start is None or inv.end is None:
        return Duration(None, "unavailable"), evidence, boundaries
    start_ts = parse_timestamp(inv.start.timestamp)
    end_ts = parse_timestamp(inv.end.timestamp)
    ms = _ms_between(start_ts, end_ts)
    if ms is None:
        return Duration(None, "unavailable"), evidence, boundaries
    return Duration(ms, "derived"), evidence, boundaries


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
    inv_states: list[_InvState] = []
    open_index: int | None = None
    warnings: list[str] = []
    occurrence_counts: dict[tuple[int, str], int] = {}
    saw_episode_end = False
    prev_ts: datetime | None = None
    non_monotonic = 0
    implicit = profile.invocation is None
    if implicit:
        inv_states.append(_InvState(index=0, name=None))
        open_index = 0

    name_field = profile.invocation.name if profile.invocation is not None else None

    for local_i, (record, order) in enumerate(zip(records, global_orders, strict=True)):
        ts = parse_timestamp(record.get("timestamp"))
        if prev_ts is not None and ts is not None and ts < prev_ts:
            non_monotonic += 1
        if ts is not None:
            prev_ts = ts

        category, token, rule_id = classify(profile, record)
        ref = _record_ref(record)
        inv_index: int | None = open_index

        if category == "episode_end":
            saw_episode_end = True

        if not implicit and profile.invocation is not None:
            if category == "invocation_start":
                name_val = record.get(name_field) if name_field else None
                name = format_token_value(name_val) if name_val is not None else None
                if open_index is not None:
                    current = inv_states[open_index]
                    if current.name == name and current.end is None:
                        warnings.append("invocation_restart")
                        open_index = None
                state = _InvState(index=len(inv_states), name=name, start=ref, start_order=order)
                inv_states.append(state)
                open_index = state.index
                inv_index = open_index
            elif category == "invocation_end":
                name_val = record.get(name_field) if name_field else None
                name = format_token_value(name_val) if name_val is not None else None
                if open_index is not None and inv_states[open_index].name == name:
                    inv_states[open_index].end = ref
                    inv_states[open_index].end_order = order
                    inv_index = open_index
                    open_index = None
                else:
                    warnings.append("unmatched_invocation_end")
                    inv_index = None
            elif category == "outcome":
                name_val = record.get(name_field) if name_field else None
                inv_index = _nearest_invocation(
                    inv_states,
                    name=name_field,
                    order=order,
                    name_field_value=format_token_value(name_val)
                    if name_val is not None
                    else None,
                )
            else:
                inv_index = open_index

        occ_n = 0
        occ_label = None
        if token is not None and inv_index is not None:
            occ_key = (inv_index, token)
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
            invocation_index=inv_index,
            attrs=_keep_attrs(profile, record),
        )
        events.append(event)
        if inv_index is not None:
            inv_states[inv_index].event_indexes.append(local_i)
            if category in ("outcome", "abort", "error", "observation", "step"):
                inv_states[inv_index].outcome_records.append((local_i, record, ref))

    if non_monotonic:
        warnings.append(f"non_monotonic:{non_monotonic}")

    # Close implicit invocation
    if implicit and inv_states:
        inv_states[0].start = events[0].ref if events else None
        inv_states[0].start_order = global_orders[0] if global_orders else None
        inv_states[0].end = events[-1].ref if events else None
        inv_states[0].end_order = global_orders[-1] if global_orders else None

    invocations: list[Invocation] = []
    inv_boundaries: list[dict[str, str]] = []
    duration_evidence_by_inv: list[list[str]] = []
    for state in inv_states:
        outcome = _invocation_outcome(profile, state, events, records)
        duration, evidence, boundaries = _invocation_duration(
            profile, state, events, records
        )
        complete = state.start is not None and state.end is not None
        if implicit:
            # Implicit invocation completeness follows episode end when configured.
            if isinstance(profile.complete_when, CompleteWhenEnd):
                complete = saw_episode_end
            else:
                complete = bool(events)
        invocations.append(
            Invocation(
                index=state.index,
                name=state.name,
                start=state.start,
                end=state.end if not implicit or saw_episode_end else state.end,
                complete=complete,
                outcome=outcome,
                duration=duration,
                events=list(state.event_indexes),
            )
        )
        inv_boundaries.append(boundaries)
        duration_evidence_by_inv.append(evidence)

    completion = _completion_for(profile, invocations, saw_episode_end)
    if isinstance(profile.outcome_episode, EpisodeOutcomeField):
        outcome = _field_episode_outcome(profile, records, events)
        # incomplete without end → unknown even if field missing
        if not saw_episode_end and isinstance(profile.complete_when, CompleteWhenEnd):
            outcome = Outcome(value="unknown", rule="no_evidence", evidence=outcome.evidence)
    else:
        outcome = _aggregate_episode_outcome(profile, invocations, completion)

    # Prefer application records for first/last so source vs enriched summaries
    # share source_line identity (span rows sort before the derived app record).
    app_events = [e for e in events if e.category != "span_event"]
    anchor_events = app_events or events
    first = anchor_events[0].ref
    last = anchor_events[-1].ref
    duration, elapsed_override, ep_boundaries, ep_evidence = _episode_duration_and_boundaries(
        events, records, first, last
    )
    # incomplete_workflow: no episode end → duration unavailable, expose elapsed_ms
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
    # Stash summary-only metadata on a private attribute for episode_summary.
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
            }
        )
    payload: dict[str, Any] = {
        "key": ep.key,
        "key_fields": ep.key_fields,
        "variant": ep.variant,
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
