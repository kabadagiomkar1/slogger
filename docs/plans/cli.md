# Log tooling: core API and CLI

Status: P0 implemented; P1 planned. The P0 task breakdown and the binding resolutions for filter
syntax, cursors, ordering, trace reconstruction, and output contracts are in
[`cli-p0-handoff.md`](cli-p0-handoff.md). The P1 breakdown (`tree`, `stats`, `errors`,
`validate`, `context`, `diff`, `watch`, `--group-by`, `query --summary`, `--format table`,
`--order time`) is in [`cli-p1-handoff.md`](cli-p1-handoff.md). Where a handoff and this file
differ, the handoff wins.

## Goal

Read the JSONL that [`JSONFormatter`](../../src/slogger/formatters.py) writes and turn it into
answers: filter records, rebuild span trees, aggregate durations and errors, and compare runs.
Serve three consumers with one implementation:

- people at a terminal (`python -m slogger ...`)
- AI agents and scripts (`--format json`, bounded results, stable output contracts)
- future clients (a local web UI, a VS Code extension, an MCP server) that call the Python API

The record contract is already published in [`schema.py`](../../src/slogger/schema.py) and
[`log-record.schema.json`](../../src/slogger/schemas/log-record.schema.json). This tooling consumes
that contract; it does not change it.

## Decisions

| Question | Decision |
|---|---|
| Where does it live | Same repo and package: `slogger.tools` (core API) and `slogger.cli` (argparse layer). Split into a second distribution only if heavy dependencies arrive. |
| Dependencies | Pure stdlib for the core and the default renderers. Anything else (`argcomplete`, `rich`) goes behind an optional `[cli]` extra and must stay off the library import path. |
| Spans without `span.end` | Reported with `status="unknown"` and `duration_ms=null`; still rendered in `trace` and `tree`; counted separately in `stats`. |
| Apps that do not use spans | `--group-by <key>` (for example `request_id`) on `query`, `stats`, and `trace` groups records by any flat key. The tree degrades to a flat timeline when span fields are absent. |
| Autocomplete | Shell completion of commands and flags, then dynamic completion of `--where` keys and values driven by `fields`. Optional `[cli]` extra via `argcomplete`, after P0. An interactive TUI is deferred. |
| Entry point | `python -m slogger` now. A `slogger` console script is added when a PyPI name is chosen; `slogger` on PyPI is taken by an unrelated package. |

## Principles

- **Stream, never load.** Every reader is an iterator. `tail` and `query` must handle files larger
  than memory.
- **Tolerant input.** Skip lines that are not JSON or not objects, count them, keep going. Only
  `validate` treats them as failures.
- **One filter grammar.** `--level`, `--logger`, `--where`, `--grep`, `--since`, `--until`,
  `--span`, `--trace`, `--exclude-events`, `--limit` mean the same thing in every command.
- **Bounded by default for machines.** With `--format json`, list commands default to a limit and
  expose a cursor. An agent can always page; it can never be flooded.
- **Python API first.** Each command is a plain function in `slogger.tools` returning dicts or
  dataclasses. The CLI is a thin wrapper. Agent tooling wraps the same functions.
- **Same visual language.** Console output reuses the styling rules of
  [`ConsoleFormatter`](../../src/slogger/formatters.py): colour follows the TTY, `NO_COLOR`, and
  `FORCE_COLOR`; strings with spaces are quoted; span fields are dimmed.
- **Exit codes mean something.** `0` success, `1` matches found when `--fail-if-any` was given,
  `2` invalid input or schema errors, `3` timeout (`watch`), `64` usage error.

## Module layout

```text
src/slogger/tools/
  __init__.py     # public API re-exports
  reader.py       # iterate JSONL from paths, globs, rotated files, stdin, or in-memory lists
  filters.py      # parse --where / --level / --since into a predicate; explain()
  trace.py        # group by trace_id (or --group-by key), build span trees, pair start/end
  stats.py        # streaming counters, level/logger/span aggregates, percentiles, time buckets
  fields.py       # key discovery: types, cardinality, sample values, time span; small cache
  render.py       # console / table / json renderers behind one small interface
src/slogger/cli.py      # argparse commands; python -m slogger dispatches here
src/slogger/__main__.py
src/slogger/schemas/
  tool-output.schema.json   # (P2) contracts for trace tree, stats, fields output
tests/test_tools_*.py       # one file per module; test_cli.py drives argparse end to end
```

`slogger.tools` is importable without the `[cli]` extra. `slogger.cli` may import optional
packages lazily and degrade when they are absent.

## Input

- One or more paths or globs, read one after another in concatenation order (no timestamp merge
  in P0). Within a glob, rotated files (`app.log.2026-09-26`) sort before the live `app.log`.
