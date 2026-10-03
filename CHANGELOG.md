# Changelog

## Unreleased

- Support optional native Polars global grouping and named numeric reductions,
  preserving typed key identity, group order and explicit precision/overflow errors.

- Native Polars filters now preserve missing/null, nested paths and mixed scalar
  types with lossless per-type lanes, including fields introduced in later batches.

- Add Python plan group-by and named count/sum/mean/min/max reductions, typed
  group identity, stable group order and post-aggregate filtering/projection.

- Add optional `tools-polars` native scalar query-plan execution with explicit
  capability/data errors, original-record reconstruction and bounded filter batches.
  Python remains the default; core logging and CLI/MCP inputs are unchanged.

- Normalize query plans conservatively with backend-aware limit/filter handling,
  validated projection collapse, boolean simplification and original error indices.

- Add global Python query-plan sorting with exact numeric ordering, stable source
  ties, explicit missing/null placement and field-domain validation.

- Add Python-only immutable `scan()` / `QueryPlan` with filter, projection, limit,
  static explanation and materialized `PlanResult`; legacy tooling stays compatible.

- Tooling predicates now expose immutable IXR, required fields, and versioned
  inspection; Python matcher compilation is lazy and cached. Custom predicates
  remain compatible.

- Adds typed Python tooling predicates: `Field`, `Predicate`, `all_of`, `any_of`,
  `not_`, and `logger_prefix`, integrated through `Filters(predicate=...)`.
  Supports membership, nested mapping paths, comparisons, regex/prefix matching,
  presence checks, and array membership with reusable compiled matchers.
  Preserves legacy filters and core logging; CLI/MCP input syntax is unchanged.

- Corrects Zsh completion setup to use a shell function; alias expansion bypassed
  the registered completer. Adds an interactive Tab-completion regression test.

- Prevents callback reconfiguration and nested-emission deadlocks; callback
  `configure()` / `reset()` calls raise `RuntimeError` before acquiring locks.
- Preserves span context fields that share logging control names and caller attribution.
- Applies span-name and anchor-window filters, reconstructs before group attribution,
  retains cyclic spans with warnings, and orders trace timestamps by UTC instant.
- Replays stdin for trace/context while preserving IDs and cleaning up temporary files.
- Bounds collector group metadata and avoids retaining ordinary logs for aggregates.
- Distinguishes JSON value types in field counts; avoids stale and colliding cache writes.
- Uses standard newline-delimited MCP framing, per-tool input contracts, resilient
  request validation, and rejects protocol stdin as a log source.
- Validates tool output directly against the bundled schema, including nested fields.

- Makes `configure()` restore the previous handlers, logger settings, filters,
  and span-event setting if replacement handler attachment fails; reused owned
  handlers stay open until their eventual removal.
- Keeps structured records when payload containers are cyclic, mapping keys are
  unsupported by JSON, or an object's `repr` fails.
- Preserves record IDs under truncation and merge cursors for `last` polling.
- Fixes generator consumption in `validate()` and cached `fields()` discovery.
- Streams stdin in `follow()`, honours explicit cursors over the default backlog,
  holds unterminated backlog records, and fixes physical-line IDs in stdin `watch()`.
- Parses `--where` at the first operator and validates regex clauses eagerly;
  rejects non-positive and boolean integer bucket sizes.
- Adds argcomplete to the development extra, removes type-checker warnings and
  dead branches/comments, and counts cursor-validation lines without loading the
  whole file into memory.
- Corrects docs for capture configuration lifetime, tail metadata, percentile
  tables, trace ID samples, source support, and current MCP transport limitations.

- Fixes `python3 -m slogger completion --shell bash|zsh` so `eval "$(…)"` no
  longer fails with a syntax error (argcomplete function-name / IFS issue with
  `python3 -m slogger`).
- Completes CLI P2 (see `docs/plans/cli-p2-handoff.md`):
  - T5: stdio MCP server (`python3 -m slogger.tools.mcp`)
  - T4: `completion` + optional `[cli]` extra (`argcomplete`), dynamic `--where` / `--logger`
  - T3: optional `fields` sidecar cache (`cache=` / CLI `fields` enables it)
  - T2: `tool-output.schema.json` with `output_schemas()` / `validate_tool_output()`
  - T1: `explain` / `Filters.explain()` (and `Filters.from_mapping`)
  - T0: `watch --existing` first-match; streaming `context`; invalid `--grep` → 64;
    drop unsupported `watch --order`
- Corrects CLI user docs against landed behaviour (JSON default `--limit 200`, duration /
  bucket units, `watch` timeout, `fields --top`, stale plan sketches).
- Adds user-facing documentation: `docs/api.md` and `docs/cli.md`. README links to both.
- Completes CLI P1: `tree`, `stats`, `errors`, `validate`, `context`, `diff`, `watch`,
  `query --summary` / `--group-by`, `--format table`, and `--order time` merge cursors.
- Adds `slogger.tools` and `python3 -m slogger` for reading JSONL logs (P0): `query`,
  `meta`, `fields`, `trace`, and `tail`.

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
