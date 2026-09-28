# P2 handoff: explain, schemas, completion, MCP

Implementation-ready breakdown of P2 from [`cli.md`](cli.md), written against the P0+P1
code in `src/slogger/tools/` and `src/slogger/cli.py`. Where this file and `cli.md`
disagree, **this file wins for P2 work**.

Scope:

| Item | Goal |
| --- | --- |
| `explain` | Print the normalised filter predicate for a set of flags / a `Filters` value |
| Published tool-output schemas | JSON Schema(s) for aggregate payloads and list `_meta` |
| `completion` | Optional `[cli]` extra: static + dynamic shell completion via `argcomplete` |
| Fields sidecar cache | Cheap repeated `fields` for dynamic `--where` completion |
| MCP wrapper | Thin server over `slogger.tools` (same JSON contracts as the CLI) |

Also in this handoff: a **warm-up** task (T0) that closes review findings which would
otherwise break MCP/agent use of large files or mislead P2 docs.

Out of scope (unchanged from `cli.md`): natural-language query, persistent index, remote
sources, TUI/REPL, alternate input formats, record-schema changes, console-script rename
(blocked on a free PyPI name), `rich`, sequence tools.

## Baseline (run 2026-09-28 on `stable` + docs branch)

| Check | Command | Result |
| --- | --- | --- |
| Interpreter | `python3 --version` | Python 3.12.x. Prefer `python3`. |
| Tests | `python3 -m pytest -q` | 198 passed |
| Lint | `python3 -m ruff check src tests examples` | All checks passed |
| Types | `python3 -m pyrefly check` | 0 errors |
| CLI | `python3 -m slogger --help` | lists P0+P1 commands; no `explain` / `completion` |
| Packaging | `pyproject.toml` | no `[cli]` extra, no `[project.scripts]`, no `argcomplete` |
| Schemas | `src/slogger/schemas/` | only `log-record.schema.json` |
| Docs | `docs/api.md`, `docs/cli.md` | user-facing; design notes still under `docs/plans/` |

All P2 tasks must keep the three checks green and add tests under `tests/`.

## Review findings (P0/P1 code vs contracts)

Audit of the landed tools/CLI against handoffs, `docs/cli.md`, and `docs/api.md`. Severity:
**bug** = wrong behaviour; **doc** = docs wrong or incomplete; **nit** = sharp edge.

### Bugs to fix before or at the start of P2 (T0)

| # | Finding | Expected | Actual | Suggested fix |
| --- | --- | --- | --- | --- |
| B1 | `watch --existing` | Stream until first match (D10); bounded memory | `query(..., complete=True)` with no `limit` materialises every match, returns `[0]` | `query(..., limit=1)` or a first-match loop |
| B2 | `context` | One pass with neighbour deques + `max_trace` (D8) | Loads every record into `all_rows` | Rewrite to streaming neighbour windows |
| B3 | Invalid `--grep` | Usage exit `64` | `re.error` escapes from `Filters.matches` | Compile in `Filters.__post_init__` / CLI `filters_from_args`; map to `ValueError` |
| B4 | `watch --order` | Not supported (D10) | Flag appears in `--help`; choosing `time` → exit 64 | Drop `add_order_arg` from `watch` |

### Doc / help mismatches (fix in user docs as part of this branch; keep plans honest)

| # | Finding | Fix |
| --- | --- | --- |
| D1 | `docs/cli.md` suggested `watch --timeout 0` = forever | Document `timeout > 0` only (matches D10 / code) |
| D2 | `docs/cli.md` said `--bucket` accepts bare int seconds | CLI needs `60s`; int only on Python `stats(bucket=60)` |
| D3 | `docs/cli.md` said `fields --top` also sets sample size | Samples hard-capped at 5; `--top` only with `--key` |
| D4 | JSON default `--limit 200` undocumented | Document under shared paging; `--limit 0` = unlimited |
| D5 | Bare `--slower-than 500` is **500 seconds** | Document units; argparse help should say bare = seconds |
| D6 | `docs/plans/cli.md` usage sketches still use `--by`, `--metric`, `context --after` | Rewrite sketches to match P1 flags (this file + `docs/cli.md`) |
| D7 | Plan filter grammar: `--trace` “id or unique prefix” | Shared `--trace` is **exact**; prefix is positional `trace` TRACE_ID only |
| D8 | Percentile / `max_samples` / `percentiles_capped` undocumented for agents | Note under `stats` in user docs |
| D9 | Plan module layout still shows P0-only tree + `filters.explain()` as if present | Refresh layout; `explain()` is P2 |