- `-` reads stdin, which also makes `some_app 2>&1 | python -m slogger tail -` work.
- In-memory: every API function also accepts an iterable of dicts, so tests can pass the list
  returned by [`capture_logs()`](../../src/slogger/testing.py) without writing a file.
- Each record gets a stable id `file:line` (or `mem:index`) so later calls can refer back to it.

## Filter grammar

```text
--level LEVEL          minimum level; =LEVEL for an exact match
--logger NAME          prefix match on the logger name (stdlib hierarchy)
--where KEYOPVALUE     repeatable, compact token; OP is one of = != > < >= <= ~ !~ (regex)
--has KEY / --missing KEY   existence tests (repeatable)
--grep PATTERN         regex on message
--since / --until      absolute ISO-8601 or relative (10m, 2h, 1d)
--span NAME            records inside a span with that name
--trace ID             trace id or unique prefix
--group-by KEY         correlate on KEY instead of trace_id
--exclude-events       drop span.start and span.end
--limit N, --last N    cap results; --after CURSOR resumes a page
--fields a,b,c         project only these keys
--truncate N           cut long strings (exception, stack) to N characters
```

`--where` is intentionally one compact token with no boolean operators, so it can be tokenised
for shell completion without a parser. Multiple flags are ANDed. Comparison is driven by the type
of the record value; a missing key never matches (use `--missing`). Full rules are in the
handoff (D1). `ctx_`-prefixed collisions are matched by their emitted key.

## Commands

| Command | Purpose | Priority |
|---|---|---|
| `meta` | Orientation: files, sizes, record count, first/last timestamp, loggers, span names, level counts | P0 |
| `fields` | Keys with type, cardinality, sample values; `--key K` lists top values for one key | P0 |
| `query` | Filter records with limit and cursor paging (`--summary` is P1) | P0 |
| `trace` | One trace (or group) as a waterfall of spans with nested log lines | P0 |
| `tail` | Follow files or stdin; `--once --after CURSOR` returns new records and exits | P0 |
| `tree` | One line per trace: root span, span count, duration, status | P1 |
| `stats` | Counts by level/logger/span, duration percentiles, `--bucket` time series | P1 |
| `errors` | Group exceptions and failed spans by `error_type` and top frame | P1 |
| `validate` | Schema-check a file with `validate_log_record`; report bad lines | P1 |
| `context` | Records around one record: same trace, plus N neighbours in time | P1 |
| `diff` | Compare two inputs by level, message, or span histograms and percentiles | P1 |
| `watch` | Block until a matching record appears or `--timeout` elapses | P1 |
| `explain` | Print the normalised predicate for a set of filter flags | P2 |
| `completion` | Emit or install shell completion (`[cli]` extra) | P2 |

### Usage sketches

`meta` and `fields`

```bash
python -m slogger meta app.log
python -m slogger fields app.log
python -m slogger fields app.log --key user --top 20
```

```text
app.log  12 480 records  3 skipped  16:00:00Z -> 17:00:00Z
loggers: app, app.db, app.pay   spans: checkout, charge, validate_cart
INFO 11 900  WARNING 543  ERROR 37

key            type     distinct  present  sample
user           str      312       84%      ada, grace, linus
order_id       str      1 204     61%      42, 43, 44
duration_ms    float    2 408     19%      88.1, 41.2
```

`query`

```bash
python -m slogger query app.log --level ERROR --since 1h
python -m slogger query app.log --where order_id=42 --format json --limit 50
python -m slogger query app.log --where 'duration_ms>500' --where event=span.end
python -m slogger query app.log --grep timeout --summary
python -m slogger query app.log --level ERROR --fail-if-any       # CI gate
```

`trace`

```bash
python -m slogger trace app.log 9f2c
python -m slogger trace app.log --where order_id=42                # trace containing that record
python -m slogger trace app.log --group-by request_id abc          # app without spans
```

```text
trace 9f2c...ab  2026-09-26T16:23:56.100Z  total 412 ms  status=error

checkout                                        ok      410 ms   user=ada items=3
├─ 16:23:56.120  INFO     app.db   connected                  host=localhost
├─ validate_cart                                ok        8 ms
├─ charge                                       error   380 ms   order_id=42
│  ├─ 16:23:56.150  INFO     app.pay  charging               amount=99.0
│  └─ 16:23:56.520  ERROR    app.pay  charge failed          error_type=Timeout
└─ 16:23:56.530  WARNING  app      rolling back
```

`tail`

```bash
python -m slogger tail app.log                       # follow, survive rotation
python -m slogger tail app.log --level WARNING --exclude-events
python -m slogger tail app.log --once --after 'app.log:12480' --format json   # agent polling
some_app 2>&1 | python -m slogger tail -
```

`tree`, `stats`, `errors`

```bash
python -m slogger tree app.log --status error --slower-than 500ms
python -m slogger stats app.log --by logger
python -m slogger stats app.log --spans --bucket 1m
python -m slogger errors app.log --group error_type --show-trace
```

