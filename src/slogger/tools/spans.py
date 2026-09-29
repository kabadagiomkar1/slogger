"""Collect span events and selection bits without retaining ordinary logs."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any

from slogger.tools.trace import Trace, build_trace


class SpanCollector:
    """Buffer lifecycle events per group; evaluate selection during ingestion.

    ``groups_seen`` is a lower bound once ``groups_capped`` is true. Dropped
    identities are not retained, so a stream of unique groups stays bounded.
    """

    def __init__(
        self, *, keep_logs: bool, max_groups: int = 10_000,
        predicate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.keep_logs = keep_logs
        self.max_groups = max_groups
        self.groups_seen = 0
        self.groups_capped = False
        self._predicate = predicate
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        self._selected: set[str] = set()
        self._seen_spans: dict[str, set[str]] = {}

    def add(self, record: Mapping[str, Any], group_key: str) -> bool:
        if group_key not in self._buffers:
            if len(self._buffers) >= self.max_groups:
                self.groups_capped = True
                self.groups_seen = len(self._buffers) + 1
                return False
            self._buffers[group_key] = []
            self._seen_spans[group_key] = set()
            self.groups_seen = len(self._buffers)
        if self._predicate is None or self._predicate(record):
            self._selected.add(group_key)
        sid = record.get("span_id")
        new_span = isinstance(sid, str) and sid not in self._seen_spans[group_key]
        if isinstance(sid, str):
            self._seen_spans[group_key].add(sid)
        if self.keep_logs or record.get("event") in ("span.start", "span.end") or new_span:
            self._buffers[group_key].append(dict(record))
        return True

    def finish(self) -> Iterator[tuple[str, Trace]]:
        for group_key, buffered in self._buffers.items():
            if group_key not in self._selected:
                continue
            result = build_trace(buffered, None, keep_logs=self.keep_logs)
            result.trace_id = group_key
            yield group_key, result
