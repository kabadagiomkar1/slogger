"""Command-line interface for reading slogger JSONL files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from typing import TextIO

from slogger.tools.errors import CursorError, ToolError
from slogger.tools.fields import fields as fields_fn
from slogger.tools.filters import (
    Filters,
    level_number,
    parse_relative_or_iso,
    parse_where,
)
from slogger.tools.grouping import parse_group_selector
from slogger.tools.meta import meta as meta_fn
from slogger.tools.query import query
from slogger.tools.query import summary as summary_fn
from slogger.tools.render import render_console_line, render_json_line, render_table, use_color
from slogger.tools.stats import stats as stats_fn
from slogger.tools.tail import follow, tail_once
from slogger.tools.timeparse import parse_bucket, parse_duration_ms
from slogger.tools.trace import render_trace
from slogger.tools.trace import trace as trace_fn
from slogger.tools.tree import tree as tree_fn

_TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{4,32}$")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(64, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="slogger", description="Read and query slogger JSONL logs.")
    sub = parser.add_subparsers(dest="command")

    query_parser = sub.add_parser("query", help="Filter log records.")
    _add_source_args(query_parser)
    add_filter_args(query_parser)
    add_output_args(query_parser, allow_table=True)
    query_parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit aggregate counts instead of records.",
    )
    query_parser.add_argument(
        "--group-by",
        default=None,
        metavar="KEY",
        help="Group summary rows by KEY (implies --summary).",
    )
    query_parser.add_argument("--top", type=int, default=50)
    add_order_arg(query_parser)
    query_parser.set_defaults(func=_cmd_query)

    meta_parser = sub.add_parser("meta", help="Summarise log sources.")
    _add_source_args(meta_parser)
    add_filter_args(meta_parser)
    meta_parser.add_argument("--format", choices=("console", "json"), default=None)
    meta_parser.add_argument("--color", action="store_true", default=False)
    meta_parser.add_argument("--no-color", action="store_true", default=False)
    add_order_arg(meta_parser)
    meta_parser.set_defaults(func=_cmd_meta)

    fields_parser = sub.add_parser("fields", help="Discover keys and values.")
    _add_source_args(fields_parser)
    add_filter_args(fields_parser)
    fields_parser.add_argument("--format", choices=("console", "json"), default=None)
    fields_parser.add_argument("--color", action="store_true", default=False)
    fields_parser.add_argument("--no-color", action="store_true", default=False)
    fields_parser.add_argument("--scan", type=int, default=100_000)
    fields_parser.add_argument("--key", default=None)
    fields_parser.add_argument("--top", type=int, default=10)
    add_order_arg(fields_parser)
    fields_parser.set_defaults(func=_cmd_fields)

    trace_parser = sub.add_parser("trace", help="Show one trace as a span tree.")
    trace_parser.add_argument(
        "args",
        nargs="+",
        help="SOURCE [TRACE_ID]. TRACE_ID is a hex id/prefix (>=4 chars).",
    )
    add_filter_args(trace_parser)
    trace_parser.add_argument("--format", choices=("console", "json"), default=None)
    trace_parser.add_argument("--color", action="store_true", default=False)
    trace_parser.add_argument("--no-color", action="store_true", default=False)
    trace_parser.add_argument("--no-logs", action="store_true", default=False)
    trace_parser.add_argument(
        "--group-by",
        default=None,
        metavar="KEY=VALUE",
        help="Reconstruct the group matching KEY=VALUE instead of a trace id.",
    )
    add_order_arg(trace_parser)
    trace_parser.set_defaults(func=_cmd_trace)

    tail_parser = sub.add_parser("tail", help="Follow or poll a log file.")
    _add_source_args(tail_parser)
    add_filter_args(tail_parser)
    add_output_args(tail_parser)
    add_order_arg(tail_parser)
    tail_parser.add_argument(
        "--once",
        action="store_true",
        help="Read new records since --after and exit.",
    )
    tail_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=10,
        help="Backlog lines before following (0 disables). Default 10.",
    )
    tail_parser.add_argument(
        "--interval",
        type=float,
        default=0.25,
        help="Poll interval in seconds while following.",
    )
    tail_parser.set_defaults(func=_cmd_tail)

    tree_parser = sub.add_parser("tree", help="List reconstructed traces.")
    _add_source_args(tree_parser)
    add_filter_args(tree_parser)
    tree_parser.add_argument("--format", choices=("console", "json", "table"), default=None)
    tree_parser.add_argument("--color", action="store_true", default=False)
    tree_parser.add_argument("--no-color", action="store_true", default=False)
    tree_parser.add_argument("--group-by", default=None, metavar="KEY")
    tree_parser.add_argument(
        "--status", choices=("ok", "error", "unknown"), default=None
    )
    tree_parser.add_argument(
        "--slower-than",
        default=None,
        metavar="DUR",
        help="Keep traces with duration_ms greater than DUR (e.g. 400ms).",
    )
    tree_parser.add_argument(
        "--sort", choices=("started", "duration"), default="started"
    )
    tree_parser.add_argument("--top", type=int, default=50)
    add_order_arg(tree_parser)
    tree_parser.set_defaults(func=_cmd_tree)

    stats_parser = sub.add_parser("stats", help="Aggregate record and span stats.")
    _add_source_args(stats_parser)
    add_filter_args(stats_parser)
    stats_parser.add_argument(
        "--format", choices=("console", "json", "table"), default=None
    )
    stats_parser.add_argument("--color", action="store_true", default=False)
    stats_parser.add_argument("--no-color", action="store_true", default=False)
    stats_parser.add_argument("--group-by", default=None, metavar="KEY")
    stats_parser.add_argument("--spans", action="store_true", default=False)
    stats_parser.add_argument("--bucket", default=None, metavar="SIZE")
    stats_parser.add_argument("--top", type=int, default=50)
    add_order_arg(stats_parser)
    stats_parser.set_defaults(func=_cmd_stats)

    return parser


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--level", default=None, help="Minimum level, or =LEVEL for exact.")
    parser.add_argument("--logger", default=None, help="Logger name or prefix.")
    parser.add_argument(
        "--where",
        action="append",
        default=[],
        metavar="KEYOPVALUE",
        help="Compact filter token, e.g. user=ada or amount>=99.",
    )
    parser.add_argument("--has", action="append", default=[], metavar="KEY")
    parser.add_argument("--missing", action="append", default=[], metavar="KEY")
    parser.add_argument("--grep", default=None, help="Regex matched against message.")
    parser.add_argument("--since", default=None, help="ISO-8601 or relative (10m, 2h, 1d).")
    parser.add_argument("--until", default=None, help="ISO-8601 or relative.")
    parser.add_argument("--span", default=None, help="Active span name.")
    parser.add_argument("--trace", default=None, help="Exact trace id.")
    parser.add_argument(
        "--exclude-events",
        action="store_true",
        help="Drop span.start and span.end records.",
    )


def add_output_args(
    parser: argparse.ArgumentParser, *, allow_table: bool = False
) -> None:
    choices = ("console", "json", "table") if allow_table else ("console", "json")
    parser.add_argument("--format", choices=choices, default=None)
    parser.add_argument("--color", action="store_true", default=False)
    parser.add_argument("--no-color", action="store_true", default=False)
    parser.add_argument("--fields", default=None, help="Comma-separated keys to project.")
    parser.add_argument("--truncate", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--last", type=int, default=None)
    parser.add_argument("--after", default=None, help="Resume after this record id.")
    parser.add_argument(
        "--fail-if-any",
        action="store_true",
        help="Exit 1 when at least one record matches.",
    )


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "sources",
        nargs="+",
        help="Log files, globs, or - for stdin.",
    )


def add_order_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--order",
        choices=("concat", "time"),
        default="concat",
        help="Record order: concat (default) or timestamp merge.",
    )


def filters_from_args(args: argparse.Namespace) -> Filters:
    level_min = None
    level_exact = None
    if args.level is not None:
        if args.level.startswith("="):
            level_exact = level_number(args.level[1:])
        else:
            level_min = level_number(args.level)
    where = tuple(parse_where(token) for token in args.where)
    since = parse_relative_or_iso(args.since) if args.since else None
    until = parse_relative_or_iso(args.until) if args.until else None
    return Filters(
        level_min=level_min,
        level_exact=level_exact,
        logger=args.logger,
        where=where,
        has=tuple(args.has),
        missing=tuple(args.missing),
        grep=args.grep,
        since=since,
        until=until,
        span=args.span,
        trace=args.trace,
        exclude_events=bool(args.exclude_events),
    )


def resolve_format(args: argparse.Namespace, stdout: TextIO) -> str:
    if args.format is not None:
        return args.format
    try:
        is_tty = stdout.isatty()
    except Exception:
        is_tty = False
    return "console" if is_tty else "json"


def resolve_color(args: argparse.Namespace, stdout: TextIO, fmt: str) -> bool:
    if args.no_color:
        return False
    if args.color:
        return True
    return fmt == "console" and use_color(stdout)


def field_list(args: argparse.Namespace) -> list[str] | None:
    if not args.fields:
        return None
    return [part.strip() for part in args.fields.split(",") if part.strip()]


def usage_error(prog: str, message: str, stderr: TextIO) -> int:
    print(f"usage: {prog} [-h] ...", file=stderr)
    print(f"{prog}: error: {message}", file=stderr)
    return 64


def emit_error(err: BaseException, fmt: str, stderr: TextIO) -> int:
    if isinstance(err, ToolError):
        payload = err.to_dict()
    elif isinstance(err, FileNotFoundError):
        payload = {"error": "file_not_found", "message": str(err)}
    elif isinstance(err, PermissionError):
        payload = {"error": "permission_denied", "message": str(err)}
    else:
        payload = {"error": "error", "message": str(err)}
    if fmt == "json":
        print(json.dumps(payload), file=stderr)
    else:
        print(f"error: {payload.get('message', err)}", file=stderr)
    return 2


def write_page(page, fmt: str, color: bool, stdout: TextIO, stderr: TextIO) -> None:
    if fmt == "json":
        for record in page.records:
            print(render_json_line(record), file=stdout)
        meta = {
            "_meta": {
                "schema_version": 1,
                "returned": len(page.records),
                "skipped_lines": page.skipped_lines,
                "next_cursor": page.next_cursor,
                "warnings": page.warnings,
            }
        }
        print(json.dumps(meta), file=stdout)
    else:
        for record in page.records:
            print(render_console_line(record, color=color), file=stdout)
        if page.skipped_lines:
            print(
                f"skipped {page.skipped_lines} lines that were not JSON objects",
                file=stderr,
            )


def _render_meta_console(payload: dict, stdout: TextIO) -> None:
    sources = ", ".join(row["path"] for row in payload["sources"])
    first = payload["first_timestamp"] or "-"
    last = payload["last_timestamp"] or "-"
    print(
        f"{sources}  {payload['records']} records  {payload['skipped_lines']} skipped  "
        f"{first} -> {last}",
        file=stdout,
    )
    loggers = ", ".join(payload["loggers"]) or "-"
    spans = ", ".join(payload["spans"]) or "-"
    print(f"loggers: {loggers}   spans: {spans}", file=stdout)
    levels = "  ".join(f"{name} {count}" for name, count in payload["levels"].items())
    print(levels or "(no levels)", file=stdout)


def _render_fields_console(payload: dict, stdout: TextIO) -> None:
    if "key" in payload:
        print(f"{'value':<40} count", file=stdout)
        for row in payload["top"]:
            print(f"{str(row['value']):<40} {row['count']}", file=stdout)
        return
    print(f"{'key':<20} {'type':<8} {'distinct':<10} present  sample", file=stdout)
    for key, info in payload["keys"].items():
        sample = ", ".join(str(v) for v in info["samples"][:3])
        print(
            f"{key:<20} {info['type']:<8} {info['distinct']:<10} "
            f"{info['present_pct']:>6.1f}%  {sample}",
            file=stdout,
        )


def _cmd_meta(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    try:
        filters = filters_from_args(args)
        payload = meta_fn(args.sources, filters=filters, order=args.order)
    except ValueError as exc:
        return usage_error("slogger meta", str(exc), stderr)
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)
    if fmt == "json":
        print(json.dumps(payload), file=stdout)
    else:
        _render_meta_console(payload, stdout)
    return 0


def _cmd_fields(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    try:
        filters = filters_from_args(args)
        payload = fields_fn(
            args.sources,
            filters=filters,
            scan=args.scan,
            key=args.key,
            top=args.top,
            order=args.order,
        )
    except ValueError as exc:
        return usage_error("slogger fields", str(exc), stderr)
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)
    if fmt == "json":
        print(json.dumps(payload), file=stdout)
    else:
        _render_fields_console(payload, stdout)
    return 0


def _split_trace_args(args: argparse.Namespace) -> tuple[list[str], str | None]:
    parts = list(args.args)
    if len(parts) >= 2 and _TRACE_ID_RE.fullmatch(parts[-1]):
        return parts[:-1], parts[-1]
    return parts, None


def _cmd_tail(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    color = resolve_color(args, stdout, fmt)

    if args.after is not None and "-" in args.sources:
        return usage_error("slogger tail", "--after cannot be used with stdin", stderr)

    try:
        filters = filters_from_args(args)
    except ValueError as exc:
        return usage_error("slogger tail", str(exc), stderr)

    if args.once:
        limit = args.limit
        if limit is None and fmt == "json":
            limit = 200
        if limit == 0:
            limit = None
        try:
            page = tail_once(
                args.sources,
                filters=filters,
                after=args.after,
                limit=limit,
                fields=field_list(args),
                truncate=args.truncate,
                order=args.order,
            )
        except (CursorError, FileNotFoundError, PermissionError) as exc:
            return emit_error(exc, fmt, stderr)
        write_page(page, fmt, color, stdout, stderr)
        if args.fail_if_any and page.records:
            return 1
        return 0

    if args.order != "concat":
        return usage_error(
            "slogger tail",
            "--order time is not supported in follow mode (use --once)",
            stderr,
        )

    if len(args.sources) != 1:
        return usage_error(
            "slogger tail",
            "follow mode accepts exactly one source (use --once for globs)",
            stderr,
        )

    path = args.sources[0]
    reopened: list[str] = []

    def on_reopen(reopened_path: str) -> None:
        reopened.append(reopened_path)
        if fmt != "json":
            print(f"-- reopened {reopened_path}", file=stderr)

    try:
        stream = follow(
            path,
            filters=filters,
            after=args.after,
            interval=args.interval,
            lines=args.lines,
            on_reopen=on_reopen,
        )
        for record in stream:
            if field_list(args) is not None or args.truncate is not None:
                from slogger.tools.render import project

                record = project(record, field_list(args), args.truncate)
            if fmt == "json":
                print(render_json_line(record), file=stdout, flush=True)
            else:
                print(render_console_line(record, color=color), file=stdout, flush=True)
    except KeyboardInterrupt:
        return 130
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)
    return 0


def _cmd_trace(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    color = resolve_color(args, stdout, fmt)
    sources, trace_id = _split_trace_args(args)
    has_filters = any(
        [
            args.level,
            args.logger,
            args.where,
            args.has,
            args.missing,
            args.grep,
            args.since,
            args.until,
            args.span,
            args.trace,
            args.exclude_events,
        ]
    )
    group_by = None
    if args.group_by is not None:
        try:
            group_by = parse_group_selector(args.group_by)
        except ValueError as exc:
            return usage_error("slogger trace", str(exc), stderr)
        if trace_id is not None:
            return usage_error(
                "slogger trace",
                "positional trace id and --group-by are mutually exclusive",
                stderr,
            )
        if has_filters:
            return usage_error(
                "slogger trace",
                "--group-by and filter flags are mutually exclusive",
                stderr,
            )
    elif trace_id and has_filters:
        return usage_error(
            "slogger trace",
            "positional trace id and filter flags are mutually exclusive",
            stderr,
        )
    elif not trace_id and not has_filters:
        return usage_error(
            "slogger trace", "provide a trace id, --group-by, or filter flags", stderr
        )

    try:
        filters = filters_from_args(args) if has_filters else None
        result = trace_fn(
            sources,
            trace_id=trace_id,
            filters=filters,
            order=args.order,
            group_by=group_by,
        )
    except ValueError as exc:
        return usage_error("slogger trace", str(exc), stderr)
    except ToolError as exc:
        return emit_error(exc, fmt, stderr)
    except (FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)

    if fmt == "json":
        print(json.dumps(result.to_dict()), file=stdout)
    else:
        print(render_trace(result, color=color, logs=not args.no_logs), file=stdout)
    return 0


def _cmd_tree(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    if args.exclude_events:
        return usage_error(
            "slogger tree",
            "--exclude-events cannot be used with tree",
            stderr,
        )
    try:
        filters = filters_from_args(args)
        slower = (
            parse_duration_ms(args.slower_than) if args.slower_than is not None else None
        )
        payload = tree_fn(
            args.sources,
            filters=filters,
            group_by=args.group_by,
            status=args.status,
            slower_than_ms=slower,
            span=args.span,
            sort=args.sort,
            top=args.top,
            order=args.order,
        )
    except ValueError as exc:
        return usage_error("slogger tree", str(exc), stderr)
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)

    if fmt == "json":
        print(json.dumps(payload), file=stdout)
    elif fmt == "table":
        rows = []
        for tr in payload["traces"]:
            label = (
                f"{tr['group']['key']}={tr['group']['value']}"
                if tr["group"] is not None
                else tr["trace_id"]
            )
            rows.append(
                {
                    "trace": label,
                    "root_span": tr["root_span"],
                    "spans": tr["spans"],
                    "failed": tr["failed"],
                    "unfinished": tr["unfinished"],
                    "status": tr["status"],
                    "duration_ms": tr["duration_ms"],
                    "started": tr["started"],
                }
            )
        print(
            render_table(
                rows,
                [
                    "trace",
                    "root_span",
                    "spans",
                    "failed",
                    "unfinished",
                    "status",
                    "duration_ms",
                    "started",
                ],
            ),
            file=stdout,
        )
    else:
        for tr in payload["traces"]:
            label = (
                f"{tr['group']['key']}={tr['group']['value']}"
                if tr["group"] is not None
                else tr["trace_id"]
            )
            duration = (
                f"{tr['duration_ms']:g}" if tr["duration_ms"] is not None else "-"
            )
            print(
                f"{label}  {tr['root_span'] or '-'}  spans={tr['spans']}  "
                f"status={tr['status']}  duration_ms={duration}",
                file=stdout,
            )
        print(
            f"total {payload['total']}  returned {payload['returned']}",
            file=stdout,
        )
    return 0


def _cmd_stats(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    if args.exclude_events and args.spans:
        return usage_error(
            "slogger stats",
            "--exclude-events cannot be used with --spans",
            stderr,
        )
    try:
        filters = filters_from_args(args)
        if args.bucket is not None:
            parse_bucket(args.bucket)  # validate early for usage 64
        payload = stats_fn(
            args.sources,
            filters=filters,
            group_by=args.group_by,
            spans=args.spans,
            bucket=args.bucket,
            top=args.top,
            order=args.order,
        )
    except ValueError as exc:
        return usage_error("slogger stats", str(exc), stderr)
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)

    if fmt == "json":
        print(json.dumps(payload), file=stdout)
    elif fmt == "table":
        rows = []
        if payload.get("bucket"):
            for bucket in payload["totals"].get("buckets", []):
                row = {"bucket": bucket["start"], "records": bucket.get("records", 0)}
                if args.spans:
                    row["spans"] = bucket.get("spans", 0)
                    dur = bucket.get("duration_ms", {})
                    p50 = dur.get("p50")
                    if p50 is not None and dur.get("percentiles_capped"):
                        row["p50"] = f"~{p50:g}"
                    else:
                        row["p50"] = p50
                rows.append(row)
            cols = ["bucket", "records"] + (["spans", "p50"] if args.spans else [])
        else:
            rows = [{"scope": "totals", "records": payload["totals"]["records"]}]
            if args.spans:
                rows[0]["spans"] = payload["totals"]["spans"]
            for group in payload["groups"]:
                row = {"scope": str(group["value"]), "records": group.get("records", 0)}
                if args.spans:
                    row["spans"] = group.get("spans", 0)
                rows.append(row)
            cols = ["scope", "records"] + (["spans"] if args.spans else [])
        print(render_table(rows, cols), file=stdout)
    else:
        print(
            f"records {payload['totals']['records']}  "
            f"skipped {payload['skipped_lines']}",
            file=stdout,
        )
        if args.spans:
            t = payload["totals"]
            print(
                f"spans {t['spans']}  completed {t['completed']}  "
                f"failed {t['failed']}  unfinished {t['unfinished']}",
                file=stdout,
            )
    return 0


def _cmd_query(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    color = resolve_color(args, stdout, fmt)

    if args.group_by is not None:
        args.summary = True
    if args.summary:
        if args.limit is not None or args.last is not None:
            return usage_error(
                "slogger query",
                "--limit/--last cannot be used with --summary",
                stderr,
            )
        if args.fields is not None or args.truncate is not None:
            return usage_error(
                "slogger query",
                "--fields/--truncate cannot be used with --summary",
                stderr,
            )
        if fmt == "table" or args.format == "table":
            pass  # allowed for summary
        elif args.format is None:
            fmt = resolve_format(args, stdout)

    if args.after is not None and "-" in args.sources:
        return usage_error("slogger query", "--after cannot be used with stdin", stderr)
    if args.last is not None and args.after is not None:
        return usage_error(
            "slogger query", "--last and --after are mutually exclusive", stderr
        )

    try:
        filters = filters_from_args(args)
    except ValueError as exc:
        return usage_error("slogger query", str(exc), stderr)

    if args.summary:
        try:
            payload = summary_fn(
                args.sources,
                filters=filters,
                after=args.after,
                group_by=args.group_by,
                top=args.top,
                order=args.order,
            )
        except (CursorError, FileNotFoundError, PermissionError) as exc:
            return emit_error(exc, fmt, stderr)
        if fmt == "json":
            print(json.dumps(payload), file=stdout)
        elif fmt == "table":
            rows = [
                {
                    "matched": payload["matched"],
                    "levels": len(payload["levels"]),
                    "loggers": len(payload["loggers"]),
                }
            ]
            print(render_table(rows, ["matched", "levels", "loggers"]), file=stdout)
        else:
            print(
                f"matched {payload['matched']}  "
                f"{payload['first_timestamp'] or '-'} -> {payload['last_timestamp'] or '-'}",
                file=stdout,
            )
        if args.fail_if_any and payload["matched"] > 0:
            return 1
        return 0

    if fmt == "table":
        return usage_error(
            "slogger query",
            "--format table requires --summary",
            stderr,
        )

    limit = args.limit
    if limit is None and fmt == "json" and args.last is None:
        limit = 200
    if limit == 0:
        limit = None

    try:
        page = query(
            args.sources,
            filters=filters,
            limit=limit,
            after=args.after,
            last=args.last,
            fields=field_list(args),
            truncate=args.truncate,
            order=args.order,
        )
    except (CursorError, FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)

    write_page(page, fmt, color, stdout, stderr)
    if args.fail_if_any and page.records:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        print("slogger: error: a command is required", file=sys.stderr)
        return 64
    try:
        return int(args.func(args, sys.stdout, sys.stderr))
    except ValueError as exc:
        # Reader/parse_id and similar raise ValueError for bad usage tokens.
        return usage_error("slogger", str(exc), sys.stderr)
    except ToolError as exc:
        fmt = resolve_format(args, sys.stdout) if hasattr(args, "format") else "json"
        return emit_error(exc, fmt, sys.stderr)
    except BrokenPipeError:
        return 0
