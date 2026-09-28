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

_ALLOWED_TOP_LEVEL_V1 = frozenset(
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
_ALLOWED_TOP_LEVEL_V2 = frozenset(
    {
        "schema_version",
        "name",
        "profile_version",
        "episode",
        "variant_key",
        "occurrence_key",
        "spans",
        "span_events",
        "rules",
        "outcome",
        "links",
        "keep_attrs",
        "path",
    }
)

SpansMode = Literal["default", "as_steps"]
BoundsKind = Literal["group", "pair", "interval"]


@dataclass(frozen=True)
class SpanRoleSpec:
    """One nestable span role declared by the profile.

    ``parent`` is the role name this opens under (``None`` for the root).
    Nesting follows these pointers, not timestamp containment.
    """

    role: str
    parent: str | None
    bounds: BoundsKind
    name: str | None = None
    start: tuple[Where, ...] = ()
    end: tuple[Where, ...] = ()
    when: tuple[Where, ...] = ()
    token: str | None = None
    end_attr: str | None = None
    incomplete_when: tuple[Where, ...] = ()


@dataclass(frozen=True)
class Rule:
    id: str
    category: Category
    when: tuple[Where, ...]
    token: str | None = None
    token_suffix: str | None = None
    on: str | None = None


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
class CompleteWhenNames:
    """Episode is complete when every ``names`` entry exists as a complete span of ``role``."""

    role: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class CompleteWhenEnd:
    """Episode is complete when an episode-end record was seen."""

    pass


CompleteWhen = CompleteWhenNames | CompleteWhenEnd | None


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
    span_roles: tuple[SpanRoleSpec, ...]
    span_event_mode: SpansMode
    outcome_span_role: str | None
    rules: tuple[Rule, ...]
    outcome_rules: tuple[OutcomeRule, ...]
    outcome_episode: EpisodeOutcomeSpec
    links_recovery_of: str | None
    links_triggered_recovery: str | None
    keep_attrs: tuple[str, ...]
    path_app: tuple[str, ...]
    source: str

    @property
    def spans(self) -> SpansMode:
        """Compatibility alias for ``span_event_mode`` (schema v1 ``spans`` string)."""
        return self.span_event_mode


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


def _parse_complete_when_v2(raw: object, span_roles: tuple[SpanRoleSpec, ...]) -> CompleteWhen:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("episode.complete_when: expected object")
    if raw.get("end") is True:
        extra = set(raw) - {"end"}
        if extra:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(extra)}")
        return CompleteWhenEnd()
    if "role" in raw or "names" in raw:
        allowed = {"role", "names"}
        unknown = set(raw) - allowed
        if unknown:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(unknown)}")
        role = raw.get("role")
        if not isinstance(role, str) or not role:
            raise _invalid("episode.complete_when.role: expected non-empty string")
        if not any(spec.role == role for spec in span_roles):
            raise _invalid(f"episode.complete_when.role: unknown role {role!r}")
        names = _parse_str_list(raw.get("names"), context="episode.complete_when.names")
        if not names:
            raise _invalid("episode.complete_when.names: must be non-empty")
        return CompleteWhenNames(role=role, names=names)
    raise _invalid("episode.complete_when: need {role, names} or end:true")


