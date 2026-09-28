# CLI reference

Read JSONL logs written by slogger's `JSONFormatter`.

```bash
python3 -m slogger --help
python3 -m slogger <command> --help
```

There is no console-script entry point yet (`slogger` on PyPI is taken by an
unrelated package). Always invoke via `python3 -m slogger`.

Python equivalents of every command live in [`slogger.tools`](api.md#tools-api--sloggertools).
Design notes: [`plans/cli.md`](plans/cli.md).

---

## Commands at a glance

| Command | Purpose |
| --- | --- |
| `meta` | Summarise sources: counts, time range, loggers, spans, levels |
| `fields` | Discover keys and value distributions |
| `query` | Filter records (optional `--summary` / `--group-by`) |
| `explain` | Print the normalised filter predicate (no sources required) |
| `completion` | Print shell completion script (`[cli]` extra) |
| `trace` | Show one trace (or group) as a span tree |
| `tail` | Follow a file / stdin, or `--once` poll from a cursor |
| `tree` | List reconstructed traces (one line each) |
| `stats` | Aggregate record or span statistics |
| `errors` | Group error records and failed spans |
| `validate` | Validate JSONL against the log-record schema |
| `context` | Show a record with neighbours / same-trace context |
| `diff` | Compare stats between two source sets |
| `watch` | Wait until a matching record appears |

---

## Sources

Most commands take one or more **sources**:

```text
sources               Log files, globs, or - for stdin.
```

Examples:

```bash
python3 -m slogger meta app.log
python3 -m slogger query 'logs/*.log' --level ERROR
python3 -m slogger query a.log b.log --order time
some_app 2>&1 | python3 -m slogger tail -
```

- Globs expand with rotated files (`app.log.2026-09-26`) ordered before the live
  `app.log`.
- `-` reads stdin.
- Non-JSON / non-object lines are skipped and counted (except `validate`, which
  reports them as failures).

---

## Shared filters

These flags mean the same thing on every command that accepts them:

| Flag | Meaning |
| --- | --- |
| `--level LEVEL` | Minimum level (`INFO`, `ERROR`, … or a number). Use `=LEVEL` for an exact match (`--level =ERROR`) |
| `--logger NAME` | Logger name or prefix (`app` matches `app` and `app.pay`) |
| `--where KEYOPVALUE` | Compact filter; repeatable; operators `= != > < >= <= ~ !~` |
| `--has KEY` | Key must be present (repeatable) |
| `--missing KEY` | Key must be absent (repeatable) |
| `--grep PATTERN` | Regex matched against `message` |
| `--since` / `--until` | Absolute ISO-8601 or relative (`10m`, `2h`, `1d`) |
| `--span NAME` | Records whose active span name is `NAME` |
| `--trace ID` | Exact `trace_id` |
| `--exclude-events` | Drop `span.start` and `span.end` records |

`--where` examples:

```bash
--where user=ada
--where amount>=99
--where 'message~timeout'
--where error_type!=TimeoutError
```

Multiple filter flags are ANDed. A missing key never matches a `--where`
comparison (use `--missing`). Match `ctx_`-prefixed collisions by their emitted
key name.

### Shared output / paging (list-style commands)

| Flag | Meaning |
| --- | --- |
| `--format {console,json[,table]}` | Default: `console` on a TTY, else `json` |
| `--color` / `--no-color` | Force colour on or off |
| `--fields a,b,c` | Project only these keys |
| `--truncate N` | Cut long strings (`exception`, `stack`, …) to N characters |
| `--limit N` | Cap matching records. With `--format json`, default is `200` when unset; `--limit 0` means unlimited. Console default is unlimited |
| `--last N` | Keep only the final N matches (not with `--after`) |
| `--after ID` | Resume after this record id (`path:line`) |
| `--fail-if-any` | Exit `1` when at least one record matches |
| `--order {concat,time}` | `concat` (default) or timestamp merge across files |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | `--fail-if-any` matched |
| `2` | Data / I/O / schema error |
| `3` | `watch` timed out |
| `64` | Usage error |
| `130` | Interrupted |

### JSON output contract

With `--format json` (the default when stdout is not a TTY):

- **List** commands (`query`, `tail`, `context`) write JSONL records plus a
  trailing `{"_meta": {...}}` control line with `schema_version`, `returned`,
  `skipped_lines`, `next_cursor`, and `warnings`.
- For `query` / `tail --once`, when `--limit` is unset the JSON default is **200**
  (`--limit 0` = unlimited). Always read `_meta.next_cursor` when paging.
- **Aggregate** commands (`meta`, `fields`, `trace`, `tree`, `stats`, `errors`,
  `diff`, `validate`) write one JSON object with `schema_version`.
- Errors go to stderr as `{"error": code, "message": ...}`.

---

## `meta`

Summarise log sources: record counts, skipped lines, time range, loggers, span
names, and level histogram.

```bash
python3 -m slogger meta app.log
python3 -m slogger meta app.log --level WARNING --exclude-events
python3 -m slogger meta 'logs/*.log' --format json
```

Example console output:

```text
app.log  6 records  0 skipped  2026-09-26T16:00:00.000Z -> 2026-09-26T16:00:04.000Z
loggers: app, app.db, app.pay   spans: -
DEBUG 1  ERROR 1  INFO 3  WARNING 1
```

| Extra options | Meaning |
| --- | --- |
| Shared filters | Restrict which records are counted |
| `--format` | `console`, `json`, or `table` |
| `--order` | Kept for API parity; aggregates are order-invariant |

---

## `fields`

Discover keys (type, distinct count, presence, samples) or top values for one key.

```bash
python3 -m slogger fields app.log
python3 -m slogger fields app.log --key user --top 20
python3 -m slogger fields app.log --scan 10000 --logger app.pay
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--scan N` | `100000` | Max matching records to scan (`0` = unbounded) |
| `--key KEY` | none | Rank top values for this key instead of listing all keys |
| `--top N` | `10` | How many top values when `--key` is set (overview samples stay capped at 5) |

---

## `query`

Filter records. With `--summary` (or `--group-by`), emit aggregate counts instead.

```bash
python3 -m slogger query app.log --level ERROR
python3 -m slogger query app.log --where order_id=42 --format json --limit 50
python3 -m slogger query app.log --where 'amount>=99' --where user=ada
python3 -m slogger query app.log --grep timeout --exclude-events
python3 -m slogger query app.log --level ERROR --fail-if-any          # CI gate
python3 -m slogger query app.log --summary --group-by logger
python3 -m slogger query a.log b.log --order time --limit 50
python3 -m slogger query app.log --after 'app.log:100' --limit 50
```

| Extra options | Meaning |
| --- | --- |
| `--summary` | Aggregate counts instead of records |
| `--group-by KEY` | Group summary rows by `KEY` (implies `--summary`) |
| `--top N` | Cap summary groups (default `50`) |
| Shared filters + output / paging | See above |

---

## `explain`

Print how shared filter flags are interpreted. No log sources required.

```bash
python3 -m slogger explain --level ERROR --where user=ada --exclude-events
python3 -m slogger explain --since 10m --format json
```

Relative `--since` / `--until` are resolved to absolute UTC timestamps at explain
time. Invalid tokens (including bad `--grep`) exit `64`.

Python:

```python
from slogger.tools import Filters, Where

print(Filters(level_min=40, where=(Where("user", "=", "ada"),)).explain())
```

---

## `trace`

Show one trace as a waterfall of spans with nested log lines.

```bash
python3 -m slogger trace app.log aaaa
python3 -m slogger trace app.log aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --no-logs
python3 -m slogger trace app.log --where order_id=42
python3 -m slogger trace app.log --group-by request_id=abc
```

Positional arguments: `SOURCE [TRACE_ID]`. The trace id is a hex id or unique
prefix (≥ 4 characters). Alternatively omit the id and pass filters /
`--group-by KEY=VALUE` to select the group.

| Extra options | Meaning |
| --- | --- |
| `--no-logs` | Span skeleton only (no nested log lines) |
| `--group-by KEY=VALUE` | Reconstruct by field instead of `trace_id` |
| `--format` | `console` or `json` |

---

## `tail`

Follow a log file (survives rotation) or poll once from a cursor.

```bash
python3 -m slogger tail app.log                              # follow
python3 -m slogger tail app.log --level WARNING --exclude-events
python3 -m slogger tail app.log -n 20 --interval 0.5
python3 -m slogger tail app.log --once --after 'app.log:100' # agent poll
some_app 2>&1 | python3 -m slogger tail -
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--once` | off | Read new records since `--after` and exit |
| `-n` / `--lines` | `10` | Backlog lines before following (`0` disables) |
| `--interval` | `0.25` | Poll interval in seconds while following |
| Shared filters + output | | |

---

## `tree`

One line per reconstructed trace (or `--group-by` group).

```bash
python3 -m slogger tree app.log
python3 -m slogger tree app.log --status error --slower-than 500ms
python3 -m slogger tree app.log --sort duration --top 20
python3 -m slogger tree app.log --group-by request_id --format table
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--group-by KEY` | none | Correlate on `KEY` instead of `trace_id` |
| `--status` | none | Keep only `ok`, `error`, or `unknown` |
| `--slower-than DUR` | none | Keep traces with `duration_ms` greater than `DUR` (`400ms`, `1s`, …). A bare number is **seconds** (`500` → 500s) |
| `--sort` | `started` | `started` or `duration` |
| `--top N` | `50` | Max rows returned |

Unfinished spans (start without end) appear with `status=unknown` and no duration.

---

## `stats`

Aggregate record counts or span duration statistics.

```bash
python3 -m slogger stats app.log
python3 -m slogger stats app.log --group-by logger --format table
python3 -m slogger stats app.log --spans --bucket 1m
python3 -m slogger stats app.log --spans --top 20
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--group-by KEY` | none | Break aggregates down by key |
| `--spans` | off | Span-centric stats (counts, percentiles, unfinished) |
| `--bucket SIZE` | none | Time series buckets (`30s`, `1m`, `5m`, `1h`). CLI requires a unit; the Python API also accepts an int number of seconds |
| `--top N` | `50` | Cap groups |

Percentiles use nearest-rank over at most the first `max_samples` (default 100_000)
durations seen; when the cap hits, the payload sets `percentiles_capped` (early-record bias).
Full percentile tables are in JSON / `--format table`; console output stays compact.

---

## `errors`

Group error-level records and failed spans by `error_type` and top frame.
(Python API: `slogger.tools.failures`.)

```bash
python3 -m slogger errors app.log
python3 -m slogger errors app.log --top 10 --samples 5
python3 -m slogger errors app.log --show-trace --fail-if-any
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--top N` | `20` | Max groups |
| `--samples N` | `3` | Sample records kept per group |
| `--show-trace` | off | Include traceback text in samples |
| `--fail-if-any` | off | Exit `1` when any group matches |

---

## `validate`

Schema-check every line with `validate_log_record`. Exit `2` when invalid lines
are found.

```bash
python3 -m slogger validate app.log
python3 -m slogger validate app.log --max-diagnostics 20 --format json
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--max-diagnostics N` | `100` | Cap detailed diagnostics in the report |

Unlike other commands, malformed / non-schema lines are failures, not silent skips.

---

## `context`

Show one record together with neighbours and (by default) the rest of its trace.

```bash
python3 -m slogger context app.log --id 'app.log:42'
python3 -m slogger context app.log --id 'app.log:42' -B 5 -A 5
python3 -m slogger context app.log --id 'app.log:42' --no-same-trace
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--id ID` | required | Record id (`path:line`) |
| `-B` / `--before` | `10` | Neighbours before the anchor |
| `-A` / `--after-lines` | `10` | Neighbours after the anchor |
| `--no-same-trace` | off | Do not expand to the full same-trace window |
| `--fields` / `--truncate` | | Projection helpers |

Note: `--after` is the shared **cursor** flag on other commands; context uses
`-A` / `--after-lines` for neighbour count.

---

## `diff`

Compare aggregate stats between two source sets (before vs after).

```bash
python3 -m slogger diff before.log after.log
python3 -m slogger diff before.log after.log --spans --group-by span
python3 -m slogger diff 'run1/*.log' 'run2/*.log' --format table
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--group-by KEY` | none | Compare per-group breakdowns |
| `--spans` | off | Include span duration metrics |
| `--top N` | `50` | Cap compared groups |
| Shared filters | | Applied to both sides |

Positional arguments: `before` and `after` (paths or globs).

---

## `watch`

Block until a matching record appears, or until `--timeout`.

```bash
python3 -m slogger watch app.log --level ERROR --timeout 30s
python3 -m slogger watch app.log --where span=checkout --where event=span.end
python3 -m slogger watch app.log --existing --timeout 5s   # also scan current EOF
```

| Extra options | Default | Meaning |
| --- | --- | --- |
| `--timeout DUR` | `30s` | Give up after this duration (`timeout` must be &gt; 0). Exit code `3` on timeout |
| `--existing` | off | Also consider records already in the file |
| `--interval` | `0.25` | Poll interval in seconds |
| Single `source` | | One file or `-` |

`--order` is not supported on `watch` (follow semantics are concat-only).

Exit `0` on match, `3` on timeout.

---

## MCP, completion, and schemas

P2 items from [`plans/cli-p2-handoff.md`](plans/cli-p2-handoff.md) are landed
(T0–T6).

### MCP

```bash
python3 -m slogger.tools.mcp
```

JSON-RPC 2.0 over stdio (MCP `Content-Length` framing). Tools mirror
`slogger.tools` (`meta`, `query`, `explain`, …). Pass `filters` using the same
object shape as `Filters.explain()["filters"]`.

### `completion`

Requires the optional `[cli]` extra:

```bash
pip install -e '.[cli]'
alias slogger='python3 -m slogger'
eval "$(python3 -m slogger completion --shell bash)"
```

With a source file already on the command line, `--where <TAB>` offers keys from
cached `fields`, and `--where user=<TAB>` offers top values. `--logger <TAB>`
offers logger names from `meta`.

### Fields cache

`fields(..., cache=True)` may write `<path>.slogger-fields.json` for a single
unfiltered file overview (invalidated by size/mtime/`scan`). The Python API
defaults to `cache=False`; `python3 -m slogger fields` enables caching.
Validate aggregates in Python with:

```python
from slogger.tools import meta, output_schemas, validate_tool_output

validate_tool_output("meta", meta("app.log"))
schema = output_schemas()  # draft 2020-12 document with $defs
```


---

## End-to-end recipes

Orientation on a new file:

```bash
python3 -m slogger meta app.log
python3 -m slogger fields app.log
python3 -m slogger fields app.log --key error_type --top 20
```

Debug one failing order:

```bash
python3 -m slogger query app.log --where order_id=42 --exclude-events
python3 -m slogger trace app.log --where order_id=42
python3 -m slogger context app.log --id 'app.log:512' -B 20 -A 20
```

CI / alerting:

```bash
python3 -m slogger validate app.log
python3 -m slogger query app.log --level ERROR --fail-if-any
python3 -m slogger errors app.log --fail-if-any
python3 -m slogger watch app.log --level ERROR --timeout 60s
```

Compare two runs:

```bash
python3 -m slogger diff before.log after.log --spans --format table
python3 -m slogger stats after.log --spans --bucket 1m
```

Agent-friendly paging:

```bash
python3 -m slogger query app.log --level ERROR --format json --limit 50
# read next_cursor from the trailing _meta line, then:
python3 -m slogger query app.log --level ERROR --format json --limit 50 --after 'app.log:120'
python3 -m slogger tail app.log --once --after 'app.log:120' --format json
```
