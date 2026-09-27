"""Select and reconstruct span trees from structured log records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from slogger.schema import SCHEMA_KEYS, SPAN_FIELD_ORDER
from slogger.tools.errors import ToolError
from slogger.tools.filters import Filters
from slogger.tools.reader import Order, Reader, Source, resolve_sources
from slogger.tools.render import render_console_line

_SPAN_META = frozenset(SPAN_FIELD_ORDER) | {"event", "_id"}
_EXCLUDED_FIELDS = SCHEMA_KEYS | _SPAN_META


@dataclass
class SpanNode:
    span: str | None
    span_id: str
    parent_span_id: str | None
    status: Literal["ok", "error", "unknown"]
    started: str | None
    ended: str | None
    duration_ms: float | None
    error_type: str | None
    error: str | None
    fields: dict[str, Any]
    logs: list[dict[str, Any]] = field(default_factory=list)
    children: list["SpanNode"] = field(default_factory=list)
    orphan: bool = False
    missing_start: bool = False
    _order: int = field(default=0, repr=False)


@dataclass
class Trace:
    trace_id: str
    status: str
    started: str | None
    ended: str | None
    duration_ms: float | None
    spans: list[SpanNode]
    logs: list[dict[str, Any]]
    warnings: list[str]
    matched_records: int | None = None
    matched_traces: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "trace_id": self.trace_id,
            "status": self.status,
            "started": self.started,
            "ended": self.ended,
            "duration_ms": self.duration_ms,
            "spans": [_span_to_dict(span) for span in self.spans],
            "logs": self.logs,
            "warnings": self.warnings,
            "matched_records": self.matched_records,
            "matched_traces": self.matched_traces,
        }


def _span_to_dict(span: SpanNode) -> dict[str, Any]:
    return {
        "span": span.span,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "status": span.status,
        "started": span.started,
        "ended": span.ended,
        "duration_ms": span.duration_ms,
        "error_type": span.error_type,
        "error": span.error,
        "fields": span.fields,
        "logs": span.logs,
        "children": [_span_to_dict(child) for child in span.children],
        "orphan": span.orphan,
        "missing_start": span.missing_start,
    }


def _context_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in _EXCLUDED_FIELDS}


def _sort_key(timestamp: str | None, order: int) -> tuple[str, int]:
    return (timestamp if timestamp is not None else "~", order)


def _new_node(
    record: Mapping[str, Any],
    span_id: str,
    *,
    order: int,
    missing_start: bool = False,
) -> SpanNode:
    return SpanNode(
        span=record.get("span") if isinstance(record.get("span"), str) else None,
        span_id=span_id,
        parent_span_id=(
            record.get("parent_span_id")
            if isinstance(record.get("parent_span_id"), str)
            else None
        ),
        status="unknown",
        started=None,
        ended=None,
        duration_ms=None,
        error_type=None,
        error=None,
        fields=_context_fields(record),
        missing_start=missing_start,
        _order=order,
    )


def build_trace(records: Iterable[Mapping[str, Any]], trace_id: str) -> Trace:
    nodes: dict[str, SpanNode] = {}
    warnings: list[str] = []
    trace_logs: list[tuple[tuple[str, int], dict[str, Any]]] = []
    order = 0

    for record in records:
        if record.get("trace_id") != trace_id:
            continue
        current = order
        order += 1
        event = record.get("event")
        span_id = record.get("span_id")
        timestamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None

        if event == "span.start" and isinstance(span_id, str):
            existing = nodes.get(span_id)
            if existing is not None and not existing.missing_start:
                warnings.append(f"duplicate_start:{span_id}")
                continue
            node = _new_node(record, span_id, order=existing._order if existing else current)
            node.started = timestamp
            node.missing_start = False
            if existing is not None:
                node.ended = existing.ended
                node.duration_ms = existing.duration_ms
                node.status = existing.status
                node.error_type = existing.error_type
                node.error = existing.error
                node.logs = existing.logs
                node.fields = {**existing.fields, **node.fields}
            nodes[span_id] = node
            continue

        if event == "span.end" and isinstance(span_id, str):
            node = nodes.get(span_id)
            if node is not None and node.ended is not None:
                warnings.append(f"duplicate_end:{span_id}")
                continue
            if node is None:
                node = _new_node(record, span_id, order=current, missing_start=True)
                nodes[span_id] = node
            node.ended = timestamp
            duration = record.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                node.duration_ms = float(duration)
            status = record.get("status")
            node.status = status if status in ("ok", "error") else "ok"
            if isinstance(record.get("error_type"), str):
                node.error_type = record["error_type"]
            if isinstance(record.get("error"), str):
                node.error = record["error"]
            node.fields = {**node.fields, **_context_fields(record)}
            if isinstance(record.get("span"), str):
                node.span = record["span"]
            if isinstance(record.get("parent_span_id"), str):
                node.parent_span_id = record["parent_span_id"]
            continue

        log_record = dict(record)
        if isinstance(span_id, str):
            node = nodes.get(span_id)
            if node is None:
                node = _new_node(record, span_id, order=current, missing_start=True)
                nodes[span_id] = node
            node.logs.append(log_record)
        else:
            trace_logs.append((_sort_key(timestamp, current), log_record))

    roots: list[SpanNode] = []
    for node in nodes.values():
        parent_id = node.parent_span_id
        if parent_id is None:
            roots.append(node)
            continue
        parent = nodes.get(parent_id)
        if parent is None:
            node.orphan = True
            warnings.append(f"missing_parent:{node.span_id}")
            roots.append(node)
        else:
            parent.children.append(node)

    def sort_tree(items: list[SpanNode]) -> None:
        items.sort(key=lambda item: _sort_key(item.started, item._order))
        for item in items:
            item.logs = [
                log
                for _, log in sorted(
                    enumerate(item.logs),
                    key=lambda pair: (
                        pair[1].get("timestamp")
                        if isinstance(pair[1].get("timestamp"), str)
                        else "~",
                        pair[0],
                    ),
                )
            ]
            sort_tree(item.children)

    sort_tree(roots)
    trace_logs.sort(key=lambda item: item[0])
    logs = [item[1] for item in trace_logs]

    if any(node.status == "error" for node in nodes.values()):
        status = "error"
    elif any(node.status == "unknown" for node in roots):
        status = "unknown"
    else:
        status = "ok"

    started_candidates = [node.started for node in roots if node.started is not None]
    ended_candidates = [node.ended for node in roots if node.ended is not None]
    started = min(started_candidates) if started_candidates else None
    ended = max(ended_candidates) if ended_candidates else None
    if len(roots) == 1 and roots[0].duration_ms is not None:
        duration_ms = roots[0].duration_ms
    else:
        duration_ms = None

    return Trace(
        trace_id=trace_id,
        status=status,
        started=started,
        ended=ended,
        duration_ms=duration_ms,
        spans=roots,
        logs=logs,
        warnings=warnings,
    )


def find_trace_id(
    sources: Source | Sequence[Source],
    *,
    prefix: str | None = None,
    filters: Filters | None = None,
    order: Order = "concat",
) -> tuple[str, int, int]:
    if prefix is not None and len(prefix) < 4:
        raise ValueError("trace id prefix must be at least 4 characters")

    predicate = filters if filters is not None else Filters()
    matched_records = 0
    matched_traces: set[str] = set()
    first_trace: str | None = None
    candidates: set[str] = set()

    for record in Reader(sources, order=order):
        trace_id = record.get("trace_id")
        if prefix is not None:
            if isinstance(trace_id, str) and trace_id.startswith(prefix):
                candidates.add(trace_id)
            continue
        if not predicate.matches(record):
            continue
        matched_records += 1
        if isinstance(trace_id, str):
            matched_traces.add(trace_id)
            if first_trace is None:
                first_trace = trace_id

    if prefix is not None:
        if not candidates:
            raise ToolError("trace_not_found", f"no trace matching prefix {prefix!r}")
        if len(candidates) > 1:
            raise ToolError(
                "ambiguous_trace",
                f"prefix {prefix!r} matches {len(candidates)} traces",
                candidates=sorted(candidates)[:10],
            )
        return next(iter(candidates)), 0, 1

    if matched_records == 0:
        raise ToolError("trace_not_found", "no records matched the filter")
    if first_trace is None:
        raise ToolError("no_trace_on_match", "first matching record has no trace_id")
    return first_trace, matched_records, len(matched_traces)


def trace(
    sources: Source | Sequence[Source],
    *,
    trace_id: str | None = None,
    filters: Filters | None = None,
    order: Order = "concat",
) -> Trace:
    # Materialise once so generators survive the find + collect passes.
    resolved = resolve_sources(sources)
    if trace_id is not None:
        selected, _, _ = find_trace_id(resolved, prefix=trace_id, order=order)
        matched_records = None
        matched_traces = None
    else:
        selected, matched_records, matched_traces = find_trace_id(
            resolved, filters=filters, order=order
        )

    records = [
        record
        for record in Reader(resolved, order=order)
        if record.get("trace_id") == selected
    ]
    result = build_trace(records, selected)
    result.matched_records = matched_records
    result.matched_traces = matched_traces
    return result


def render_trace(tr: Trace, *, color: bool, logs: bool = True) -> str:
    total = f"{tr.duration_ms:g} ms" if tr.duration_ms is not None else "?"
    started = tr.started or "-"
    lines = [
        f"trace {tr.trace_id}  {started}  total {total}  status={tr.status}",
        "",
    ]

    def format_span(node: SpanNode, indent: str, is_last: bool, is_root: bool) -> None:
        duration = f"{node.duration_ms:g} ms" if node.duration_ms is not None else "?"
        name = node.span or node.span_id
        extras = [f"{key}={value}" for key, value in node.fields.items()]
        if node.orphan:
            extras.append("(orphan)")
        extra = ("  " + " ".join(extras)) if extras else ""
        if is_root:
            lines.append(f"{name:<44} {node.status:<7} {duration:>8}{extra}")
            child_indent = ""
        else:
            branch = "└─ " if is_last else "├─ "
            lines.append(
                f"{indent}{branch}{name:<40} {node.status:<7} {duration:>8}{extra}"
            )
            child_indent = indent + ("   " if is_last else "│  ")

        items: list[tuple[str, object, tuple[str, int]]] = []
        if logs:
            for index, log in enumerate(node.logs):
                ts = log.get("timestamp") if isinstance(log.get("timestamp"), str) else "~"
                items.append(("log", log, (ts, index)))
        for index, child in enumerate(node.children):
            items.append(("span", child, _sort_key(child.started, child._order + index)))
        items.sort(key=lambda item: item[2])

        for index, (kind, value, _) in enumerate(items):
            last = index == len(items) - 1
            if kind == "span":
                assert isinstance(value, SpanNode)
                format_span(value, child_indent if not is_root else "", last, False)
            else:
                assert isinstance(value, dict)
                branch = "└─ " if last else "├─ "
                rendered = render_console_line(value, color=color)
                prefix = child_indent if not is_root else ""
                lines.append(f"{prefix}{branch}{rendered}")

    for index, root in enumerate(tr.spans):
        format_span(root, "", index == len(tr.spans) - 1, True)
    if tr.logs and logs:
        lines.append("")
        for log in tr.logs:
            lines.append(render_console_line(log, color=color))
    return "\n".join(lines)