def _parse_complete_when_v1(raw: object) -> CompleteWhen:
    """Schema v1: ``invocations`` list compiles to role ``api``."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("episode.complete_when: expected object")
    if "invocations" in raw:
        names = _parse_str_list(
            raw["invocations"], context="episode.complete_when.invocations"
        )
        if not names:
            raise _invalid("episode.complete_when.invocations: must be non-empty")
        extra = set(raw) - {"invocations"}
        if extra:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(extra)}")
        return CompleteWhenNames(role="api", names=names)
    if raw.get("end") is True:
        extra = set(raw) - {"end"}
        if extra:
            raise _invalid(f"episode.complete_when: unknown keys {sorted(extra)}")
        return CompleteWhenEnd()
    raise _invalid("episode.complete_when: need invocations or end:true")


def _parse_rules(raw: object, *, allow_on: bool) -> tuple[Rule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid("rules: expected list")
    seen: set[str] = set()
    rules: list[Rule] = []
    allowed = {"id", "category", "when", "token", "token_suffix"}
    if allow_on:
        allowed = allowed | {"on"}
    for index, item in enumerate(raw):
        context = f"rules[{index}]"
        if not isinstance(item, dict):
            raise _invalid(f"{context}: expected object")
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
        on = item.get("on")
        if on is not None and not isinstance(on, str):
            raise _invalid(f"{context}: on must be a string role name")
        rules.append(
            Rule(
                id=rule_id,
                category=category,  # type: ignore[arg-type]
                when=_parse_when_list(item.get("when", []), context=f"{context}.when"),
                token=token,
                token_suffix=token_suffix,
                on=on,
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


def _parse_episode_block_keys(raw: object) -> dict[str, Any]:
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
        "complete_when_raw": raw.get("complete_when"),
    }


def _parse_span_event_mode(raw: object, *, context: str) -> SpansMode:
    if raw is None:
        return "default"
    if raw in ("default", "as_steps"):
        return raw  # type: ignore[return-value]
    raise _invalid(f"{context}: unsupported {raw!r}")


def _parse_span_roles(raw: object) -> tuple[SpanRoleSpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise _invalid("spans: expected a non-empty list of span role objects")
    roles: list[SpanRoleSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        context = f"spans[{index}]"
        if not isinstance(item, dict):
            raise _invalid(f"{context}: expected object")
        allowed = {
            "role",
            "parent",
            "bounds",
            "name",
            "start",
            "end",
            "when",
            "token",
            "end_attr",
            "incomplete_when",
        }
        unknown = set(item) - allowed
        if unknown:
            raise _invalid(f"{context}: unknown keys {sorted(unknown)}")
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise _invalid(f"{context}: role must be a non-empty string")
        if role in seen:
            raise _invalid(f"duplicate span role: {role!r}")
        seen.add(role)
        parent = item.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise _invalid(f"{context}: parent must be a string or null")
        bounds = item.get("bounds")
        if bounds not in {"group", "pair", "interval"}:
            raise _invalid(f"{context}: bounds must be group|pair|interval")
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise _invalid(f"{context}: name must be a string")
        token = item.get("token")
        if token is not None and not isinstance(token, str):
            raise _invalid(f"{context}: token must be a string")
        end_attr = item.get("end_attr")
        if end_attr is not None and not isinstance(end_attr, str):
            raise _invalid(f"{context}: end_attr must be a string")
        start = _parse_when_list(item.get("start", []), context=f"{context}.start")
        end = _parse_when_list(item.get("end", []), context=f"{context}.end")
        when = _parse_when_list(item.get("when", []), context=f"{context}.when")
        incomplete_when = _parse_when_list(
            item.get("incomplete_when", []), context=f"{context}.incomplete_when"
        )
        if bounds == "group":
            if parent is not None:
                raise _invalid(f"{context}: group root parent must be null")
            if index != 0:
                raise _invalid(f"{context}: group root must be the first spans entry")
        if bounds == "pair":
            if not start or not end:
                raise _invalid(f"{context}: pair bounds require start and end")
            if parent is None:
                raise _invalid(f"{context}: pair bounds require a parent role")
        if bounds == "interval":
            if not when:
                raise _invalid(f"{context}: interval bounds require when")
            if parent is None:
                raise _invalid(f"{context}: interval bounds require a parent role")
        roles.append(
            SpanRoleSpec(
                role=role,
                parent=parent,
                bounds=bounds,  # type: ignore[arg-type]
                name=name,
                start=start,
                end=end,
                when=when,
                token=token,
                end_attr=end_attr,
                incomplete_when=incomplete_when,
            )
        )
    role_names = {spec.role for spec in roles}
    for spec in roles:
        if spec.parent is not None and spec.parent not in role_names:
            raise _invalid(
                f"spans: parent {spec.parent!r} of role {spec.role!r} is not defined"
            )
    roots = [spec for spec in roles if spec.parent is None]
    if len(roots) != 1 or roots[0].bounds != "group":
        raise _invalid("spans: exactly one group root with parent null is required")
    return tuple(roles)


def _compile_v1_span_roles(invocation_raw: object) -> tuple[SpanRoleSpec, ...]:
    root = SpanRoleSpec(role="episode", parent=None, bounds="group")
    if invocation_raw is None:
        return (root,)
    if not isinstance(invocation_raw, dict):
        raise _invalid("invocation: expected object")
    allowed = {"name", "start", "end", "outcome_window"}
    unknown = set(invocation_raw) - allowed
    if unknown:
        raise _invalid(f"invocation: unknown keys {sorted(unknown)}")
    name = invocation_raw.get("name")
    if name is not None and not isinstance(name, str):
        raise _invalid("invocation.name: expected string")
    window = invocation_raw.get("outcome_window", "same_name_nearest")
    if window != "same_name_nearest":
        raise _invalid(f"invocation.outcome_window: unsupported {window!r}")
    api = SpanRoleSpec(
        role="api",
        parent="episode",
        bounds="pair",
        name=name,
        start=_parse_when_list(invocation_raw.get("start", []), context="invocation.start"),
        end=_parse_when_list(invocation_raw.get("end", []), context="invocation.end"),
    )
    return (root, api)


def _parse_path_app(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise _invalid("path: expected object")
    allowed = {"app"}
    unknown = set(raw) - allowed
    if unknown:
        raise _invalid(f"path: unknown keys {sorted(unknown)}")
    return _parse_str_list(raw.get("app", []), context="path.app")


def _parse_outcome_v2(
    outcome_raw: object, span_roles: tuple[SpanRoleSpec, ...]
) -> tuple[tuple[OutcomeRule, ...], str | None, EpisodeOutcomeSpec]:
    if outcome_raw is None:
        return (), None, EpisodeOutcomeAggregate()
    if not isinstance(outcome_raw, dict):
        raise _invalid("outcome: expected object")
    allowed = {"span_role", "rules", "episode"}
    unknown = set(outcome_raw) - allowed
    if unknown:
        raise _invalid(f"outcome: unknown keys {sorted(unknown)}")
    span_role = outcome_raw.get("span_role")
    if span_role is not None and not isinstance(span_role, str):
        raise _invalid("outcome.span_role: expected string or null")
    if span_role is not None and not any(spec.role == span_role for spec in span_roles):
        raise _invalid(f"outcome.span_role: unknown role {span_role!r}")
    rules = _parse_outcome_rules(outcome_raw.get("rules"), context="outcome.rules")
    episode = _parse_outcome_episode(outcome_raw.get("episode"))
    return rules, span_role, episode


def _parse_outcome_v1(
    outcome_raw: object, has_api_role: bool
) -> tuple[tuple[OutcomeRule, ...], str | None, EpisodeOutcomeSpec]:
    if outcome_raw is None:
        return (), ("api" if has_api_role else None), EpisodeOutcomeAggregate()
    if not isinstance(outcome_raw, dict):
        raise _invalid("outcome: expected object")
    allowed = {"invocation", "episode"}
    unknown = set(outcome_raw) - allowed
    if unknown:
        raise _invalid(f"outcome: unknown keys {sorted(unknown)}")
    rules = _parse_outcome_rules(
        outcome_raw.get("invocation"), context="outcome.invocation"
    )
    episode = _parse_outcome_episode(outcome_raw.get("episode"))
    return rules, ("api" if has_api_role else None), episode


def profile_from_dict(data: Mapping[str, Any], *, source: str) -> Profile:
    """Validate a profile mapping and return a :class:`Profile`."""
    if not isinstance(data, Mapping):
        raise _invalid("profile root must be an object")

    schema_version = data.get("schema_version")
    if schema_version == 1:
        return _profile_from_v1(data, source=source)
    if schema_version == 2:
        return _profile_from_v2(data, source=source)
    raise _invalid(f"unsupported schema_version: {schema_version!r}")


def _common_header(data: Mapping[str, Any]) -> tuple[str, str, str | None, tuple[str, ...]]:
    name = data.get("name", "unnamed")
    if not isinstance(name, str) or not name:
        raise _invalid("name: expected non-empty string")
    profile_version = data.get("profile_version", "1")
    if not isinstance(profile_version, str):
        raise _invalid("profile_version: expected string")
    variant_key = data.get("variant_key")
    if variant_key is not None and not isinstance(variant_key, str):
        raise _invalid("variant_key: expected string or null")
    occurrence_key = _parse_str_list(
        data.get("occurrence_key", []), context="occurrence_key"
    )
    return name, profile_version, variant_key, occurrence_key


def _profile_from_v1(data: Mapping[str, Any], *, source: str) -> Profile:
    unknown = set(data) - _ALLOWED_TOP_LEVEL_V1
    if unknown:
        raise _invalid(f"unknown top-level keys: {sorted(unknown)}", keys=sorted(unknown))
    name, profile_version, variant_key, occurrence_key = _common_header(data)
    if "episode" not in data:
        raise _invalid("episode: required")
    episode = _parse_episode_block_keys(data["episode"])
    span_roles = _compile_v1_span_roles(data.get("invocation"))
    complete_when = _parse_complete_when_v1(episode["complete_when_raw"])
    if isinstance(complete_when, CompleteWhenNames):
        if not any(spec.role == complete_when.role for spec in span_roles):
            raise _invalid(
                "episode.complete_when.invocations requires an invocation block "
                "(compiles to span role 'api')"
            )
    span_event_mode = _parse_span_event_mode(data.get("spans", "default"), context="spans")
    keep_attrs = _parse_str_list(data.get("keep_attrs", []), context="keep_attrs")
    has_api = any(spec.role == "api" for spec in span_roles)
    outcome_rules, outcome_span_role, outcome_episode = _parse_outcome_v1(
        data.get("outcome"), has_api
    )
    recovery_of, triggered = _parse_links(data.get("links"))
    rules = _parse_rules(data.get("rules"), allow_on=False)
    return Profile(
        name=name,
        profile_version=profile_version,
        episode_key=episode["episode_key"],
        fallback_keys=episode["fallback_keys"],
        episode_start=episode["episode_start"],
        episode_end=episode["episode_end"],
        complete_when=complete_when,
        variant_key=variant_key,
        occurrence_key=occurrence_key,
        span_roles=span_roles,
        span_event_mode=span_event_mode,
        outcome_span_role=outcome_span_role,
        rules=rules,
        outcome_rules=outcome_rules,
        outcome_episode=outcome_episode,
        links_recovery_of=recovery_of,
        links_triggered_recovery=triggered,
        keep_attrs=keep_attrs,
        path_app=(),
        source=source,
    )


def _profile_from_v2(data: Mapping[str, Any], *, source: str) -> Profile:
    unknown = set(data) - _ALLOWED_TOP_LEVEL_V2
    if unknown:
        raise _invalid(f"unknown top-level keys: {sorted(unknown)}", keys=sorted(unknown))
    name, profile_version, variant_key, occurrence_key = _common_header(data)
    if "episode" not in data:
        raise _invalid("episode: required")
    episode = _parse_episode_block_keys(data["episode"])
    if "spans" not in data:
        raise _invalid("spans: required for schema_version 2")
    span_roles = _parse_span_roles(data["spans"])
    complete_when = _parse_complete_when_v2(episode["complete_when_raw"], span_roles)
    span_event_mode = _parse_span_event_mode(
        data.get("span_events", "default"), context="span_events"
    )
    rules = _parse_rules(data.get("rules"), allow_on=True)
    role_names = {spec.role for spec in span_roles}
    for rule in rules:
        if rule.on is not None and rule.on not in role_names:
            raise _invalid(f"rules: on {rule.on!r} is not a defined span role")
    keep_attrs = _parse_str_list(data.get("keep_attrs", []), context="keep_attrs")
    outcome_rules, outcome_span_role, outcome_episode = _parse_outcome_v2(
        data.get("outcome"), span_roles
    )
    recovery_of, triggered = _parse_links(data.get("links"))
    path_app = _parse_path_app(data.get("path"))
    for role in path_app:
        if role not in role_names:
            raise _invalid(f"path.app: unknown role {role!r}")
    return Profile(
        name=name,
        profile_version=profile_version,
        episode_key=episode["episode_key"],
        fallback_keys=episode["fallback_keys"],
        episode_start=episode["episode_start"],
        episode_end=episode["episode_end"],
        complete_when=complete_when,
        variant_key=variant_key,
        occurrence_key=occurrence_key,
        span_roles=span_roles,
        span_event_mode=span_event_mode,
        outcome_span_role=outcome_span_role,
        rules=rules,
        outcome_rules=outcome_rules,
        outcome_episode=outcome_episode,
        links_recovery_of=recovery_of,
        links_triggered_recovery=triggered,
        keep_attrs=keep_attrs,
        path_app=path_app,
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


def role_by_name(profile: Profile) -> dict[str, SpanRoleSpec]:
    return {spec.role: spec for spec in profile.span_roles}


def pair_roles(profile: Profile) -> tuple[SpanRoleSpec, ...]:
    return tuple(spec for spec in profile.span_roles if spec.bounds == "pair")


def classify(
    profile: Profile, record: Mapping[str, Any]
) -> tuple[Category, str | None, str | None]:
    """Classify ``record`` under ``profile``. First matching rule wins."""
    event = record.get("event")
    if event in ("span.start", "span.end"):
        if profile.span_event_mode == "as_steps":
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

    for spec in pair_roles(profile):
        if spec.start and _rule_matches(spec.start, record):
            token = (
                _token_for(record, category="span_open", token_field=spec.name)
                if spec.name
                else None
            )
            return ("span_open", token, f"span_open:{spec.role}")
        if spec.end and _rule_matches(spec.end, record):
            token = (
                _token_for(record, category="span_close", token_field=spec.name)
                if spec.name
                else None
            )
            return ("span_close", token, f"span_close:{spec.role}")

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