```text
span            count   p50     p95     p99     max    errors  unfinished
checkout        1 204   88 ms   310 ms  512 ms  1.9 s  12      1
charge          1 204   41 ms   270 ms  480 ms  1.8 s  12      0
```

`validate`, `context`, `diff`, `watch`

```bash
python -m slogger validate app.log                    # exit 2 on schema errors
python -m slogger context app.log --id app.log:5121 --before 20 --after 20
python -m slogger diff before.log after.log --by span --metric p95
python -m slogger watch app.log --where span=checkout --where event=span.end --timeout 30s
```

## Output contract

- `--format console` (default on a TTY): the formatter's line style, tables, and trees.
- `--format json` (default when stdout is not a TTY):
  - list commands (`query`, `tail`, `context`) write **JSONL**, one record per line, in the
    published `LogRecord` shape plus `_id`, followed by one `{"_meta": {...}}` control line that
    carries `schema_version`, `returned`, `skipped_lines`, `next_cursor`, and `warnings`
  - aggregate commands (`meta`, `fields`, `trace`, `tree`, `stats`, `errors`, `diff`, `validate`)
    write **one JSON object** with `schema_version`, the payload, and `next_cursor` when paged
  - errors go to stderr as one JSON object `{"error": code, "message": ..., "line": ...}`
- `--format table` (P1) for aggregates when a human wants columns but not colour.

Output schemas for the aggregate payloads are published as package data in P2, alongside the
record schema, so external tools and an MCP wrapper can validate them.

## Python API

```python
from slogger.tools import fields, meta, query, stats, tail, trace

info = meta("logs/app.log*")
keys = fields("app.log", top=10)
errors = query("app.log", level="ERROR", where=[("order_id", "=", "42")], limit=50)
tree = trace("app.log", trace_id="9f2c")
per_span = stats("app.log", by="span", bucket="1m")
new = tail("app.log", after=cursor, once=True)
```

Every function accepts a path, a list of paths or globs, `"-"`, or an iterable of dicts. Return
values are plain dicts and lists matching the JSON output, so the CLI and any agent wrapper are
serialisation-only.

## Unfinished spans

A `span.start` without a matching `span.end` in the input (crash, forgotten `end()`, file cut by
rotation) is kept:

- `trace`: rendered with `status=unknown` and no duration, marked visibly
- `tree`: counted in `spans`, status `unknown` if it is the root
- `stats --spans`: `unfinished` column
- `errors`: not counted as an error

## Autocomplete

Two tiers, both optional, both after P0.

1. **Static**: commands, flags, enumerated values (`--level`, `--format`). Provided through
   `argcomplete` in the `[cli]` extra; `python -m slogger completion --shell bash` prints the
   script.
2. **Dynamic**: when the command line already names a file, completing `--where <TAB>` offers keys
   from `fields`, and `--where user=<TAB>` offers that key's top values. `fields` must therefore be
   cheap on large inputs: scan at most N records by default and cache results in a small sidecar
   next to the file, invalidated by size and mtime.

The same `fields` primitive is the discovery step for agents and the key source for a future editor
extension.

## Scope by phase

**P0** — `reader`, `filters`, `fields`, `meta`, `query` (limit, cursor, projection),
`trace` (span tree, unfinished spans), `tail` (follow, rotation, `--once --after`), console and
JSON renderers, the Python API, `python -m slogger`, fixtures and tests for each module. Task
order and acceptance cases: [`cli-p0-handoff.md`](cli-p0-handoff.md).

**P1** — `tree`, `stats` (buckets, percentiles), `errors`, `validate`, `context`, `diff`, `watch`,
`--group-by`, `query --summary`, `--format table`, timestamp merge across files.

**P2** — `explain`, published output schemas, `completion` and dynamic key/value completion, an
MCP wrapper over `slogger.tools`.

## Out of scope

- Natural-language query translation (an agent's job, not the library's)
- Persistent index or database; stream first, index if files get large
- Remote or hosted log sources
- Interactive TUI or REPL
- Alternate input formats (logfmt, plain text)
- Changes to the log record schema

## Files to touch when P0 starts

- New: `src/slogger/tools/` package, `src/slogger/cli.py`, `src/slogger/__main__.py`
- `src/slogger/__init__.py`: no new exports required; `slogger.tools` is imported explicitly
- `pyproject.toml`: `[cli]` extra placeholder, `tests` already collected
- Tests: `tests/test_tools_reader.py`, `tests/test_tools_filters.py`, `tests/test_tools_trace.py`,
  `tests/test_tools_fields.py`, `tests/test_cli.py`
- Docs: README section "Reading logs", CHANGELOG under Unreleased, `AGENTS.md` layout table and the
  deferred list (CLI moves out of deferred)