### Sharp edges (document; optional hardening later)

| # | Note |
| --- | --- |
| S1 | `query` sets `next_cursor` when `limit` equals remaining matches (empty next page) — by design |
| S2 | `context --id` must match the source label exactly (`./app.log` ≠ `app.log`) |
| S3 | `tree` / `stats --spans` / `errors` buffer whole traces via `SpanCollector` before filtering |
| S4 | Positional `trace` TRACE_ID (prefix ≥4 hex) vs `--trace` (exact) |
| S5 | `trace` / other two-pass APIs need materialised sources (generators are consumed once) |
| S6 | `stats` console output is thinner than early plan sketches; JSON/table carry percentiles |
| S7 | `order=time` + `last` + `complete=False` can expose a concat-style cursor (API-only footgun) |

## Facts checked in the P1 code (relevant to P2)

| Area | Verified behaviour | Consequence for P2 |
| --- | --- | --- |
| `Filters` | Dataclass; no `explain()`; `_grep_re` compiles lazily in `matches` | T1 adds `explain()` + eager validate |
| Aggregate JSON | Every aggregate payload already has `schema_version: 1` with stable top-level keys (see D2) | Schemas can freeze current shapes |
| List `_meta` | `schema_version`, `returned`, `skipped_lines`, `next_cursor`, `warnings` (+ context extras) | One shared list-meta schema |
| `fields` | `scan` default 100_000; no sidecar cache | T3 adds cache; completion depends on it |
| Packaging | No `[cli]` extra | T4 adds optional `argcomplete` only behind `[cli]` |
| Exit codes | `0/1/2/3/64/130` | `explain` / `completion` stay in this scheme |
| `slogger.tools.__all__` | Tools stay off package root | MCP and schemas consume `slogger.tools`, not `import slogger` |

### Frozen aggregate key sets (for schema drafting)

Captured 2026-09-28 from fixtures (top-level keys only):

```text
meta      schema_version sources records skipped_lines first_timestamp last_timestamp
          levels loggers loggers_capped spans spans_capped traces traces_capped
fields    schema_version scanned scan_capped keys
          (+ key / top when --key)
summary   schema_version order matched skipped_lines levels loggers group_by groups
          groups_capped ungrouped first_id last_id first_timestamp last_timestamp warnings
tree      schema_version order group_by total returned traces groups_capped ungrouped
          skipped_lines warnings truncated
stats     schema_version order records skipped_lines group_by spans bucket totals groups
          groups_capped ungrouped warnings
errors    schema_version order records_scanned skipped_lines error_records failed_spans
          groups total_groups returned groups_capped warnings
validate  schema_version sources lines valid invalid kinds diagnostics diagnostics_capped
diff      schema_version order before after group_by spans totals groups added removed
          truncated warnings
trace     schema_version trace_id status started ended duration_ms spans logs warnings
          matched_records matched_traces group
list _meta  schema_version returned skipped_lines next_cursor warnings
            (+ context: anchor, trace_id, before, after, trace_records, trace_capped)
watch JSON  matched record (or null) + _meta {schema_version, matched, timed_out,
            elapsed_ms, records_seen}
```

Bump `schema_version` only on breaking changes; additive optional keys stay on version 1.

## Binding decisions

### D1. Compatibility

Preserve unchanged: `Filters` / `Where` grammar, `Page`, cursors, `--order`, exit codes,
JSONL + `_meta`, aggregate `schema_version: 1` shapes above, exports from
`slogger.tools.__all__` only, no record-schema changes.

New public names (tools `__all__` unless noted):

```python
# filters.py
def Filters.explain(self) -> dict[str, Any]          # or standalone explain_filters(filters)
# Prefer method for discoverability; CLI wraps it.

# meta / fields already return dicts — no new types required for schemas

# fields.py
def fields(..., *, cache: bool | None = None, cache_dir: str | None = None) -> dict
# cache default: True for CLI completion path; False (or unset) keeps today’s behaviour
# for the public API unless explicitly enabled — see D3.

# cli.py commands
explain SOURCE_FLAGS...     # no sources required; may accept optional sources for examples
completion --shell bash|zsh|fish [--install]
```

