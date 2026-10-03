"""Read and query structured log files produced by slogger.

This package provides the Python API for inspecting structured log files. Import public
names from here (not from :mod:`slogger`)::

    from slogger.tools import Field, Filters, meta, query, trace

    info = meta("app.log")
    page = query(
        "app.log",
        filters=Filters(level_min=40, predicate=Field("order_id").in_(["42", "43"])),
        limit=50,
    )

Sources may be a path, a glob, a sequence of those, ``"-"`` (stdin), or an
in-memory iterable of dicts. See ``docs/api.md`` and ``docs/cli.md``.
"""

from slogger.tools.context import context
from slogger.tools.diff import diff
from slogger.tools.errors import CursorError, ToolError
from slogger.tools.failures import failures
from slogger.tools.fields import fields
from slogger.tools.filters import Filters, Where, level_number, parse_where
from slogger.tools.grouping import group_value, parse_group_selector
from slogger.tools.meta import meta
from slogger.tools.output_schema import ToolOutputKind, output_schemas, validate_tool_output
from slogger.tools.plan import PlanResult, QueryPlan, scan
from slogger.tools.predicates import Field, Predicate, all_of, any_of, logger_prefix, not_
from slogger.tools.query import Page, query, summary
from slogger.tools.reader import (
    Order,
    Reader,
    parse_id,
    parse_timestamp,
    resolve_sources,
)
from slogger.tools.render import (
    project,
    render_console_line,
    render_json_line,
    render_table,
)
from slogger.tools.spans import SpanCollector
from slogger.tools.stats import percentile, stats
from slogger.tools.tail import follow, tail_once
from slogger.tools.timeparse import parse_bucket, parse_duration_ms
from slogger.tools.trace import SpanNode, Trace, build_trace, render_trace, trace
from slogger.tools.tree import tree
from slogger.tools.validate import validate
from slogger.tools.watch import WatchResult, watch

__all__ = [
    "AggregateSpec",
    "GroupedPlan",
    "count_rows",
    "sum_of",
    "mean_of",
    "min_of",
    "max_of",
    "CursorError",
    "Field",
    "Filters",
    "Order",
    "Page",
    "Predicate",
    "PlanResult",
    "QueryPlan",
    "Reader",
    "SpanCollector",
    "SpanNode",
    "ToolError",
    "ToolOutputKind",
    "Trace",
    "WatchResult",
    "Where",
    "all_of",
    "any_of",
    "build_trace",
    "context",
    "diff",
    "failures",
    "fields",
    "follow",
    "group_value",
    "level_number",
    "logger_prefix",
    "meta",
    "not_",
    "output_schemas",
    "parse_bucket",
    "parse_duration_ms",
    "parse_group_selector",
    "parse_id",
    "parse_timestamp",
    "parse_where",
    "percentile",
    "project",
    "query",
    "render_console_line",
    "render_json_line",
    "render_table",
    "render_trace",
    "resolve_sources",
    "scan",
    "stats",
    "summary",
    "tail_once",
    "trace",
    "tree",
    "validate",
    "validate_tool_output",
    "watch",
]

from .plan import AggregateSpec, GroupedPlan, count_rows, max_of, mean_of, min_of, sum_of
