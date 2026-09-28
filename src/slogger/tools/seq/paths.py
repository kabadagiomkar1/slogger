"""Path tokens and fingerprints for sequence episodes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from slogger.tools.filters import Filters
from slogger.tools.reader import Order
from slogger.tools.seq.episodes import extract_episodes
from slogger.tools.seq.model import FINGERPRINT_VERSION, Episode, RecordRef
from slogger.tools.seq.profile import Profile

_APP_TOKEN_CATEGORIES = frozenset({"step", "observation", "error", "abort"})


def path_tokens(ep: Episode, granularity: str) -> list[str]:
    """Return ordered path tokens for ``ep`` at ``granularity``.

    ``granularity`` is ``app``, ``span``, or a span role name (e.g. ``api``).
    """
    if granularity == "span":
        tokens: list[str] = []
        for event in ep.events:
            if event.rule == "spans" and event.token:
                tokens.append(event.token)
            elif (
                event.category == "span_event"
                and event.attrs.get("event") == "span.end"
                and event.attrs.get("span") is not None
            ):
                tokens.append(str(event.attrs["span"]))
        return tokens

    if granularity != "app":
        return [span.name for span in ep.spans if span.role == granularity and span.name]

    tokens = []
    for event in ep.events:
        if event.category == "span_open" and event.token:
            tokens.append(event.token)
        elif event.category in _APP_TOKEN_CATEGORIES and event.token:
            tokens.append(event.token)
    return tokens


def fingerprint(
    profile: Profile,
    granularity: str,
    tokens: Sequence[str],
    *,
    collapsed: bool = False,
) -> str:
    """Return the first 16 hex chars of the path fingerprint hash."""
    payload: list[Any]
    if collapsed:
        payload = [
            FINGERPRINT_VERSION,
            profile.name,
            profile.profile_version,
            granularity,
            list(tokens),
            True,
        ]
    else:
        payload = [
            FINGERPRINT_VERSION,
            profile.name,
            profile.profile_version,
            granularity,
            list(tokens),
        ]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def collapse(
    tokens: Sequence[str], refs: Sequence[RecordRef]
) -> list[dict[str, Any]]:
    """Merge adjacent equal tokens; non-adjacent repeats stay separate."""
    if len(tokens) != len(refs):
        raise ValueError("tokens and refs must have the same length")
    if not tokens:
        return []
    groups: list[dict[str, Any]] = []
    current_token = tokens[0]
    current_refs = [refs[0]]
    for token, ref in zip(tokens[1:], refs[1:], strict=True):
        if token == current_token:
            current_refs.append(ref)
        else:
            groups.append(
                {
                    "token": current_token,
                    "count": len(current_refs),
                    "refs": list(current_refs),
                }
            )
            current_token = token
            current_refs = [ref]
    groups.append(
        {
            "token": current_token,
            "count": len(current_refs),
            "refs": list(current_refs),
        }
    )
    return groups


def _token_refs(ep: Episode, granularity: str) -> list[RecordRef]:
    """Refs parallel to :func:`path_tokens` for collapse."""
    if granularity == "span":
        refs: list[RecordRef] = []
        for event in ep.events:
            if event.rule == "spans" and event.token:
                refs.append(event.ref)
            elif (
                event.category == "span_event"
                and event.attrs.get("event") == "span.end"
                and event.attrs.get("span") is not None
            ):
                refs.append(event.ref)
        return refs
    if granularity != "app":
        refs = []
        for span in ep.spans:
            if span.role != granularity or not span.name:
                continue
            if span.start is not None:
                refs.append(span.start)
            elif span.events:
                refs.append(ep.events[span.events[0]].ref)
        return refs
    refs = []
    for event in ep.events:
        if event.category == "span_open" and event.token:
            refs.append(event.ref)
        elif event.category in _APP_TOKEN_CATEGORIES and event.token:
            refs.append(event.ref)
    return refs


def paths(
    sources: Any,
    *,
    profile: Profile,
    granularity: str = "app",
    collapse_repeats: bool = False,
    filters: Filters | None = None,
    episode_keys: Sequence[str] = (),
    outcomes: Sequence[str] = (),
    completion: str | None = None,
    variant: str | None = None,
    order: Order = "concat",
    after: str | None = None,
    top: int | None = 50,
    show_background: bool = False,
) -> dict[str, Any]:
    """Group episodes by path fingerprint."""
    result = extract_episodes(
        sources,
        profile=profile,
        filters=filters,
        episode_keys=episode_keys,
        outcomes=outcomes,
        completion=completion,
        variant=variant,
        order=order,
        after=after,
        top=top,
    )
    groups: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []

    for ep in result.episodes:
        tokens = path_tokens(ep, granularity)
        fp = fingerprint(profile, granularity, tokens)
        if fp not in groups:
            group_order.append(fp)
            entry: dict[str, Any] = {
                "fingerprint": fp,
                "tokens": tokens,
                "episodes": [],
                "outcomes": Counter(),
                "completion": Counter(),
                "background_refs": [],
            }
            if collapse_repeats:
                refs = _token_refs(ep, granularity)
                collapsed_rows = collapse(tokens, refs)
                entry["collapsed_tokens"] = [
                    {
                        "token": row["token"],
                        "count": row["count"],
                        "refs": [
                            {
                                "id": r.id,
                                "timestamp": r.timestamp,
                                "source_line": r.source_line,
                            }
                            for r in row["refs"]
                        ],
                    }
                    for row in collapsed_rows
                ]
                entry["collapsed_fingerprint"] = fingerprint(
                    profile,
                    granularity,
                    [row["token"] for row in collapsed_rows],
                    collapsed=True,
                )
            groups[fp] = entry

        group = groups[fp]
        group["episodes"].append(ep.key)
        group["outcomes"][ep.outcome.value] += 1
        group["completion"][ep.completion] += 1
        if show_background:
            for event in ep.events:
                if event.category == "background":
                    group["background_refs"].append(
                        {
                            "id": event.ref.id,
                            "timestamp": event.ref.timestamp,
                            "source_line": event.ref.source_line,
                            "episode_key": ep.key,
                        }
                    )

    path_groups = []
    for fp in group_order:
        group = groups[fp]
        item: dict[str, Any] = {
            "fingerprint": group["fingerprint"],
            "tokens": group["tokens"],
            "episodes": group["episodes"],
            "outcomes": dict(group["outcomes"]),
            "completion": dict(group["completion"]),
        }
        if show_background:
            item["background_refs"] = group["background_refs"]
        if collapse_repeats:
            item["collapsed_tokens"] = group["collapsed_tokens"]
            item["collapsed_fingerprint"] = group["collapsed_fingerprint"]
        path_groups.append(item)

    return {
        "schema_version": 1,
        "profile": {
            "name": profile.name,
            "profile_version": profile.profile_version,
            "source": profile.source,
        },
        "granularity": granularity,
        "fingerprint_version": FINGERPRINT_VERSION,
        "order": order,
        "order_basis": "reading",
        "paths": path_groups,
        "total": result.total,
        "returned": result.returned,
        "truncated": result.truncated,
        "warnings": result.warnings,
    }