MCP surface is **not** imported into `slogger.tools`; it lives under
`slogger.tools.mcp` or a separate optional package path that only imports the tools API
(decision in D5).

### D2. `explain`

- Input: the same filter flags as every other command (no sources required).
- Output JSON (default when not a TTY):

```json
{
  "schema_version": 1,
  "filters": {
    "level_min": 40,
    "level_exact": null,
    "logger": "app.pay",
    "where": [{"key": "user", "op": "=", "value": "ada"}],
    "has": ["order_id"],
    "missing": [],
    "grep": "timeout",
    "since": "2026-09-26T15:00:00.000Z",
    "until": null,
    "span": null,
    "trace": null,
    "exclude_events": true
  },
  "notes": [
    "multiple --where clauses are ANDed",
    "missing keys never match comparisons"
  ]
}
```

- Console: one readable block (key: value lines), not a table.
- Relative `--since` / `--until` are resolved to absolute UTC ISO-8601 at explain time
  (same helper as `filters_from_args`).
- Invalid tokens → exit `64` (including bad `--grep` once B3 lands).
- Python: `Filters(...).explain() -> dict`.

### D3. Fields sidecar cache

- Path: `<logpath>.slogger-fields.json` next to the file (or under `cache_dir` when given).
- Invalidate when `(size, mtime_ns)` of the source file change, or when `scan` / filter
  fingerprint differ from the cached request.
- Cache stores the **unfiltered** key overview for the default scan window; filtered
  `fields` calls still scan (do not serve stale filtered views from an unfiltered cache).
- For globs / multi-source: no shared cache in P2 (document; scan as today).
- Stdin / in-memory: never cache.
- CLI `fields` keeps current defaults; completion enables cache.
- Public API: `cache=False` by default so library callers are not surprised by new files;
  `python3 -m slogger fields` may pass `cache=True` (document in CHANGELOG).

### D4. Published schemas

Ship as package data next to the record schema:

```text
src/slogger/schemas/
  log-record.schema.json          # existing
  tool-output.schema.json         # bundle, or split per command — prefer one file with
                                  # $defs for meta, fields, summary, tree, stats, errors,
                                  # validate, diff, trace, page_meta, watch_meta, explain
```

- Loader: `slogger.tools.output_schemas()` → `dict` (mirrors `log_record_json_schema()`).
- Validation helper (stdlib only, same spirit as `validate_log_record`): optional
  `validate_tool_output(kind, payload)` for tests / MCP; **not** a hard dependency on the
  `jsonschema` package.
- Docs: link from `docs/cli.md` and `docs/api.md`; keep examples in sync with `$defs`.
- Do **not** change payload shapes in this task except additive optional keys required by
  explain/completion.

### D5. Completion (`[cli]` extra)

```toml
[project.optional-dependencies]
cli = ["argcomplete>=3"]
```

- `python3 -m slogger completion --shell bash` prints a script that registers the parser.
- Static: commands, flags, enumerated choices (`--format`, `--status`, `--order`, …).
- Dynamic: after a source path is present on the argv being completed,
  - `--where <TAB>` → keys from cached `fields`
  - `--where user=<TAB>` → top values for `user`
  - `--logger <TAB>` → loggers from `meta` or `fields` (prefer `meta` levels/loggers if cheap)
- If `argcomplete` is missing: `completion` exits `64` with an install hint
  (`pip install 'slogger[cli]'` once published; locally `pip install -e '.[cli]'`).
- Keep `argcomplete` **off** the default import path of `slogger` and `slogger.tools`.

### D6. MCP wrapper

- Optional module callable as a stdio MCP server (exact SDK choice left to implementer;
  prefer a thin hand-rolled JSON-RPC shim or a small optional dep behind `[mcp]` if needed).
- Tools map 1:1 to `slogger.tools` functions: `meta`, `fields`, `query`, `summary`, `trace`,
  `tree`, `stats`, `failures`, `validate`, `context`, `diff`, `watch`, `tail_once`, `explain`.
