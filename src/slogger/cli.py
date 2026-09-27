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
from slogger.tools.meta import meta as meta_fn
from slogger.tools.query import query
from slogger.tools.render import render_console_line, render_json_line, use_color
from slogger.tools.tail import follow, tail_once
from slogger.tools.trace import render_trace
from slogger.tools.trace import trace as trace_fn

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
    add_output_args(query_parser)
    query_parser.set_defaults(func=_cmd_query)

    meta_parser = sub.add_parser("meta", help="Summarise log sources.")
    _add_source_args(meta_parser)
    add_filter_args(meta_parser)
    meta_parser.add_argument("--format", choices=("console", "json"), default=None)
    meta_parser.add_argument("--color", action="store_true", default=False)
    meta_parser.add_argument("--no-color", action="store_true", default=False)
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
    trace_parser.set_defaults(func=_cmd_trace)

    tail_parser = sub.add_parser("tail", help="Follow or poll a log file.")
    _add_source_args(tail_parser)
    add_filter_args(tail_parser)
    add_output_args(tail_parser)
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


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("console", "json"), default=None)
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
        payload = meta_fn(args.sources, filters=filters)
    except ValueError as exc:
        print("usage: slogger meta [-h] ...", file=stderr)
        print(f"slogger: error: {exc}", file=stderr)
        return 64
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
        )
    except ValueError as exc:
        print("usage: slogger fields [-h] ...", file=stderr)
        print(f"slogger: error: {exc}", file=stderr)
        return 64
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
        print("usage: slogger tail [-h] ...", file=stderr)
        print("slogger: error: --after cannot be used with stdin", file=stderr)
        return 64

    try:
        filters = filters_from_args(args)
    except ValueError as exc:
        print("usage: slogger tail [-h] ...", file=stderr)
        print(f"slogger: error: {exc}", file=stderr)
        return 64

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
            )
        except (CursorError, FileNotFoundError, PermissionError) as exc:
            return emit_error(exc, fmt, stderr)
        write_page(page, fmt, color, stdout, stderr)
        if args.fail_if_any and page.records:
            return 1
        return 0

    if len(args.sources) != 1:
        print("usage: slogger tail [-h] ...", file=stderr)
        print(
            "slogger: error: follow mode accepts exactly one source "
            "(use --once for globs)",
            file=stderr,
        )
        return 64

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
    if trace_id and has_filters:
        print("usage: slogger trace [-h] ...", file=stderr)
        print(
            "slogger: error: positional trace id and filter flags are mutually exclusive",
            file=stderr,
        )
        return 64
    if not trace_id and not has_filters:
        print("usage: slogger trace [-h] ...", file=stderr)
        print("slogger: error: provide a trace id or filter flags", file=stderr)
        return 64

    try:
        filters = filters_from_args(args) if has_filters else None
        result = trace_fn(sources, trace_id=trace_id, filters=filters)
    except ValueError as exc:
        print("usage: slogger trace [-h] ...", file=stderr)
        print(f"slogger: error: {exc}", file=stderr)
        return 64
    except ToolError as exc:
        return emit_error(exc, fmt, stderr)
    except (FileNotFoundError, PermissionError) as exc:
        return emit_error(exc, fmt, stderr)

    if fmt == "json":
        print(json.dumps(result.to_dict()), file=stdout)
    else:
        print(render_trace(result, color=color, logs=not args.no_logs), file=stdout)
    return 0


def _cmd_query(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    fmt = resolve_format(args, stdout)
    color = resolve_color(args, stdout, fmt)

    if args.after is not None and "-" in args.sources:
        print("usage: slogger query [-h] ...", file=stderr)
        print("slogger: error: --after cannot be used with stdin", file=stderr)
        return 64
    if args.last is not None and args.after is not None:
        print("usage: slogger query [-h] ...", file=stderr)
        print("slogger: error: --last and --after are mutually exclusive", file=stderr)
        return 64

    try:
        filters = filters_from_args(args)
    except ValueError as exc:
        print("usage: slogger query [-h] ...", file=stderr)
        print(f"slogger: error: {exc}", file=stderr)
        return 64

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
    except BrokenPipeError:
        return 0
