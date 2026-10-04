# Changelog

## Unreleased

- Add shared grammar-aware filter syntax completion with typed JSON templates,
  array elements, connectors, delimiters and repair guidance. Native editors offer
  scrollable keyboard/mouse selection, local dismissal/reopening and stale-response
  rejection while preserving newer drafts, suffixes, applied views and pane focus.

- Add complete dataset-scoped background trace trees with paged disk indexes,
  source-order identity across files, missing-parent placeholders, explicit
  relationship/cycle uncertainty, and conservative canonical lifecycle summaries.
  Preserve every captured occurrence, selection and JSON pins through native
  flat/tree switching, folds, keyboard/mouse navigation and cancellation.
  Filtered ancestor context and search remain separate subsequent slices.
- Add shared complete IXR infix parsing with typed/nested/literal paths and located
  errors; expose explicitly scoped cancellable Investigation filter jobs and
  complete disk-backed result pages preserving original order, origins and identities.
  Isolate reference regex evaluation in a package-owned subprocess and account
  result staging through managed storage. Add a compact native Main editor with
  distinct draft/applied/pending state, safe supersession/cancellation and separate
  displayed positions, preserving pinned JSON and prior successful views.

- Add complete JSON inspector navigation, optional line numbers, exact nested and
  literal key targets with unsupported-path guidance, independent source-aware
  pins, keyboard hide/resize/focus controls and a narrow full-width inspector.
  Copy sends complete inspected JSON through OSC 52 with explicit unavailable
  or unverified-acceptance status; command-palette controls remain reachable.
  Progressive capture updates preserve pins and JSON scroll/key selection while
  updating origin counts and resource usage.
- Add complete-content console wrapping with variable-height paging/click mapping,
  keyboard/mouse scrolling and horizontal page/reset routes. Preserve record
  selection through resize and expose temporary timestamp/duration options with
  aligned columns; retain bounded visible rows and one admitted-record layout.

- Add optional `tools-tui`/`slogger-tui` native split-view opening, headless stable
  Investigation capture and paged access, original physical origins and repeated
  input identities, explicit record/disk/RAM admission, complete parsed JSON, and
  session cleanup.
- Add progressive background capture, explicit verification progress, retained
  canceled/failed prefixes, native loading/error states and Escape cancellation.
  Bound transactional record/diagnostic publication and reconcile changed-file
  allocation without per-record file opens or full storage scans. Complete-dataset
  operations remain gated until verified capture; persistent cache lifecycle
  follows separately.
- Make the shared type checker query its selected editable interpreter, including
  optional native dependencies and Python endpoint environments.

- Add development environment preflight, shared checks, a local pre-commit hook,
  documentation lifecycle validation, and focused agent workflow references.

- Breaking: convenient Field/boolean builders now return IXR directly; remove the
  Predicate facade, custom executable callbacks, compile/matches/to_ixr methods,
  and legacy inspection. Expressions support `&`, `|`, and `~`; both adapters
  compile the same nodes. Query expressions and planning now live in query core.

- Breaking: remove legacy Filters/Where, query/Page/summary, specialized tooling,
  CLI/completion, MCP, and transport-only schemas/extras. Retain finite query plans,
  builders, Python and optional Polars execution; core logging is unchanged.
  Trace/tree reconstruction and live watching are withdrawn pending future designs.

- Preserve cancellation-sensitive and repeated-fraction reduction parity using
  checked binary fixed-point native Int128 sums/means and compensated Python
  floating reductions across interpreter versions.
- Share nested field resolution/missing identity and record projection between
  execution adapters to keep matching and reconstruction semantics aligned.

- Provide reproducible IXR benchmarks with backend correctness checks, diagnostic
  phase probes, and peak memory reporting; previous measurements are historical.


- Preserve native existence/missing checks for object-valued, heterogeneous-array
  and large-integer fields when no value operation needs their representation.

- Add global native Polars sorting with source-ordinal ties, separate missing/null
  categories, exact integer-only keys and explicit unsupported precision errors.

- Support optional native Polars global grouping and named numeric reductions,
  preserving typed key identity, group order and explicit precision/overflow errors.

- Add native Polars string prefixes, logger hierarchy matching and plain-literal
  regex patterns, with eager capability rejection of unsupported regex constructs.

- Native Polars filters now preserve missing/null, nested paths and mixed scalar
  types with lossless per-type lanes, including fields introduced in later batches.

- Add Python plan group-by and named count/sum/mean/min/max reductions, typed
  group identity, stable group order and post-aggregate filtering/projection.

- Add optional `tools-polars` execution of shared IXR for sparse scalar, string,
  array, sorting, and grouping operations with explicit capability/data errors.
- Normalize plans conservatively while preserving field lineage, diagnostics,
  input accounting, and stable ordering.
- Breaking: finite inputs now live in the source module without Reader aliases,
  cursors, replay, or live modes. Construction/explanation do not consume input;
  reusable files/collections and one-shot stdin/iterators have explicit lifetimes.
- Breaking: expose aligned `PlanResult.origins` separately from application fields.
  Preserve origin through filter/projection/sort; aggregate origins are `None`.
  A logged `_id` is ordinary queryable data, including grouping and aliases.
- Reconcile maintained docs, capability examples, agent navigation, and benchmark
  entry points with the IXR-only library; label previous measurements historical.

### Historical development of retired tooling

The entries below record earlier work on interfaces removed by this migration.
They are history, not a list of current capabilities or installation instructions.

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