- Arguments mirror the Python kwargs (filters as a JSON object isomorphic to
  `Filters.explain()["filters"]`).
- Return values are the same dicts/JSONL contracts as `--format json`.
- Must not import `slogger.cli` argparse.
- Packaging: either `python3 -m slogger.tools.mcp` or documented under `[mcp]` extra.
- **Prerequisite:** T0 memory fixes (B1, B2) and published schemas (T2) so agents do not OOM
  or guess shapes.

### D7. Docs and plan status

- User docs (`docs/cli.md`, `docs/api.md`, README) are the operator/agent reference.
- `docs/plans/cli.md` stays the product brief; P2 details live here.
- After P2 lands: mark this file **implemented**, bump CHANGELOG, refresh AGENTS.md deferred
  table (CLI P2 rows move out).

## Tasks

Order matters: T0 → T1 → T2 → T3 → T4 → T5 → T6.

### T0. Review warm-up (correctness + doc honesty)

- Fix B1–B4 in code with tests.
- Align `docs/cli.md` / argparse help with D4–D5 paging and duration units (partially done on
  the docs branch; finish any remaining help strings).
- Rewrite stale sketches in `docs/plans/cli.md` (see T6).

Acceptance: `watch --existing` on a multi-match file returns the first match without allocating
O(matches); `context` on a large synthetic stream stays O(neighbours + max_trace); `--grep '['`
exits 64; `watch --help` has no `--order`.

### T1. `explain`

- `Filters.explain()` + CLI `explain`.
- Eager `--grep` compile (shares B3).
- Tests: golden JSON for a representative flag set; relative `--since` resolves; bad tokens → 64.
- Export from `slogger.tools.__all__` if a free function is added; method needs no export.

### T2. Tool-output schemas

- Author `tool-output.schema.json` `$defs` from the frozen key sets above (plus nested row
  shapes from P1 handoff examples).
- `output_schemas()` / `validate_tool_output(kind, data)`.
- Tests: every aggregate fixture path used in `tests/test_tools_*.py` validates; list `_meta`
  from `query` validates.
- Package-data entry already covers `schemas/*.json`.

### T3. Fields sidecar cache

- Implement cache read/write + invalidation.
- Tests: hit/miss on mtime change; stdin never writes; filtered calls do not read unfiltered
  cache incorrectly.
- Wire CLI completion path (T4) to `cache=True`.

### T4. Completion + `[cli]` extra

- Add optional dependency; `completion` subcommand; argcomplete registration.
- Static tests without importing argcomplete on the default path (mock or skip if missing).
- Dynamic completion unit-tested with argv fixtures and a tiny log file.

### T5. MCP wrapper

- Stdio server exposing tools API.
- Round-trip test: call `meta` / `query` / `explain` through the server against fixtures.
- Document launch command in `docs/cli.md` and `docs/api.md`.

### T6. Documentation and plan status

- Update `docs/plans/cli.md` P2 section to “implemented” when done; point at this handoff until
  then.
- CHANGELOG Unreleased bullet per landed P2 item.
- AGENTS.md: move CLI P2 out of deferred; mention schemas path.

## Maintainer decisions still open

Defaults below are chosen so work can start; say so if you want them changed.

1. **MCP packaging** — in-tree `slogger.tools.mcp` + optional `[mcp]` extra vs a separate
   distribution. Default: in-tree module, optional extra only if an SDK dependency appears.
2. **`fields` cache default for CLI `fields` command** — default **on** for CLI, **off** for
   API (D3). Alternative: off everywhere until completion needs it.
3. **`explain` without sources** — allowed (D2). Alternative: require a source and sample one
   matching record (deferred; richer “explain with example”).
4. **Schema file layout** — one `tool-output.schema.json` with `$defs` (D4) vs one file per
   command. Default: one file.
5. **Forever `watch`** — not in P2 (keep `timeout > 0`). Revisit only if an agent workflow needs it.

## Start here

1. Land T0 (B1–B4 + doc/help alignment).
2. Implement T1 `explain` end-to-end (API + CLI + test) — smallest user-visible P2 command.
3. Freeze schemas (T2) from current JSON before any intentional shape change.
4. Cache (T3) then completion (T4).
5. MCP (T5) last, once contracts and memory behaviour are trustworthy.
