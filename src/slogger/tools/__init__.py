"""Read and query structured log files produced by slogger."""

from slogger.tools.context import context
from slogger.tools.diff import diff
from slogger.tools.errors import CursorError, ToolError
from slogger.tools.failures import failures
from slogger.tools.fields import fields
from slogger.tools.filters import Filters, Where, level_number, parse_where
from slogger.tools.grouping import group_value, parse_group_selector
from slogger.tools.meta import meta
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
from slogger.tools.seq import (
    FINGERPRINT_VERSION,
    GENERIC_PROFILE,
    Duration,
    Episode,
    EpisodesResult,
    Invocation,
    Links,
    Outcome,
    Profile,
    RecordRef,
    SeqEvent,
    Span,
    classify,
    collapse,
    episode_summary,
    extract_episodes,
    fingerprint,
    get_episode,
    load_profile,
    path_tokens,
    paths,
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
    "CursorError",
    "Duration",
    "Episode",
    "EpisodesResult",
    "FINGERPRINT_VERSION",
    "Filters",
    "GENERIC_PROFILE",
    "Invocation",
    "Links",
    "Order",
    "Outcome",
    "Page",
    "Profile",
    "Reader",
    "RecordRef",
    "SeqEvent",
    "Span",
    "SpanCollector",
    "SpanNode",
    "ToolError",
    "Trace",
    "WatchResult",
    "Where",
    "build_trace",
    "classify",
    "collapse",
    "context",
    "diff",
    "episode_summary",
    "extract_episodes",
    "failures",
    "fields",
    "fingerprint",
    "follow",
    "get_episode",
    "group_value",
    "level_number",
    "load_profile",
    "meta",
    "path_tokens",
    "paths",
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
    "stats",
    "summary",
    "tail_once",
    "trace",
    "tree",
    "validate",
    "watch",
]
