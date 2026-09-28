"""Stream span events into per-group traces."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from slogger.tools.trace import Trace, build_trace

_SPAN_EVENTS = frozenset({"span.start", "span.end"})


@dataclass
class SpanCollector:
    """Buffer span events (and optional logs) per group key, then build traces."""

    keep_logs: bool
    max_groups: int = 10_000
    groups_seen: int = 0
    groups_capped: bool = False
    _buffers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _select_only: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)
    _skipped: set[str] = field(default_factory=set)

    def __init__(self, *, keep_logs: bool, max_groups: int = 10_000) -> None:
        self.keep_logs = keep_logs
        self.max_groups = max_groups
        self.groups_seen = 0
        self.groups_capped = False
        self._buffers = {}
        self._select_only = {}
        self._order = []
        self._skipped = set()

    def add(self, record: Mapping[str, Any], group_key: str) -> None:
        if group_key in self._skipped:
            return
        if group_key not in self._buffers:
            self.groups_seen += 1
            if len(self._buffers) >= self.max_groups:
                self.groups_capped = True
                self._skipped.add(group_key)
                return
            self._buffers[group_key] = []
            self._select_only[group_key] = []
            self._order.append(group_key)

        event = record.get("event")
        is_event = event in _SPAN_EVENTS
        copied = dict(record)
        if is_event or self.keep_logs:
            self._buffers[group_key].append(copied)
        else:
            # Held only until finish() decides selection; never enter Trace.logs.
            self._select_only[group_key].append(copied)

    def finish(
        self,
        predicate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> Iterator[tuple[str, Trace]]:
        """Yield ``(group_key, Trace)`` for groups that pass ``predicate``.

        When ``predicate`` is omitted every tracked group is selected. ``trace_id``
        on each :class:`Trace` is the group key (callers rewrite for ``--group-by``).
        """
        select = predicate if predicate is not None else (lambda _record: True)
        for group_key in self._order:
            buffered = self._buffers[group_key]
            extras = self._select_only.get(group_key, [])
            if not any(select(record) for record in buffered) and not any(
                select(record) for record in extras
            ):
                continue
            # Records are already grouped; the key need not be a trace_id.
            result = build_trace(buffered, None, keep_logs=self.keep_logs)
            result.trace_id = group_key
            yield group_key, result
        # Drop selection-only buffers promptly.
        self._select_only.clear()
