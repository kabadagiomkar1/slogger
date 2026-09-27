"""JSON sequence profiles: load, validate, and classify records."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters, Where, parse_where
from slogger.tools.grouping import group_value
from slogger.tools.seq.model import (
    CATEGORIES,
    OUTCOME_VALUES,
    Category,
    OutcomeValue,
)

_ALLOWED_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "name",
        "profile_version",
        "episode",
        "variant_key",
        "occurrence_key",
        "invocation",
        "rules",
        "outcome",
        "links",
        "keep_attrs",
        "spans",
    }
)

SpansMode = Literal["default", "as_steps"]


@dataclass(frozen=True)
class Rule:
    id: str
    category: Category
    when: tuple[Where, ...]
    token: str | None = None
    token_suffix: str | None = None


@dataclass(frozen=True)
class OutcomeRule:
    id: str
    value: OutcomeValue
    when: tuple[Where, ...]


@dataclass(frozen=True)
class EpisodeOutcomeAggregate:
    require_outcome_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpisodeOutcomeField:
    field: str
    on: tuple[Where, ...]


EpisodeOutcomeSpec = EpisodeOutcomeAggregate | EpisodeOutcomeField


@dataclass(frozen=True)
class InvocationSpec:
    name: str | None
    start: tuple[Where, ...]
    end: tuple[Where, ...]
    outcome_window: Literal["same_name_nearest"] = "same_name_nearest"


@dataclass(frozen=True)
class CompleteWhenInvocations:
    invocations: tuple[str, ...]


@dataclass(frozen=True)
class CompleteWhenEnd:
    pass


CompleteWhen = CompleteWhenInvocations | CompleteWhenEnd | None


@dataclass(frozen=True)
class Profile:
    name: str
    profile_version: str
    episode_key: tuple[str, ...]
    fallback_keys: tuple[tuple[str, ...], ...]
    episode_start: tuple[Where, ...]
    episode_end: tuple[Where, ...]
    complete_when: CompleteWhen
    variant_key: str | None
    occurrence_key: tuple[str, ...]
    invocation: InvocationSpec | None
    rules: tuple[Rule, ...]
    outcome_invocation: tuple[OutcomeRule, ...]
    outcome_episode: EpisodeOutcomeSpec
    links_recovery_of: str | None
    links_triggered_recovery: str | None
    keep_attrs: tuple[str, ...]
    spans: SpansMode
    source: str


def _invalid(message: str, **extra: object) -> ToolError:
    return ToolError("profile_invalid", message, **extra)


def _parse_when_list(raw: object, *, context: str) -> tuple[Where, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid(f"{context}: expected list of when tokens")
    clauses: list[Where] = []
    for item in raw:
        if not isinstance(item, str):
            raise _invalid(f"{context}: when tokens must be strings")
        try:
            clauses.append(parse_where(item))
        except ValueError as exc:
            raise _invalid(f"{context}: {exc}") from exc
    return tuple(clauses)


def _parse_str_list(raw: object, *, context: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise _invalid(f"{context}: expected non-empty-string list")
    return tuple(raw)


def _parse_fallback_keys(raw: object) -> tuple[tuple[str, ...], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid("episode.fallback_keys: expected list of key lists")
    result: list[tuple[str, ...]] = []
    for item in raw:
        keys = _parse_str_list(item, context="episode.fallback_keys[]")
        if not keys:
            raise _invalid("episode.fallback_keys[]: key list must be non-empty")
        result.append(keys)
    return tuple(result)


def _parse_complete_when(raw: object) -> CompleteWhen:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("episode.complete_when: expected object")
    if "invocations" in raw:
        inv = _parse_str_list(raw["invocations"], context="episode.complete_when.invocations")
        if not inv:
            raise _invalid("episode.complete_when.invocations: must be non-empty")
        extra = set(raw) - {"invocations"}
        if extra:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(extra)}")
        return CompleteWhenInvocations(invocations=inv)
    if raw.get("end") is True:
        extra = set(raw) - {"end"}
        if extra:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(extra)}")
        return CompleteWhenEnd()
    raise _invalid("episode.complete_when: need invocations or end:true")


def _parse_invocation(raw: object) -> InvocationSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("invocation: expected object")
    allowed = {"name", "start", "end", "outcome_window"}
    unknown = set(raw) - allowed
    if unknown:
        raise _invalid(f"invocation: unknown keys {sorted(unknown)}")
    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise _invalid("invocation.name: expected string")
    window = raw.get("outcome_window", "same_name_nearest")
    if window != "same_name_nearest":
        raise _invalid(f"invocation.outcome_window: unsupported {window!r}")
    return InvocationSpec(
        name=name,
        start=_parse_when_list(raw.get("start", []), context="invocation.start"),
        end=_parse_when_list(raw.get("end", []), context="invocation.end"),
        outcome_window="same_name_nearest",
    )


def _parse_rules(raw: object) -> tuple[Rule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid("rules: expected list")
    seen: set[str] = set()
    rules: list[Rule] = []
    for index, item in enumerate(raw):
        context = f"rules[{index}]"
        if not isinstance(item, dict):
            raise _invalid(f"{context}: expected object")
        allowed = {"id", "category", "when", "token", "token_suffix"}
        unknown = set(item) - allowed
        if unknown:
            raise _invalid(f"{context}: unknown keys {sorted(unknown)}")
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise _invalid(f"{context}: id must be a non-empty string")
        if rule_id in seen:
            raise _invalid(f"duplicate rule id: {rule_id!r}")
        seen.add(rule_id)
        category = item.get("category")
        if category not in CATEGORIES:
            raise _invalid(f"{context}: invalid category {category!r}")
        token = item.get("token", None)
        if token is not None and not isinstance(token, str):
            raise _invalid(f"{context}: token must be string or null")
        token_suffix = item.get("token_suffix")
        if token_suffix is not None and not isinstance(token_suffix, str):
            raise _invalid(f"{context}: token_suffix must be string")
        rules.append(
            Rule(
                id=rule_id,
                category=category,  # type: ignore[arg-type]
                when=_parse_when_list(item.get("when", []), context=f"{context}.when"),
                token=token,
                token_suffix=token_suffix,
            )
        )
    return tuple(rules)


def _parse_outcome_rules(raw: object, *, context: str) -> tuple[OutcomeRule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid(f"{context}: expected list")
    seen: set[str] = set()
    rules: list[OutcomeRule] = []
    for index, item in enumerate(raw):
        ctx = f"{context}[{index}]"
        if not isinstance(item, dict):
            raise _invalid(f"{ctx}: expected object")
        allowed = {"id", "value", "when"}
        unknown = set(item) - allowed
        if unknown:
            raise _invalid(f"{ctx}: unknown keys {sorted(unknown)}")
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise _invalid(f"{ctx}: id must be a non-empty string")
        if rule_id in seen:
            raise _invalid(f"duplicate outcome rule id: {rule_id!r}")
        seen.add(rule_id)
        value = item.get("value")
        if value not in OUTCOME_VALUES:
            raise _invalid(f"{ctx}: invalid outcome value {value!r}")
        rules.append(
            OutcomeRule(
                id=rule_id,
                value=value,  # type: ignore[arg-type]
                when=_parse_when_list(item.get("when", []), context=f"{ctx}.when"),
            )
        )
    return tuple(rules)


def _parse_outcome_episode(raw: object) -> EpisodeOutcomeSpec:
    if raw is None or raw == "aggregate":
        return EpisodeOutcomeAggregate()
    if isinstance(raw, dict):
        if raw.get("aggregate") is True or "require_outcome_from" in raw:
            allowed = {"aggregate", "require_outcome_from"}
            unknown = set(raw) - allowed
            if unknown:
                raise _invalid(f"outcome.episode: unknown keys {sorted(unknown)}")
            require = _parse_str_list(
                raw.get("require_outcome_from", []),
                context="outcome.episode.require_outcome_from",
            )
            return EpisodeOutcomeAggregate(require_outcome_from=require)
        if "field" in raw:
            allowed = {"field", "on"}
            unknown = set(raw) - allowed
            if unknown:
                raise _invalid(f"outcome.episode: unknown keys {sorted(unknown)}")
            field_name = raw.get("field")
            if not isinstance(field_name, str) or not field_name:
                raise _invalid("outcome.episode.field: expected non-empty string")
            return EpisodeOutcomeField(
                field=field_name,
                on=_parse_when_list(raw.get("on", []), context="outcome.episode.on"),
            )
    raise _invalid("outcome.episode: expected 'aggregate', aggregate object, or field object")


def _parse_links(raw: object) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise _invalid("links: expected object")
    allowed = {"recovery_of", "triggered_recovery"}
    unknown = set(raw) - allowed
    if unknown:
        raise _invalid(f"links: unknown keys {sorted(unknown)}")
    recovery_of = raw.get("recovery_of")
    triggered = raw.get("triggered_recovery")
    if recovery_of is not None and not isinstance(recovery_of, str):
        raise _invalid("links.recovery_of: expected string")
    if triggered is not None and not isinstance(triggered, str):
        raise _invalid("links.triggered_recovery: expected string")
    return recovery_of, triggered


def _parse_episode_block(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _invalid("episode: expected object")
    allowed = {"key", "fallback_keys", "start", "end", "complete_when"}
    unknown = set(raw) - allowed
    if unknown:
        raise _invalid(f"episode: unknown keys {sorted(unknown)}")
    key = _parse_str_list(raw.get("key"), context="episode.key")
    if not key:
        raise _invalid("episode.key: must be a non-empty list of strings")
    return {
        "episode_key": key,
        "fallback_keys": _parse_fallback_keys(raw.get("fallback_keys")),
        "episode_start": _parse_when_list(raw.get("start", []), context="episode.start"),
        "episode_end": _parse_when_list(raw.get("end", []), context="episode.end"),
        "complete_when": _parse_complete_when(raw.get("complete_when")),
    }


def profile_from_dict(data: Mapping[str, Any], *, source: str) -> Profile:
    """Validate a profile mapping and return a :class:`Profile`."""
    if not isinstance(data, Mapping):
        raise _invalid("profile root must be an object")
    unknown = set(data) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise _invalid(f"unknown top-level keys: {sorted(unknown)}", keys=sorted(unknown))

    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise _invalid(f"unsupported schema_version: {schema_version!r}")

    name = data.get("name", "unnamed")
    if not isinstance(name, str) or not name:
        raise _invalid("name: expected non-empty string")
    profile_version = data.get("profile_version", "1")
    if not isinstance(profile_version, str):
        raise _invalid("profile_version: expected string")

    if "episode" not in data:
        raise _invalid("episode: required")
    episode = _parse_episode_block(data["episode"])

    variant_key = data.get("variant_key")
    if variant_key is not None and not isinstance(variant_key, str):
        raise _invalid("variant_key: expected string or null")

    occurrence_key = _parse_str_list(
        data.get("occurrence_key", []), context="occurrence_key"
    )

    spans_raw = data.get("spans", "default")
    if spans_raw is None:
        spans: SpansMode = "default"
    elif spans_raw == "as_steps":
        spans = "as_steps"
    elif spans_raw == "default":
        spans = "default"
    else:
        raise _invalid(f"spans: unsupported {spans_raw!r}")

    keep_attrs = _parse_str_list(data.get("keep_attrs", []), context="keep_attrs")

    outcome_raw = data.get("outcome")
    if outcome_raw is None:
        outcome_invocation: tuple[OutcomeRule, ...] = ()
        outcome_episode: EpisodeOutcomeSpec = EpisodeOutcomeAggregate()
    elif isinstance(outcome_raw, dict):
        allowed = {"invocation", "episode"}
        unknown_out = set(outcome_raw) - allowed
        if unknown_out:
            raise _invalid(f"outcome: unknown keys {sorted(unknown_out)}")
        outcome_invocation = _parse_outcome_rules(
            outcome_raw.get("invocation"), context="outcome.invocation"
        )
        outcome_episode = _parse_outcome_episode(outcome_raw.get("episode"))
    else:
        raise _invalid("outcome: expected object")

    recovery_of, triggered = _parse_links(data.get("links"))

    return Profile(
        name=name,
        profile_version=profile_version,
        episode_key=episode["episode_key"],
        fallback_keys=episode["fallback_keys"],
        episode_start=episode["episode_start"],
        episode_end=episode["episode_end"],
        complete_when=episode["complete_when"],
        variant_key=variant_key,
        occurrence_key=occurrence_key,
        invocation=_parse_invocation(data.get("invocation")),
        rules=_parse_rules(data.get("rules")),
        outcome_invocation=outcome_invocation,
        outcome_episode=outcome_episode,
        links_recovery_of=recovery_of,
        links_triggered_recovery=triggered,
        keep_attrs=keep_attrs,
        spans=spans,
        source=source,
    )


def load_profile(path: str | os.PathLike[str] | None) -> Profile:
    """Load a profile from ``path``, or return :data:`GENERIC_PROFILE` when ``path`` is None."""
    if path is None:
        return GENERIC_PROFILE
    file_path = Path(path)
    if not file_path.is_file():
        raise ToolError("profile_not_found", f"profile not found: {file_path}", path=str(file_path))
    try:
        text = file_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _invalid(f"invalid JSON: {exc}", path=str(file_path)) from exc
    except OSError as exc:
        raise ToolError(
            "profile_not_found", f"cannot read profile: {file_path}", path=str(file_path)
        ) from exc
    if not isinstance(data, dict):
        raise _invalid("profile root must be a JSON object", path=str(file_path))
    return profile_from_dict(data, source=str(file_path))


def format_token_value(value: object) -> str:
    """Stringify a field value with the same normalisation as :func:`group_value`."""
    tagged = group_value({"_": value}, "_")
    if tagged is None:
        return "null"
    kind, normalised = tagged
    if kind == "bool":
        return "true" if normalised else "false"
    if kind == "null":
        return "null"
    if kind == "number":
        assert isinstance(normalised, float)
        if normalised.is_integer():
            return str(int(normalised))
        return str(normalised)
    return str(normalised)


def _rule_matches(when: Sequence[Where], record: Mapping[str, Any]) -> bool:
    if not when:
        return False
    return Filters(where=tuple(when)).matches(record)


def _token_for(
    record: Mapping[str, Any],
    *,
    category: Category,
    token_field: str | None,
    token_suffix: str | None = None,
) -> str | None:
    if token_field is None:
        return None
    if token_field not in record:
        token = f"<{category}>"
    else:
        token = format_token_value(record[token_field])
    if token_suffix is not None and token_suffix in record:
        token = f"{token}={format_token_value(record[token_suffix])}"
    return token


def classify(
    profile: Profile, record: Mapping[str, Any]
) -> tuple[Category, str | None, str | None]:
    """Classify ``record`` under ``profile``. First matching rule wins."""
    event = record.get("event")
    if event in ("span.start", "span.end"):
        if profile.spans == "as_steps":
            if event == "span.end":
                return (
                    "step",
                    _token_for(record, category="step", token_field="span"),
                    "spans",
                )
            return ("span_event", None, None)
        return ("span_event", None, None)

    if profile.episode_start and _rule_matches(profile.episode_start, record):
        return ("episode_start", None, "episode_start")
    if profile.episode_end and _rule_matches(profile.episode_end, record):
        return ("episode_end", None, "episode_end")

    if profile.invocation is not None:
        inv = profile.invocation
        if inv.start and _rule_matches(inv.start, record):
            token = (
                _token_for(record, category="invocation_start", token_field=inv.name)
                if inv.name
                else None
            )
            return ("invocation_start", token, "invocation_start")
        if inv.end and _rule_matches(inv.end, record):
            token = (
                _token_for(record, category="invocation_end", token_field=inv.name)
                if inv.name
                else None
            )
            return ("invocation_end", token, "invocation_end")

    for rule in profile.rules:
        if _rule_matches(rule.when, record):
            token = _token_for(
                record,
                category=rule.category,
                token_field=rule.token,
                token_suffix=rule.token_suffix,
            )
            return (rule.category, token, rule.id)

    return ("other", None, None)


def _build_generic_profile() -> Profile:
    return profile_from_dict(
        {
            "schema_version": 1,
            "name": "generic",
            "profile_version": "1",
            "episode": {
                "key": ["episode_id"],
                "fallback_keys": [["workflow_id"], ["trace_id"]],
            },
            "spans": "as_steps",
            "rules": [
                {
                    "id": "background",
                    "category": "background",
                    "when": ["event=span.start"],
                }
            ],
            "outcome": {
                "invocation": [
                    {
                        "id": "span_error",
                        "value": "error",
                        "when": ["event=span.end", "status=error"],
                    }
                ],
                "episode": "aggregate",
            },
            "keep_attrs": ["span", "status", "duration_ms", "error", "error_type"],
        },
        source="builtin:generic",
    )


GENERIC_PROFILE: Profile = _build_generic_profile()
