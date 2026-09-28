# Changelog

## Unreleased

- Adds `python3 -m slogger completion` and optional `[cli]` extra (`argcomplete`) with
  dynamic `--where` / `--logger` completion (P2 T4).
- Adds optional sidecar cache for `fields` (`cache=` / CLI `fields` enables it) for
  unfiltered single-file overviews (P2 T3).

- Publishes `slogger/schemas/tool-output.schema.json` with `output_schemas()` /
  `validate_tool_output()` for aggregate and list `_meta` contracts (P2 T2).
- Adds `python3 -m slogger explain` and `Filters.explain()` (P2 T1) to print the
  normalised filter predicate without reading sources.
- Fixes P2 warm-up (T0): `watch --existing` stops at the first match; `context` streams
  neighbours / same-trace with bounded memory; invalid `--grep` exits 64; `watch` no longer
  advertises unsupported `--order`.

- Adds P2 implementation handoff (`docs/plans/cli-p2-handoff.md`): `explain`, tool-output
  schemas, completion, fields cache, MCP, plus a warm-up task for review findings
  (`watch --existing` memory, streaming `context`, `--grep` validation, `watch --order`).
- Corrects CLI user docs against landed behaviour (JSON default `--limit 200`, duration /
  bucket units, `watch` timeout, `fields --top`, stale plan sketches).
- Adds user-facing documentation: `docs/api.md` (public modules with examples) and
  `docs/cli.md` (CLI options, exit codes, and recipes). README links to both.
- Adds `slogger.tools` and `python3 -m slogger` for reading JSONL logs (P0): `query`, `meta`,
  `fields`, `trace`, and `tail` (follow / `--once`). See `docs/plans/cli.md`.
- Completes CLI P1: `tree`, `stats`, `errors`, `validate`, `context`, `diff`, `watch`,
  `query --summary` / `--group-by`, `--format table`, and `--order time` merge cursors.
  Tools names are exported from `slogger.tools.__all__` only.

## 0.2.0

Configuration is explicit, loggers are named, and spans record their own start and end.

- Package moved to a `src/` layout; install with `pip install -e ".[dev]"` before running tests or examples.
- Supports Python 3.10 through 3.13 (caller attribution adjusts for the 3.11 `findCaller` change).
- Publishes a formal log-record contract as `LogRecord` (TypedDict), JSON Schema, and `validate_log_record()`.
- Adds [pyrefly](https://pyrefly.org/) to the `dev` extra with `[tool.pyrefly]` project settings.
- Adds `capture_logs()` for asserting on structured records in tests.
- Defers the processor pipeline; design notes live in `docs/plans/processor-pipeline.md`.

- `import slogger` no longer creates `app.log` or attaches handlers. Call `configure()`.
- `get_logger(name)` returns a cached logger. `builtin_logger` is `get_logger("slogger")`.
- `bind()` / `unbind()` add fields without mutating the original logger.
- Handlers installed by `configure()` sit on the root logger by default, so stdlib and third-party records are rendered the same way and pick up the active span.
- Spans emit `span.start` and `span.end` with `span_id`, `parent_span_id`, `trace_id`, `duration_ms`, and `status`.
- Console output includes the structured fields. Timestamps are UTC ISO-8601. Colour follows the TTY, `NO_COLOR`, and `FORCE_COLOR`.
- `wrap_context()` and `run_in_executor()` carry the active span into worker threads.
- Requires Python 3.10+.

## 0.1.0

Initial release: JSON logging, `span`, and `instrument`, including async functions.
