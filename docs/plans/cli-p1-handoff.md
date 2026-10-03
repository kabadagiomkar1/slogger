> Historical design, superseded by the IXR-only tooling migration. Legacy tools, CLI, and MCP described here have been removed; this is not current usage guidance.

# P1 handoff: `slogger.tools` and `python3 -m slogger`

Historical implementation handoff. Baselines, findings, and proposed signatures
below describe that phase, not the current repository. For current behavior use
[the API reference](../api.md) and [CLI reference](../cli.md); Python-only rich
filters are documented in [typed predicates](../api.md#typed-python-predicates).
Historical precedence statements below apply only to that phase.

Implementation-ready breakdown of P1 from [`cli.md`](cli.md), written against the P0 code that
landed in `src/slogger/tools/` and `src/slogger/cli.py`. Where this file and `cli.md` or
[`cli-p0-handoff.md`](cli-p0-handoff.md) disagree, this file wins for P1 work. **P1 is
implemented.**

Scope: `tree`, `stats` (buckets, percentiles), `errors`, `validate`, `context`, `diff`, `watch`,
`--group-by`, `query --summary`, `--format table`, timestamp merging across files (`--order time`).

Out of scope (unchanged from `cli.md`): completion, `explain`, MCP wrapper, published tool-output
schemas, sidecar caches, `rich`/`argcomplete`, packaging changes, record-schema changes.

## Baseline (run 2026-09-27 on the P0 branch)

| Check | Command | Result |
|---|---|---|
| Interpreter | `python3 --version` | Python 3.12.3. `python` is not on `PATH`. `python3.10`, `python3.11`, `python3.13` are **not installed**; the 3.10/3.13 matrix in `AGENTS.md` cannot be run here. |
| Tests | `python3 -m pytest -q` | 143 passed (pytest 9.1.1) |
| Lint | `python3 -m ruff check src tests examples` | All checks passed (ruff 0.16.9) |
| Types | `python3 -m pyrefly check` | 0 errors, 9 warnings not shown (pyrefly 1.3.1) |
| CLI | `python3 -m slogger --help` | lists `query`, `meta`, `fields`, `trace`, `tail` |

All P1 tasks must keep these three checks green and add tests under `tests/`.

## Facts checked in the P0 code

| Area | Verified behaviour | Consequence for P1 |
|---|---|---|
| `Reader` (`tools/reader.py`) | Streams one source after another; `_id = "<source as given>:<line>"`; blank lines ignored; non-JSON / non-object lines counted in `skipped_lines`; `complete=False` holds back an unterminated last line; `after` validated at construction (`CursorError`, code `cursor_invalid`). `Reader.warnings` exists but is **never populated**. | Merge mode reuses `Reader` per source and finally populates `warnings`. |
| `resolve_sources` | A `str`/`PathLike` is one path; a sequence whose first item is a `Mapping` is one in-memory source; any other iterable is passed through **un-materialised**. | One-shot iterables break two-pass commands (see discrepancies). |
| In-memory labels | Every in-memory source is labelled `mem`; with two in-memory sources ids collide (`['mem:0', 'mem:0']` observed). | P1 labels the k-th in-memory source `mem` (k = 0) or `mem<k>` (k ≥ 1). |
| `Filters` (`tools/filters.py`) | Dataclass; compact `--where` grammar `KEYOPVALUE`, ops `!= >= <= !~ = > < ~`; missing key never matches; `--has`/`--missing`; `since`/`until` inclusive and drop unparseable timestamps; `exclude_events`. Contains a cached `_grep_re` field with `compare=True`, so two equal `Filters` compare unequal after one has matched. | Keep the grammar; set `compare=False` on the cache field (T1). |
| `query()` (`tools/query.py`) | Returns `Page(records, next_cursor, skipped_lines, warnings)`; `next_cursor` set only when `limit` was hit (also when the limit equals the exact remaining count); `last` uses a `deque`; `complete=False` always exposes a cursor. `warnings` always `[]`. | `Page` is reused unchanged by `context`, `tail_once`, merge mode. |
| `tail_once` / `follow` (`tools/tail.py`) | `tail_once` = `query(complete=False)` plus "always return a cursor" (returns `after` when nothing new). `follow` yields backlog (`lines`), then polls with `tail_once`, reopens on inode change or shrink, calls `on_reopen`, honours `stop()`. Stdin: single pass to EOF. | `watch` reuses `tail_once`/reopen logic, adds a deadline. |
| `trace()` (`tools/trace.py`) | Two passes over the sources: `find_trace_id` then `Reader` again. `build_trace` implements D5 of P0 (unfinished `unknown`, `duplicate_start/end`, `missing_parent`, `missing_start`, stable `(timestamp or "~", order)` sort). Span `fields` exclude `SCHEMA_KEYS`, `SPAN_FIELD_ORDER`, `event`, `_id`. `Trace.to_dict()` includes `schema_version: 1`. | `tree`, `stats --spans`, `errors` reuse `build_trace` with a new `keep_logs` switch. |
| `meta()` / `fields()` | Streaming counters; `fields` caps `scan` (100 000), distinct (10 000), samples (5); `meta` caps loggers/spans (1 000) and traces (10 000) with `_capped` flags. | Same capping style for groups, buckets, diagnostics. |
| `cli.py` | `_Parser.error` exits 64; `resolve_format` → `console` on TTY else `json`; `emit_error` → exit 2 with JSON on stderr in JSON mode; `write_page` writes JSONL then one `{"_meta": {...}}` line; `--fail-if-any` → 1; `tail` follow returns 130 on `KeyboardInterrupt`. `trace` takes `SOURCE... [TRACE_ID]` and treats a final `^[0-9a-fA-F]{4,32}$` token as the id. | New commands follow the same helpers. |
| Formatter / schema | `SPAN_FIELD_ORDER = (event, status, duration_ms, error_type, error, span, span_id, parent_span_id, trace_id)`; `validate_log_record` checks required keys, string types, `line` int, `event`/`status` enums, `duration_ms` number; it does **not** check timestamp format. `span.end` on error is logged at `ERROR` with `exception`. | `validate` reuses the validator unchanged; `errors` must not double-count failed `span.end` records. |
| Rotation | `TimedRotatingFileHandler(when="midnight", utc=True)`, suffix `%Y-%m-%d`; `resolve_sources` puts `app.log.<date>` before `app.log`. | Merge mode keeps this order for the tie-break index. |
| Fixtures | `tests/fixtures/logs/{basic,malformed,trace}.log`, `rotated/app.log{,.2026-09-25,.2026-09-26}`; `malformed.log` has no trailing newline (`.gitattributes -text`, `.gitignore` exception `!tests/fixtures/**/*.log`). | New fixtures go in the same directory and inherit both rules. |
| Packaging | No `[project.scripts]`, no `[cli]` extra, `slogger/__init__.py.__all__` does not export `tools`. | Unchanged in P1. |

## Discrepancies between P0 code and the P0 contract

| # | Observed | Contract | Resolution |
|---|---|---|---|
| 1 | `trace(generator, trace_id="aaaa")` returns an empty trace (`spans: []`, `status: ok`) because the second pass sees an exhausted iterator. | D4: "every API function also accepts an iterable of dicts". | **Fix in T1**: `resolve_sources` materialises any non-`Sequence` iterable into a list once (cost: whole iterable in memory; documented). |
| 2 | `--after nocolon` raises an uncaught `ValueError` with a traceback. | D7: usage errors exit 64 with `usage:` on stderr. | **Fix in T1**: CLI maps `ValueError` from `parse_id` to exit 64. |
| 3 | Two in-memory sources both produce `mem:0`. | D2: ids are stable per record. | **Fix in T1**: label `mem`, `mem1`, `mem2`, … by position among in-memory sources. Single-source behaviour unchanged. |
| 4 | `Filters` equality changes after `matches()` (regex cache). | Not stated; surprising for tests. | **Fix in T1**: `field(compare=False)`. |
| 5 | `_meta.warnings` is always `[]`; `Reader.warnings` is dead. | D7 lists `warnings`. | Keep the field; T2 starts populating it (`out_of_order`, `untimestamped`). |
| 6 | `trace SOURCE` where the source file name itself matches `^[0-9a-f]{4,32}$` and has no directory (e.g. a file called `deadbeef`) is taken as a trace id. | Not covered. | Documented limitation; prefix with `./`. No change. |
| 7 | `cli.md` Python API block shows `query("app.log", level="ERROR", where=[...])`, `tail("app.log", after=cursor, once=True)`, and `stats(..., by="span")`. | Actual API is `query(..., filters=Filters(...))`, `tail_once(...)`, and `stats` does not exist. | **Fix in T12**: rewrite the block against the real signatures. |
| 8 | `cli.md` sketches `context --before 20 --after 20`. | `--after` is the shared cursor flag. | Replaced by `-B/-A` (D8). |
| 9 | `AGENTS.md` says "Export new public names from `slogger/__init__.py`". | P0 kept tools under `slogger.tools.__all__`. | **Fix in T12**: add an `AGENTS.md` sentence: tools/CLI names are exported from `slogger.tools.__all__`, never from the package root. |
| 10 | `tools/errors.py` is the exception module (`ToolError`, `CursorError`). | `cli.md` names a command `errors`. | Command stays `errors`; implementation lives in `tools/failures.py` as `failures()` so `slogger.tools.errors` keeps meaning the exception module (D6). |

## Binding decisions

### D1. Compatibility and public API

Preserved unchanged: `Filters`, `Where`, `parse_where`, `Page`, `Reader` constructor arguments,
`SpanNode`, `Trace`, `build_trace`, `find_trace_id`, `trace`, `render_trace`, `tail_once`,
`follow`, `meta`, `fields`, `query` (existing keyword arguments), compact `--where`, JSONL +
`_meta` convention, `_id`/cursor semantics for `--order concat`, exit codes `0/1/2/64/130`.

New public names, all exported from `slogger.tools.__all__` (not from `slogger/__init__.py`):

```python
# reader.py
Order = Literal["concat", "time"]
def Reader(..., order: Order = "concat")          # new keyword, default preserves P0
def Reader.iter_lines() -> Iterator[tuple[str, int, str]]   # (source_label, line_no, raw_text) for validate

# query.py
def query(..., order: Order = "concat")            # new keyword
def summary(sources, *, filters=None, after=None, group_by: str | None = None,
            top: int = 50, order: Order = "concat") -> dict[str, Any]

# grouping.py (new)
def group_value(record: Mapping[str, Any], key: str) -> tuple[str, object] | None
    # -> (type_name, normalised_value) or None when key is missing
def parse_group_selector(token: str) -> tuple[str, str]    # "KEY=VALUE" for trace --group-by

# spans.py (new): shared streaming reconstruction without a framework
@dataclass
class SpanCollector:
    def __init__(self, *, keep_logs: bool, max_groups: int = 10_000) -> None
    def add(self, record: Mapping[str, Any], group_key: str) -> None
    def finish(self) -> Iterator[tuple[str, Trace]]         # group_key -> Trace (built via build_trace)
    groups_seen: int; groups_capped: bool

def build_trace(records, trace_id, *, keep_logs: bool = True) -> Trace   # new keyword only

# tree.py
def tree(sources, *, filters=None, group_by=None, status=None, slower_than_ms=None,
         sort="started", top=50, max_groups=10_000, order="concat") -> dict[str, Any]

# stats.py
def stats(sources, *, filters=None, group_by=None, spans=False, bucket=None,
          top=50, max_groups=10_000, max_buckets=10_000, max_samples=100_000,
          order="concat") -> dict[str, Any]
def percentile(sorted_values: Sequence[float], p: float) -> float   # nearest-rank, exact
def parse_bucket(text: str) -> int                                  # seconds
def parse_duration_ms(text: str) -> float                           # "500ms", "1.5s", "2m"

# failures.py  (CLI command: errors)
def failures(sources, *, filters=None, top=20, samples=3, show_trace=False,
             max_groups=1_000, order="concat") -> dict[str, Any]

# validate.py
def validate(sources, *, max_diagnostics=100) -> dict[str, Any]

# context.py
def context(sources, *, record_id: str, before=10, after=10, same_trace=True,
            filters=None, max_trace=1_000, order="concat") -> Page

# diff.py
def diff(before, after, *, filters=None, group_by=None, spans=False, top=50,
         order="concat") -> dict[str, Any]

# watch.py
@dataclass
class WatchResult:
    matched: dict[str, Any] | None; timed_out: bool; elapsed_ms: float; records_seen: int
def watch(path, *, filters=None, timeout=30.0, existing=False, interval=0.25,
          stop=None, on_reopen=None, clock=time.monotonic, sleep=time.sleep) -> WatchResult

# render.py
def render_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], *,
                 max_width: int = 40) -> str
```

Command syntax added to `python3 -m slogger` (all reuse `add_filter_args`; output flags noted):

```text
query   ... [--summary] [--group-by KEY] [--top N] [--order concat|time]
tree    SOURCE... [--group-by KEY] [--status ok|error|unknown] [--slower-than DUR] [--sort started|duration] [--top N] [--order ...]
stats   SOURCE... [--group-by KEY] [--spans] [--bucket 30s|1m|5m|1h|1d] [--top N] [--order ...]
errors  SOURCE... [--top N] [--samples N] [--show-trace] [--order ...]
validate SOURCE... [--max-diagnostics N]                 (no filter flags, no --order)
context SOURCE... --id ID [-B N] [-A N] [--no-same-trace] [--order ...]
diff    BEFORE AFTER [--group-by KEY] [--spans] [--top N] [--order ...]   (BEFORE/AFTER: one path or glob each)
watch   SOURCE [--timeout DUR] [--existing] [--interval SEC]
trace   ... [--group-by KEY=VALUE]
--format now accepts table for: query --summary, meta, fields, tree, stats, errors, validate, diff
```

New error codes (all exit 2, JSON on stderr in JSON mode): `record_not_found` (`context --id`
not in input) and `eof_without_match` (`watch -` reached EOF). `validate` signals invalid input
with exit 2 and its normal payload on **stdout**, not an error object. Unsupported flag
combinations are usage errors (64), never error codes. New exit code `3`: `watch` timed out
(payload on stdout).

CLI handling added in T1: `ValueError` from `Reader`/`parse_id` → 64; `ToolError` → 2 for every
command.

### D2. Timestamp merging and cursors (`--order time`)

- Default stays `--order concat` (P0 behaviour, byte-for-byte).
- `--order time` is a **streaming k-way merge**: one `Reader` per resolved source, one buffered
  head record per source, a heap keyed by `(ts_key, source_index, line_no)`.
  - `ts_key` = `parse_timestamp(record["timestamp"])` as an aware UTC `datetime` (`Z`, offsets,
    naive-as-UTC, 0–9 fractional digits all normalise the same). Comparison is on the datetime,
    never on the raw string.
  - Missing/unparseable timestamp: the record inherits the `ts_key` of the previous record from
    the **same source** (or `datetime.min` UTC if it is the first), so it stays adjacent to its
    physical neighbour. Counted per source; reported as `untimestamped:<label>:<n>` in `warnings`.
  - Ties: `source_index` (position in the resolved source list, so rotated siblings precede the
    live file), then `line_no`. Fully deterministic.
- **Assumption enforced, not silently violated**: each source is expected to be non-decreasing by
  timestamp. When a source's next record has `ts_key` lower than the last record emitted from
  that source, the merge does **not** buffer; the record is emitted the next time that source's
  head is the heap minimum (i.e. immediately after the preceding record from the same source,
  possibly after later-timestamped records from other sources). Each such record increments an
  `out_of_order:<label>:<n>` warning. Memory stays one record per source.
- Applies to: `query`, `query --summary`, `tail --once`, `meta`, `fields`, `tree`, `stats`,
  `errors`, `context`, `diff`, `trace` (both passes). Not accepted by: `validate` (physical
  order only), `tail` follow mode, `watch` (single source) — passing `--order time` there is 64.
- **Merge cursor**: with `--order time`, `next_cursor` is `time;<id_0>;<id_1>;...;<id_k>` with one
  `_id` per resolved source in source order; a source with nothing consumed yet contributes
  `<label>:0`. Resume (`--after time;...`) requires the same number of sources in the same order
  (labels must match exactly), otherwise `cursor_invalid`. Each per-source `_id` is validated
  like a P0 cursor (line ≤ line count). Because each source is consumed monotonically and the
  heap only ever emits a source's head, the per-source positions exactly capture the emitted set:
  no record is lost or repeated on resume, given unchanged files.
  - A P0 concat cursor passed with `--order time`, or a `time;` cursor passed with
    `--order concat`, is `cursor_invalid`.
  - Source labels containing `;` are rejected with usage 64 in time mode.
  - `--last N` with `--order time` works (deque over the merged stream); `next_cursor` is `null`
    as in P0.
- Stdin (`-`) may participate in a merge as one source (its head is pulled lazily); `--after`
  with stdin remains 64. One-shot iterables are materialised (D1). In-memory sources use their
  `mem`/`mem<k>` labels in the cursor.
- Rotation/truncation limitations are identical to P0: cursors die when a file is renamed or
  truncated. No persistent index, no inode tracking.
- Timestamp precision is unchanged (millisecond schema); the parser accepts higher precision.

### D3. Shared filtering and grouping

Three stages, named consistently in code and docs:

1. **Record filters** (`Filters`): applied to individual records.
2. **Selection**: which traces/groups are included in span-aware output.
3. **Aggregate filters**: applied to reconstructed spans/groups (`--status`, `--slower-than`,
   `--span`).

Span-aware commands are `tree`, `stats --spans`, `errors` (failed-span part), `trace`, `diff --spans`.

- A trace/group is **selected** when at least one of its records matches `Filters`. Once
  selected, reconstruction consumes **every** record of that trace/group, regardless of
  `--level`, `--grep`, `--where`, `--has`, `--missing`, `--logger`, `--exclude-events`. So
  filtering can never remove a `span.start` and invent an unfinished span.
- `--since`/`--until` on span-aware commands: selection as above; additionally `stats --spans`
  and `tree --slower-than/--status` count a span only if its **anchor timestamp** (start, else
  end) lies inside the window. Spans with no parseable anchor are counted only when no window is
  given.
- `--span NAME` on span-aware commands is an aggregate filter on span name (nodes with other names
  are still reconstructed for structure but not counted/listed). On record commands it stays a
  record filter.
- `--trace ID` selects exactly that trace.
- `--exclude-events` on `tree` and `stats --spans` is a usage error (64): it cannot affect
  reconstruction and would only confuse. On `errors` it applies to the error-record part only.

Compatibility matrix (✓ accepted, 64 = usage error, – = flag not defined):

| Flag | query | summary | tree | stats | errors | validate | context | diff | watch | trace |
|---|---|---|---|---|---|---|---|---|---|---|
| record filters | ✓ | ✓ | select | select / ✓ records | ✓ / select | – | neighbours only | ✓ | ✓ | select |
| `--exclude-events` | ✓ | ✓ | 64 | 64 with `--spans` | ✓ | – | ✓ | 64 with `--spans` | ✓ | 64 |
| `--limit` | ✓ | 64 | – | – | – | – | – | – | – | – |
| `--last` | ✓ | 64 | – | – | – | – | – | – | – | – |
| `--after CURSOR` | ✓ | ✓ | – | – | – | – | 64 | – | 64 | – |
| `--fields/--truncate` | ✓ | 64 | – | – | – | – | ✓ | – | ✓ | – |
| `--fail-if-any` | ✓ | ✓ (matched > 0) | – | – | ✓ (any group) | – | – | – | – | – |
| `--group-by KEY` | ✓ (implies summary) | ✓ | ✓ | ✓ | – | – | – | ✓ | – | `KEY=VALUE` |
| `--order time` | ✓ | ✓ | ✓ | ✓ | ✓ | 64 | ✓ | ✓ | 64 | ✓ |
| `--format table` | 64 unless `--summary` | ✓ | ✓ | ✓ | ✓ | ✓ | 64 | ✓ | 64 | 64 |
| stdin `-` | ✓ | ✓ | ✓ (buffered spans) | ✓ | ✓ | ✓ | ✓ | one side only | ✓ | ✓ |

**`--group-by KEY` value normalisation** (`grouping.group_value`):

| Record value | Group key |
|---|---|
| key missing | not grouped; counted in `ungrouped` |
| `None` | `("null", None)` |
| `bool` | `("bool", True/False)` (distinct from `1`/`"true"`) |
| `int`/`float` | `("number", float(value))` so `1` and `1.0` share a group |
| `str` | `("str", value)` |
| `list`/`dict` | `("array"/"object", json.dumps(value, sort_keys=True, separators=(",",":")))` |

Output row for a group: `{"value": <original scalar or compact JSON string>, "type": <type name>, ...}`.
Ordering: by `count` desc, then `type` asc, then JSON of `value` asc. Limits: at most
`max_groups` (10 000) distinct groups are tracked; further new values are counted in
`ungrouped_capped` and `groups_capped: true`; output shows the top `--top` (50).

**`query --group-by KEY`** implies `--summary` and produces the summary payload with a `groups`
list. **`stats --group-by KEY`** groups records (and, with `--spans`, spans by the value on
their `span.start` record, else `span.end`). **`tree --group-by KEY`** replaces `trace_id` with the
group key as the unit of reconstruction. **`trace --group-by KEY=VALUE`** reconstructs the single
group whose normalised value equals `VALUE` (compared with `=` rules from D1 of P0); its output
has `trace_id: null`, `group: {"key": KEY, "value": VALUE}`, and `matched_traces` = distinct
`trace_id`s inside the group. Records with no `span_id` become group-level `logs`; spans from
several traces become several roots. A group containing multiple traces is therefore rendered as
a forest, never merged into one tree.

### D4. `tree` and span aggregation

- Reconstruction rules are P0 D5 via `build_trace(..., keep_logs=False)`: `logs` lists stay
  empty, everything else identical (unfinished → `unknown`, `duplicate_start/end`,
  `missing_parent` → orphan root, `missing_start`, status precedence, `duration_ms` only when
  exactly one root).
- `SpanCollector` streams records once, bucketing them by group key (`trace_id`, or
  `--group-by` value). Records without a group key are dropped for span purposes and counted as
  `ungrouped`. Memory is O(total span events + 1 dict per record while the record is needed):
  with `keep_logs=False` non-event records are only used to mark a trace as selected and are not
  retained. Interleaved traces stay open until EOF; that is the cost of not assuming trace
  locality. `max_groups` (10 000) bounds it: further new groups are counted in `total` but not
  reconstructed; `groups_capped: true`.
- Span identity: `(group_key, span_id)`. The same `span_id` in two traces is two spans.
- Row per trace/group: `trace_id` (or `group`), `root_span` (name of first root by start), `roots`,
  `spans` (nodes), `completed` (start and end), `failed` (status error), `unfinished` (start, no
  end), `missing_start`, `status`, `started`, `ended`, `duration_ms`, `warnings` count.
- Aggregate filters: `--status`, `--slower-than DUR` (trace `duration_ms` > threshold; traces
  with `null` duration excluded), `--span NAME` (trace kept only if it has a node with that name;
  counts still cover the whole trace).
- Sorting: `--sort started` (default; `(started or "~", first_seen_order)`) or `--sort duration`
  (desc, `null` last). Output bounded by `--top` (50); `total` and `returned` reported;
  `truncated: total > returned or groups_capped`.

### D5. `stats` and `query --summary`

Counts (every one is defined; nothing is inferred):

| Field | Meaning |
|---|---|
| `records` | records matching `Filters` (post-filter). |
| `spans` | distinct `(group, span_id)` nodes seen in selected traces (start or end or log with span_id). |
| `completed` | nodes with both start and end. |
| `failed` | nodes with `status == "error"`. |
| `unfinished` | nodes with start and no end. |
| `missing_start` | nodes with end and no start. |
| `duration_ms.count` | nodes whose `duration_ms` (from `span.end`) is a finite non-negative number, bool excluded. |
| `invalid_durations` | nodes with an end but a `duration_ms` that fails that test. |

Percentiles: **exact nearest-rank** on the stored sample: for `n` values sorted ascending,
`p` in (0, 100], index `k = max(1, ceil(p/100 * n))`, result `values[k-1]`. `p50`, `p95`, `p99`
plus `min`, `max`, `mean` (arithmetic, unrounded float). Memory: one `list[float]` per group,
capped at `max_samples` (100 000) values; beyond the cap further durations update `count`,
`min`, `max`, `mean` (streaming) but are not stored, and the group reports
`"percentiles_capped": true` — the percentiles are then over the first 100 000 durations and are
labelled approximate in table output (`~`). Empty sample: all percentile fields `null`, `count 0`.

Worked examples (independently computed):

| Sample | p50 | p90 | p95 | p99 | mean |
|---|---|---|---|---|---|
| `[5, 100, 380, 410]` | 100 | 410 | 410 | 410 | 223.75 |
| `[1..10]` | 5 | 9 | 10 | 10 | 5.5 |
| `[7]` | 7 | 7 | 7 | 7 | 7.0 |
| `[3, 1]` | 1 | 3 | 3 | 3 | 2.0 |

Buckets: `--bucket` accepts `<n>s|m|h|d` (`30s`, `1m`, `5m`, `1h`, `1d`). Boundary =
`floor(epoch_seconds / size) * size`, UTC, rendered as `YYYY-MM-DDTHH:MM:SS.000Z`. Records are
assigned by their own timestamp; spans by anchor timestamp (start, else end). Missing/invalid
timestamp → bucket `null`, listed last. Empty buckets are omitted (no zero-fill). At most
`max_buckets` (10 000) buckets per group; beyond, new buckets are counted in `buckets_capped`
and dropped.

`stats` payload:

```json
{"schema_version": 1, "order": "concat", "records": 6, "skipped_lines": 0,
 "group_by": null, "spans": false, "bucket": null,
 "totals": {"records": 6, "levels": {"INFO": 3, "DEBUG": 1, "WARNING": 1, "ERROR": 1}},
 "groups": [], "groups_capped": false, "ungrouped": 0, "warnings": []}
```

With `--spans`, `totals` gains `spans, completed, failed, unfinished, missing_start,
invalid_durations, duration_ms: {count,min,max,mean,p50,p95,p99, percentiles_capped}` and
`groups` lists one row per span name (same fields plus `value`). With `--group-by KEY`, `groups`
rows carry `value`/`type`. With `--bucket`, every row (totals and groups) gains
`"buckets": [{"start": "...Z"|null, "records": n, ...span fields when --spans}]`.

`query --summary`: counts **all** matches from the start (or from `--after`), never a page.
`--limit`, `--last`, `--fields`, `--truncate` with `--summary` → 64. `--fail-if-any` → exit 1
when `matched > 0`. `--group-by` adds `groups`. Implementation is `summary()` which calls the
same internals as `stats()` (`_Accumulator`) so numbers cannot disagree. Payload:

```json
{"schema_version": 1, "order": "concat", "matched": 3, "skipped_lines": 0,
 "levels": {"INFO": 1, "WARNING": 1, "ERROR": 1}, "loggers": {"app.pay": 3},
 "first_id": "tests/fixtures/logs/basic.log:3", "last_id": "tests/fixtures/logs/basic.log:5",
 "first_timestamp": "2026-09-26T16:00:02.000Z", "last_timestamp": "2026-09-26T16:00:03.000Z",
 "group_by": null, "groups": [], "groups_capped": false, "ungrouped": 0, "warnings": []}
```

`loggers` is bounded to the top 20 by count.

### D6. `errors` (module `tools/failures.py`, function `failures`)

- **Error record**: `level_number(level) >= 40` **or** `exception` present, **and** `event != "span.end"`.
- **Failed span**: a reconstructed node with `status == "error"` (from selected traces). Failed
  `span.end` records are therefore counted once, as spans, never as records.
- **Group identity** `(kind, error_type, frame)`:
  - `kind`: `record` or `span`.
  - `error_type`: record `error_type` if a non-empty string; else the class name from the last
    non-blank line of `exception` (text before the first `:`; whole line if no colon); else
    `"unknown"`.
  - `frame`: innermost `File "<path>", line <n>` match in `exception` rendered as `<basename>:<n>`;
    else `<record.file>:<record.line>` when both present; else `"?"`.
- The tool **counts records/spans per group**; it does not claim two records are one incident.
  `count`, `traces` (distinct `trace_id`s, cap 10 000 per group with `traces_capped`),
  `first_seen`/`last_seen` (min/max parseable timestamps), `samples` (first `--samples` (3)
  records as `{"_id", "timestamp", "logger", "message" (truncated to 200)}`), and with
  `--show-trace` a `trace_ids` list (first `--samples` distinct ids). `--show-trace` never renders
  trees.
- Sorting: `count` desc, `last_seen` desc (`null` last), then identity asc. `max_groups` (1 000)
  tracked, `groups_capped` beyond; `--top` (20) shown; `total_groups` reported.
- `--fail-if-any` → exit 1 when `total_groups > 0`.

Payload:

```json
{"schema_version": 1, "order": "concat", "records_scanned": 14, "skipped_lines": 0,
 "error_records": 2, "failed_spans": 1, "total_groups": 3, "returned": 3, "groups_capped": false,
 "groups": [{"kind": "record", "error_type": "TimeoutError", "frame": "pay.py:48", "count": 2,
             "traces": 0, "first_seen": "...", "last_seen": "...",
             "samples": [{"_id": "...", "timestamp": "...", "logger": "app.pay", "message": "charge failed"}],
             "trace_ids": []}],
 "warnings": []}
```

### D7. `validate`

- Uses `Reader.iter_lines()` (new, T1): yields `(label, line_no, text)` for every **non-blank**
  physical line, honouring the P0 file/stdin/`complete` handling but performing no JSON parsing.
  Other commands keep using the tolerant record iterator; their behaviour does not change.
- Classification per line: `not_json` (`json.JSONDecodeError`), `not_object` (parsed but not a
  `dict`), `schema` (`validate_log_record` raised; message = its text). In-memory sources: non-
  `Mapping` items are `not_object`, mappings are schema-checked, `line_no` is the index.
- Blank/whitespace-only lines: ignored, not counted (P0 rule). Unterminated final line of a
  regular file: validated (file is complete). Line numbers are physical, 1-based, identical to
  `_id`.
- Totals: `lines` (non-blank), `valid`, `invalid`, `kinds: {not_json, not_object, schema}`, per
  source too. Diagnostics list bounded by `--max-diagnostics` (100) with `diagnostics_capped`;
  **counting continues to EOF** regardless.
- No timestamp-format check (the validator has none). No filters, no `--order`.
- Exit precedence: 64 (usage) > 2 (`file_not_found`/`permission_denied`) > 2 (`invalid > 0`,
  payload on **stdout**) > 0.

Payload:

```json
{"schema_version": 1, "sources": [{"path": "tests/fixtures/logs/invalid.log", "lines": 8, "valid": 1, "invalid": 7}],
 "lines": 8, "valid": 1, "invalid": 7, "kinds": {"not_json": 1, "not_object": 2, "schema": 4},
 "diagnostics": [{"_id": "tests/fixtures/logs/invalid.log:2", "kind": "schema",
                  "message": "log record field 'timestamp' must be a str"}],
 "diagnostics_capped": false}
```

### D8. `context`

- Syntax: `context SOURCE... --id ID [-B N] [-A N] [--no-same-trace]`. `-B/--before` and
  `-A/--after-lines` default 10. The shared `--after CURSOR` is **not** defined on `context`.
- Anchor: the record whose `_id == ID` in the resolved input (label match + line). Not found →
  `record_not_found` (2). `ID` malformed → 64.
- Neighbours: the `N` records **matching `Filters`** immediately before and after the anchor in
  the chosen `--order` (physical concat order by default; merged order with `--order time`).
  Filters do not apply to the anchor or to same-trace records.
- Same-trace: when the anchor has a string `trace_id` and `--no-same-trace` is absent, all records
  with that `trace_id` (cap `max_trace` 1 000 in reading order, `trace_capped` flag). Anchor
  without `trace_id`: same-trace part is empty, `_meta.trace_id: null`.
- Combine: union by `_id`; sort by reading order key `(source_index, line_no)` (concat) or the
  merge key (time). Anchor record gains `"_anchor": true`. Output is JSONL + `_meta`
  (`anchor`, `trace_id`, `before`, `after`, `trace_records`, `trace_capped`, `returned`,
  `skipped_lines`, `next_cursor: null`, `warnings`). No pagination.
- Memory: `deque(N)` before the anchor, `N` after, plus the capped same-trace list. Single pass
  when the anchor is found before EOF; if the anchor is the last record the pass still ends at
  EOF. Stdin and one-shot iterables: allowed (materialised for iterables; stdin single pass).
- Invalid timestamps do not matter in concat order; in time order they follow D2.

### D9. `diff`

- `diff BEFORE AFTER`: each side is one path or glob (a glob expands to a merged/concatenated
  source set on that side). Same `Filters`, `--group-by`, `--spans`, `--order` applied to both.
- Relative `--since/--until` are resolved to absolute instants **once** before either side is read
  and the same instants are applied to both.
- Computation: `stats()` on each side (identical parameters) → totals and groups; aligned by group
  `(type, value)`. Groups only on one side go to `added` (after only) / `removed` (before only)
  with their own row. Metrics compared: `records`; with `--spans`: `spans, completed, failed,
  unfinished, duration_ms.{count,min,max,mean,p50,p95,p99}`.
- Per metric: `{"before": a, "after": b, "abs": b - a, "pct": (b - a) / a * 100}`; `pct` is
  `null` when `a == 0` or either side is `null`; `abs` is `null` when either side is `null`.
  `approximate: true` on a row when either side had `percentiles_capped`.
- Ordering: `totals` first; `groups` sorted by `(type, value)` asc; `added`/`removed` likewise;
  bounded by `--top` (50) with `truncated`. No significance claims anywhere in output or docs.

Payload:

```json
{"schema_version": 1, "order": "concat", "group_by": null, "spans": false,
 "before": {"sources": ["a.log"], "records": 6}, "after": {"sources": ["b.log"], "records": 8},
 "totals": {"records": {"before": 6, "after": 8, "abs": 2, "pct": 33.33333333333333}},
 "groups": [], "added": [], "removed": [], "truncated": false, "warnings": []}
```

### D10. `watch`

- Default: **only records arriving after the watch starts** satisfy it (start at EOF, like
  `follow(lines=0)`). `--existing` first scans the whole file; an existing match returns
  immediately with `elapsed_ms` ≈ 0.
- One source only (file or `-`). Globs/multiple → 64. `--order time` → 64. `--after` → 64.
- File loop: deadline = `clock() + timeout`; each iteration runs `tail_once(complete=False)` from
  the current cursor, applies rotation/truncation reopen exactly as `follow`, checks `stop()`,
  then sleeps `min(interval, remaining)`. When `clock() >= deadline` before a match → timeout.
  Partial lines are held back by `tail_once`; a match on a partial line is only recognised once
  its newline arrives. A quiet file therefore times out precisely at the deadline.
- Stdin: a daemon thread reads lines into a `queue.Queue`; the main loop waits with
  `queue.get(timeout=remaining)`; EOF without a match → `timed_out=False, matched=None` and CLI
  exit 2 with error code `eof_without_match`. This keeps `--timeout` working even though
  `sys.stdin.readline()` blocks.
- Boundary: a record that matches on the same poll in which the deadline passes counts as a match
  (records are checked before the deadline test).
- Results: `WatchResult(matched, timed_out, elapsed_ms, records_seen)`. CLI: match → JSONL record
  then `{"_meta": {"schema_version": 1, "matched": true, "elapsed_ms": ..., "records_seen": n}}`,
  exit 0; timeout → only the `_meta` line with `"matched": false`, exit **3** (stdout, not an
  error); data error 2; usage 64; `KeyboardInterrupt` 130. Console mode prints the matching line
  or `watch: timed out after 30.0s` on stderr.
- `--timeout` accepts `30`, `30s`, `2m`, `0.5`; ≤ 0 → 64. Default `30s`.
- Tests inject `clock` and `sleep` (fake monotonic clock advanced by the fake sleep) so no test
  sleeps for real.

### D11. Output and resource bounds

- **JSON**: aggregates are one object with `schema_version: 1`; list commands (`context`,
  `watch`) write JSONL + `_meta`. All caps surface as `*_capped`/`truncated` booleans and the
  totals still count everything scanned; partial aggregates are never presented as complete.
  Empty results are full payloads with zero counts (examples per command in the task sections).
  Errors: `{"error": code, "message": ...}` on stderr, exit 2.
- **Table** (`--format table`, stdlib only, no colour): `render_table(rows, columns)` computes
  column widths from header and cells, truncates cells to `max_width` (40) with `...`, left-aligns
  strings and right-aligns numbers, prints header, a dash rule, rows; zero rows → header, rule,
  `(no rows)`. Row order equals JSON order. Approximate percentiles are prefixed `~`. Supported:
  `query --summary`, `meta`, `fields`, `tree`, `stats`, `errors`, `validate`, `diff`; elsewhere 64.
- **Bounded output vs bounded memory**: `--top` bounds what is printed; `max_groups`,
  `max_buckets`, `max_samples`, `max_trace`, `max_diagnostics` bound memory. Reaching a memory cap
  sets the matching `*_capped` flag; reaching an output cap sets `truncated` (with `total` and
  `returned`). Both continue scanning to EOF.

## Fixtures

Existing (reused unchanged): `basic.log`, `malformed.log`, `trace.log`, `rotated/`. New files under
`tests/fixtures/logs/`, written by hand in T1 (all `INFO`, `file=g.py`, `func=f`, `line=1` unless
stated; timestamps UTC):

`grouped.log` — 8 records for `--group-by request_id`:

| line | request_id | message | extra |
|---|---|---|---|
| 1 | `"r1"` | `a` | |
| 2 | `"r1"` | `b` | `level: ERROR` |
| 3 | `"r2"` | `c` | |
| 4 | *(missing)* | `d` | |
| 5 | `null` | `e` | |
| 6 | `["r1"]` | `f` | |
| 7 | `7` | `g` | |
| 8 | `"r1"` | `h` | `trace_id: "a"*32`, `span_id: "1"*16`, `event: span.start`, `span: "job"` |

Expected `group_value` groups: `("str","r1")` count 3 (lines 1, 2, 8), `("str","r2")` 1,
`("null",None)` 1, `("array",'["r1"]')` 1, `("number",7.0)` 1; `ungrouped` 1 (line 4). Order:
`r1` (3), then ties at 1 sorted by `(type, value)`: `array '["r1"]'`, `null`, `number 7.0`,
`str r2`.

`interleaved/a.log` and `interleaved/b.log` (messages are the ids used below):

```text
a.log: a1 10:00:00.000Z | a2 10:00:02.000Z | a3 10:00:04.000Z | a4 10:00:01.000Z   (a4 out of order)
b.log: b1 10:00:01.000Z | b2 10:00:03.000Z | b3 10:00:03.000Z | b4 (no timestamp key)
```

(date `2026-09-26`). Expected `--order time` sequence: `a1 b1 a2 b2 b3 b4 a3 a4`; warnings
`["out_of_order:tests/fixtures/logs/interleaved/a.log:1", "untimestamped:tests/fixtures/logs/interleaved/b.log:1"]`.
Concat order: `a1 a2 a3 a4 b1 b2 b3 b4`. Merge cursor after 3 records:
`time;tests/fixtures/logs/interleaved/a.log:2;tests/fixtures/logs/interleaved/b.log:1`.

`durations.log` — 12 spans `work`, each its own trace (`trace_id` = hex digit repeated 32 times,
`span_id` = same digit ×16), start and end pairs, `logger=job`:

| span | start ts | duration_ms | note |
|---|---|---|---|
| 1..5 | `12:00:0N.000Z` (N = span) | 1,2,3,4,5 | bucket `12:00` |
| 6..10 | `12:01:0N.000Z` | 6,7,8,9,10 | bucket `12:01` |
| 11 | `12:02:00.000Z` | `"fast"` | `invalid_durations` |
| 12 | `12:02:01.000Z` | `-1` | `invalid_durations` |

Span 3's end has `status: error`, `error_type: ValueError`, `error: bad`, level `ERROR`. Expected
`stats --spans`: `spans 12, completed 12, failed 1, unfinished 0, missing_start 0,
invalid_durations 2, duration_ms.count 10, min 1, max 10, mean 5.5, p50 5, p95 10, p99 10`.
`--bucket 1m`: `12:00:00.000Z` → 5 spans, `12:01:00.000Z` → 5, `12:02:00.000Z` → 2 (count of
valid durations 0 there).

`invalid.log` — 9 physical lines, line 8 blank, trailing newline present:

```text
1 {"timestamp": "2026-09-26T19:00:00.000Z", "level": "INFO", "logger": "v", "message": "ok", "file": "v.py", "func": "f", "line": 1}
2 {"timestamp": 1, "level": "INFO", "logger": "v", "message": "ts", "file": "v.py", "func": "f", "line": 2}
3 {"level": "INFO", "logger": "v", "message": "missing"}
4 not json
5 [1]
6 "str"
7 {"timestamp": "2026-09-26T19:00:00.000Z", "level": "INFO", "logger": "v", "message": "line", "file": "v.py", "func": "f", "line": "7"}
8
9 {"timestamp": "2026-09-26T19:00:00.000Z", "level": "INFO", "logger": "v", "message": "event", "file": "v.py", "func": "f", "line": 9, "event": "span.begin"}
```

Expected: `lines 8, valid 1, invalid 7, kinds {not_json 1, not_object 2, schema 4}`; diagnostics
ids `:2 schema`, `:3 schema` (message starts `log record missing required key(s)`), `:4 not_json`,
`:5 not_object`, `:6 not_object`, `:7 schema`, `:9 schema`.

`errors.log` — 7 records (`logger=app`, `file=pay.py`, date `2026-09-26`):

| line | timestamp | level | message | extras |
|---|---|---|---|---|
| 1 | `20:00:00.000Z` | ERROR | `charge failed` | `exception` = `Traceback (most recent call last):\n  File "/srv/app/pay.py", line 48, in charge\n    raise TimeoutError("boom")\nTimeoutError: boom`, `line: 48` |
| 2 | `20:00:01.000Z` | ERROR | `charge failed` | same exception text, `line: 48` |
| 3 | `20:00:02.000Z` | ERROR | `no details` | no `exception`, no `error_type`, `line: 60` |
| 4 | `20:00:03.000Z` | WARNING | `recovered` | `exception` = `Traceback (most recent call last):\n  File "/srv/app/a.py", line 3, in g\nValueError: nope`, `line: 5` |
| 5 | `20:00:04.000Z` | INFO | `fine` | `line: 6` |
| 6 | `20:00:06.000Z` | CRITICAL | `down` | `error_type: "DiskFull"`, `line: 70` |
| 7 | `20:00:05.000Z` | ERROR | `span.end` | `event: span.end`, `status: error`, `error_type: TimeoutError`, `error: boom`, `span: charge`, `span_id: "2"*16`, `trace_id: "b"*32`, `duration_ms: 12.0`, `line: 9`; no `exception` key |

Expected `failures()`: `error_records 5` (lines 1, 2, 3, 4, 6), `failed_spans 1` (line 7 creates
a `missing_start` node with `status error`). Groups sorted by `count` desc, then `last_seen`
desc, then identity:

1. `record / TimeoutError / pay.py:48` — count 2, last_seen `20:00:01.000Z`
2. `record / DiskFull / pay.py:70` — count 1, last_seen `20:00:06.000Z`
3. `span / TimeoutError / pay.py:9` — count 1, last_seen `20:00:05.000Z` (no `exception`, so the frame falls back to `file:line` of the `span.end` record)
4. `record / ValueError / a.py:3` — count 1, last_seen `20:00:03.000Z`
5. `record / unknown / pay.py:60` — count 1, last_seen `20:00:02.000Z`

Fixture generation: write files by hand or via a throwaway script kept out of the repo; commit the
resulting files. Keep expected values in the tests exactly as listed here.

## Tasks

Regression checks after every task: `python3 -m pytest -q`, `python3 -m ruff check src tests examples`,
`python3 -m pyrefly check`. Each task also adds the listed focused test file.

### T1. P0 compatibility fixes, shared helpers, new fixtures

Scope: `tools/reader.py`, `tools/filters.py`, `tools/render.py`, `cli.py`, new `tools/grouping.py`,
fixtures above, `tests/test_tools_reader.py`, `tests/test_cli.py`, new `tests/test_tools_grouping.py`,
`tests/test_tools_render.py`. Depends on nothing.

Inspect/change: `resolve_sources`, `Reader._iter_memory`, `Reader._validate_cursor`,
`Filters._grep_re`, `emit_error`, every `_cmd_*` `except` block, `render.py`.

Deliverables:
- `resolve_sources` materialises non-`Sequence` iterables (`list(iterable)`); `Sequence` inputs untouched.
- In-memory labels `mem`, `mem1`, …; `_validate_cursor` accepts those labels.
- `Filters._grep_re = field(default=None, init=False, repr=False, compare=False)`.
- CLI: `ValueError` raised by `Reader`/`parse_id`/`parse_where`/`level_number`/`parse_relative_or_iso`
  → usage 64 (one helper `_usage_error(prog, message, stderr)` replaces the repeated prints);
  `ToolError` → 2 everywhere.
- `Reader.iter_lines()` per D7; `parse_duration_ms`, `parse_bucket` (in `tools/stats.py` stub or
  `tools/timeparse.py`, pick `tools/timeparse.py` and re-export later); `render_table` per D11;
  `grouping.group_value` and `parse_group_selector` per D3.
- Fixtures: `grouped.log`, `interleaved/a.log`, `interleaved/b.log`, `durations.log`,
  `invalid.log`, `errors.log`.

Acceptance:
- `trace((r for r in Reader(TRACE)), trace_id="aaaa").spans[0].span == "checkout"` (P0 discrepancy 1 fixed).
- `[r["_id"] for r in Reader([[{"m":1}], [{"m":2}]])] == ["mem:0", "mem1:0"]`; `Reader([[...],[...]], after="mem1:0")` yields nothing from the second source and raises nothing.
- `main(["query", BASIC, "--after", "nocolon"])` → 64, stderr starts with `usage:`, no traceback.
- `Filters(grep="x") == Filters(grep="x")` after one has matched.
- `list(Reader(MALFORMED).iter_lines())` → 7 tuples (blank line 2 skipped) with line numbers `[1, 3, 4, 5, 6, 7, 8]`; the last text has no trailing newline.
- `parse_duration_ms("500ms") == 500.0`, `"1.5s" == 1500.0`, `"2m" == 120000.0`, `"x"` raises `ValueError`; `parse_bucket("1m") == 60`, `"30s" == 30`, `"1h" == 3600`, `"1d" == 86400`, `"2w"` raises.
- `group_value({"k": 1}, "k") == ("number", 1.0)`; `{"k": True}` → `("bool", True)`; `{"k": None}` → `("null", None)`; `{"k": [1]}` → `("array", "[1]")`; `{}` → `None`.
- `parse_group_selector("request_id=r1") == ("request_id", "r1")`; `"request_id"` raises.
- `render_table([{"a": "x", "n": 1}], ["a", "n"])` → three lines: header `a  n`, rule, row with `n` right-aligned; `render_table([], ["a"])` ends with `(no rows)`; a 60-char cell is cut to 37 chars + `...`.
- All P0 tests still pass unchanged (143 → 143 + new).

Exclusions: no new commands, no `--order`, no span collector.

Prompt: "Implement T1 of `docs/plans/cli-p1-handoff.md`: fix the four P0 discrepancies (materialise one-shot iterables in `resolve_sources`, unique `mem<k>` labels, `ValueError` → exit 64 in `cli.py`, `compare=False` on `Filters._grep_re`), add `Reader.iter_lines()`, `tools/timeparse.py` (`parse_duration_ms`, `parse_bucket`), `render_table` in `tools/render.py`, `tools/grouping.py` (`group_value`, `parse_group_selector`), and the six new fixtures exactly as specified. Add the listed tests. Do not add commands or `--order`. Keep pytest, ruff, and pyrefly green."

### T2. `--order time` merge and merge cursors

Scope: `tools/reader.py` (new `MergedReader` used when `order="time"`), `tools/query.py`,
`tools/tail.py` (`tail_once` passes `order`), `tools/meta.py`, `tools/fields.py`,
`tools/trace.py` (both passes), `cli.py` (`--order` on query/meta/fields/trace/tail --once),
`tests/test_tools_merge.py`. Depends on T1.

Contract: D2. `Reader(sources, after=None, complete=True, order="concat")` keeps P0 behaviour;
`order="time"` returns records in merged order, populates `warnings`, and exposes
`cursor() -> str` (`time;...`). `query(..., order=...)` sets `Page.next_cursor` to the merge
cursor when `limit` is hit and `Page.warnings` from the reader.

Acceptance (`A="tests/fixtures/logs/interleaved/a.log"`, `B=".../b.log"`):
- `query([A, B], order="time")` messages `a1 b1 a2 b2 b3 b4 a3 a4`; `warnings == ["out_of_order:"+A+":1", "untimestamped:"+B+":1"]`; concat order unchanged.
- `query([A, B], order="time", limit=3).next_cursor == f"time;{A}:2;{B}:1"`; resuming with that cursor and `limit=3` gives `b2 b3 b4`, then `a3 a4` with `next_cursor` `null`. Concatenating the three pages equals the full merged list (no loss, no repeat).
- `query([A, B], order="time", after=f"{A}:2")` → `CursorError`; `query([A, B], after=f"time;{A}:2;{B}:1")` (concat) → `CursorError`; `query([A], order="time", after=f"time;{A}:2;{B}:1")` → `CursorError` (source count mismatch).
- `query([A, B], order="time", last=2).records` messages `a3 a4`, `next_cursor None`.
- `--order time` on `validate`/`watch`/`tail` follow → 64 (asserted after those commands exist; T7/T10 re-check).
- `meta([A, B], order="time")["records"] == 8`; `trace(TRACE, trace_id="aaaa", order="time")` equals the concat result.
- Mixed precision: in-memory records with `2026-09-26T10:00:00Z` and `2026-09-26T10:00:00.000500+00:00` merge with the `+00:00` one second.
- Rotated glob in time mode yields `r1..r6` and no warnings.

Exclusions: no timestamp merge for `follow`/`watch`, no persistent index, no change to the record schema.

Prompt: "Implement T2 of `docs/plans/cli-p1-handoff.md`: add `order: Literal['concat','time']` to `Reader`, `query`, `tail_once`, `meta`, `fields`, `trace`, and a `--order` flag on those CLI commands. Implement a heap-based streaming merge with inherited timestamps for untimestamped records, `out_of_order`/`untimestamped` warnings, and `time;<id>;<id>` cursors validated per source. Concat behaviour must stay byte-identical. Add `tests/test_tools_merge.py` with the acceptance cases."

### T3. Shared span collection and `--group-by` on `trace`

Scope: new `tools/spans.py` (`SpanCollector`), `tools/trace.py` (`build_trace(keep_logs)`,
`trace(group_by=...)`), `cli.py` (`trace --group-by KEY=VALUE`), `tests/test_tools_spans.py`,
`tests/test_tools_trace.py`. Depends on T1 (grouping), T2 (order plumbing).

Contract: D3, D4. `SpanCollector.add(record, group_key)` stores span events (and logs only when
`keep_logs`) per group and tracks `selected` per group when a record matches the selection
predicate supplied to `finish()`; `finish()` yields `(group_key, Trace)` for selected groups
using `build_trace`. Memory caps per D4.

Acceptance:
- `build_trace(records, "a"*32, keep_logs=False)` equals the P0 result except every `logs == []`.
- `SpanCollector(keep_logs=False)` fed all of `trace.log` yields 3 groups; group `b*32` trace has `status unknown`; group `c*32` warnings contain `missing_parent:4444444444444444`.
- Selection: feeding `trace.log` with predicate `Filters(level_min=40)` selects only `a*32` (the ERROR `span.end`), and its `checkout` root still has `started` and `status ok` (the DEBUG start was not filtered away).
- `max_groups=2` on `trace.log`: `groups_seen == 3`, `groups_capped True`, two traces returned.
- `trace(GROUPED, group_by=("request_id", "r1"))`: `trace_id None`, `group == {"key": "request_id", "value": "r1"}`, one root `job` (`status unknown`), group-level `logs` messages `["a", "b"]`, `matched_traces 1`.
- CLI `trace GROUPED --group-by request_id=r1 --format json` → exit 0, `group.value == "r1"`; `trace GROUPED aaaa --group-by request_id=r1` → 64; `--group-by request_id` (no `=`) → 64; value with no matching records → `trace_not_found` (2).
- P0 `trace` tests unchanged.

Exclusions: no `tree`/`stats` commands yet.

Prompt: "Implement T3 of `docs/plans/cli-p1-handoff.md`: add `keep_logs` to `build_trace`, create `tools/spans.py` with `SpanCollector` (per-group span event buffering, selection predicate, `max_groups` cap), and add `group_by=(key, value)` to `trace()` plus `--group-by KEY=VALUE` on the CLI. Follow D3/D4 exactly; keep all existing trace tests passing."

### T4. `tree`

Scope: new `tools/tree.py`, `cli.py`, `tests/test_tools_tree.py`, `tests/test_cli.py`. Depends on T3.

Contract: D4 payload:

```json
{"schema_version": 1, "order": "concat", "group_by": null, "total": 3, "returned": 3,
 "truncated": false, "groups_capped": false, "ungrouped": 0, "skipped_lines": 0,
 "traces": [{"trace_id": "aaaa...", "group": null, "root_span": "checkout", "roots": 1, "spans": 2,
             "completed": 2, "failed": 1, "unfinished": 0, "missing_start": 0, "status": "error",
             "started": "2026-09-26T18:00:00.000Z", "ended": "2026-09-26T18:00:00.410Z",
             "duration_ms": 410.0, "warnings": 0}],
 "warnings": []}
```

Acceptance (`TRACE`):
- Default: 3 rows in order `a*32` (started 18:00), `b*32` (18:01), `c*32` (18:02). Row `a`: `spans 2, completed 2, failed 1, unfinished 0, status error, duration_ms 410.0`. Row `b`: `spans 1, unfinished 1, status unknown, duration_ms null`. Row `c`: `roots 2, spans 2, completed 1, missing_start 1, warnings 2, status ok, duration_ms null`.
- `--status error` → only `a`; `--slower-than 400ms` → only `a`; `--slower-than 500ms` → none with `total 0`.
- `--sort duration` → `a` first, then the two `null` durations in started order.
- `--top 1` → `returned 1`, `total 3`, `truncated true`.
- `--span charge` → only `a`.
- `--group-by request_id` on `GROUPED` → one row with `group == {"key": "request_id", "value": "r1"}`, `spans 1`, `unfinished 1`; `ungrouped 1`.
- `--exclude-events` → 64. Empty input (`[]`) → `total 0`, `traces []`.
- Table format: columns `trace, root_span, spans, failed, unfinished, status, duration_ms, started`.

Prompt: "Implement T4 of `docs/plans/cli-p1-handoff.md`: `tools/tree.py` `tree()` built on `SpanCollector(keep_logs=False)`, with `--status`, `--slower-than`, `--span`, `--sort`, `--top`, `--group-by`, `--order`, JSON and table output, and the CLI subcommand. Use the D4 payload and the acceptance cases verbatim."

### T5. `stats`, `query --summary`, `--group-by` on `query`

Scope: new `tools/stats.py` (`_Accumulator`, `percentile`, `stats`), `tools/query.py`
(`summary`), `cli.py`, `tests/test_tools_stats.py`, `tests/test_cli.py`. Depends on T3.

Contract: D5.

Acceptance:
- `percentile([5,100,380,410], 50) == 100`, `95 → 410`; `percentile([1..10], 95) == 10`, `50 → 5`; `percentile([7], 99) == 7`; `percentile([3,1] sorted, 50) == 1`.
- `stats(BASIC)["totals"] == {"records": 6, "levels": {"INFO": 3, "DEBUG": 1, "WARNING": 1, "ERROR": 1}}`.
- `stats(DURATIONS, spans=True)["totals"]` matches the fixture table (`spans 12`, `failed 1`, `invalid_durations 2`, `duration_ms.count 10`, `p50 5`, `p95 10`, `mean 5.5`); `groups` has one row `value "work"` with the same numbers.
- `stats(DURATIONS, spans=True, bucket="1m")["totals"]["buckets"]` starts `["2026-09-26T12:00:00.000Z" → spans 5, duration_ms.count 5, p50 3]`, `["...12:01..." → 5, p50 8]`, `["...12:02..." → spans 2, duration_ms.count 0, p50 null]`.
- `stats(TRACE, spans=True)["totals"]["duration_ms"]` → `count 4, p50 100, p95 410, mean 223.75`; `unfinished 1`, `missing_start 1`, `failed 1`, `spans 5`.
- `stats(GROUPED, group_by="request_id")["groups"]` rows in the fixture order with counts `3,1,1,1,1`; `ungrouped 1`.
- `max_samples=3` on `DURATIONS`: `percentiles_capped True`, `count 10`, `max 10`, `p50 2` (over the first three durations 1, 2, 3 in reading order).
- `summary(BASIC, filters=Filters(where=(Where("user","=","ada"),)))` equals the D5 example payload.
- CLI: `query BASIC --summary --format json` → one object with `matched 6`; `--summary --limit 2` → 64; `--group-by request_id` on `GROUPED` implies summary and returns `groups`; `--summary --fail-if-any` → 1 with matches, 0 with `--level CRITICAL`; `stats DURATIONS --spans --bucket 1m --format table` prints a `bucket` column; `stats --spans --exclude-events` → 64; `--bucket 2w` → 64.
- Empty input: `stats([])["totals"]["records"] == 0`, `duration_ms` all `null` when `spans=True`.

Prompt: "Implement T5 of `docs/plans/cli-p1-handoff.md`: `tools/stats.py` with an `_Accumulator` (records, span counts per D5, exact nearest-rank percentiles with a `max_samples` cap, UTC-floored buckets), `stats()` and `summary()` sharing that accumulator, `query --summary`/`--group-by` in the CLI, and the `stats` subcommand with JSON and table output. Match every number in the acceptance list."

### T6. `errors` command (`tools/failures.py`)

Scope: new `tools/failures.py`, `cli.py`, `tests/test_tools_failures.py`, `tests/test_cli.py`. Depends on T3.

Contract: D6.

Acceptance (`ERRORS="tests/fixtures/logs/errors.log"`):
- `failures(ERRORS)` → `error_records 5`, `failed_spans 1`, `total_groups 5`, groups in the fixture order; group 1 `count 2`, `samples` length 2 with `_id`s `:1` and `:2`, `frame "pay.py:48"`, `error_type "TimeoutError"`.
- `failures(ERRORS, samples=1)` → one sample per group; `show_trace=True` → group `span / TimeoutError / pay.py:9` has `trace_ids == ["b"*32]`.
- `failures(BASIC)` → `error_records 1` (line 5: level ERROR, `error_type TimeoutError`, no `exception`, frame falls back to `pay.py:48`), `failed_spans 0`.
- `failures(TRACE)` → `error_records 0` (the only ERROR record is a `span.end`), `failed_spans 1`; its `exception` text contains no `File "` line, so the group is `span / TimeoutError / shop.py:9`.
- `top=2` → `returned 2`, `total_groups 5`; `max_groups=2` → `groups_capped True`.
- CLI: `errors ERRORS --format json` exit 0; `--fail-if-any` → 1; `errors BASIC --level CRITICAL --fail-if-any` → 0 with `total_groups 0`; table columns `kind, error_type, frame, count, traces, last_seen`.
- `import slogger.tools.errors` still exposes `ToolError`; `slogger.tools` has no attribute named `errors` that is a function.

Prompt: "Implement T6 of `docs/plans/cli-p1-handoff.md`: `tools/failures.py` with `failures()` grouping error records (level ≥ 40 or `exception`, excluding `span.end`) and failed spans by `(kind, error_type, frame)` per D6, bounded samples/groups, `--show-trace`, and the `errors` CLI subcommand. Do not shadow `slogger.tools.errors`."

### T7. `validate`

Scope: new `tools/validate.py`, `cli.py`, `tests/test_tools_validate.py`, `tests/test_cli.py`. Depends on T1.

Contract: D7.

Acceptance:
- `validate(INVALID)` equals the D7 payload (7 diagnostics in line order).
- `validate(INVALID, max_diagnostics=2)` → `diagnostics` length 2, `diagnostics_capped True`, totals unchanged.
- `validate(MALFORMED)` → `lines 7, valid 5, invalid 2, kinds {not_json 1, not_object 1}` (line 8 unterminated is validated).
- `validate([{"message": "x"}, 5])` → `not_object 1`, `schema 1`, ids `mem:0`, `mem:1`.
- `validate(BASIC)` → `invalid 0`; CLI exit 0. `validate INVALID` → exit 2 with payload on stdout; `validate nope.log --format json` → exit 2, stderr `file_not_found`, stdout empty; `validate INVALID --order time` → 64; `validate INVALID --level ERROR` → 64 (flag undefined).
- Console output: one line per diagnostic `tests/fixtures/logs/invalid.log:4: not_json: ...` then `8 lines, 1 valid, 7 invalid`.

Prompt: "Implement T7 of `docs/plans/cli-p1-handoff.md`: `tools/validate.py` using `Reader.iter_lines()` and `validate_log_record`, classifying `not_json`/`not_object`/`schema`, with bounded diagnostics that never stop counting, per-source and total counts, exit 2 when invalid > 0, and JSON/console/table output. Do not add filters, `--order`, or timestamp checks."

### T8. `context`

Scope: new `tools/context.py`, `cli.py`, `tests/test_tools_context.py`, `tests/test_cli.py`. Depends on T2.

Contract: D8.

Acceptance:
- `context(TRACE, record_id=f"{TRACE}:4", before=1, after=1)` → `_id`s `:1 :2 :3 :4 :5 :6 :7` (same trace `a*32` supplies 1–7; neighbours 3 and 5 are already included); anchor `:4` has `_anchor True`; `_meta.trace_records 7`.
- `context(TRACE, record_id=f"{TRACE}:9", before=2, after=2, same_trace=False)` → `:7 :8 :9 :10 :11`.
- `context(BASIC, record_id=f"{BASIC}:3", before=1, after=1, filters=Filters(level_min=30))` → ids `[":3", ":4"]`: no record before the anchor is WARNING or above, the first matching record after it is `:4`, and `basic.log` has no `trace_id`.
- `context(TRACE, record_id=f"{TRACE}:9", max_trace=1)` → `trace_capped True`.
- Missing id → `ToolError("record_not_found")`; `record_id="bad"` → `ValueError` (CLI 64); `--after` flag on `context` → argparse 64.
- `context([A, B], record_id=f"{B}:2", before=1, after=1, order="time")` → `a2 b2 b3` (merged neighbours), while concat order gives `b1 b2 b3`.
- CLI JSONL ends with `_meta` containing `"anchor"`, `"next_cursor": null`.

Prompt: "Implement T8 of `docs/plans/cli-p1-handoff.md`: `tools/context.py` `context()` returning a `Page` with the anchor (`_anchor: true`), N filtered neighbours before/after in the chosen order, and the capped same-trace records, deduplicated and sorted by reading order; CLI flags `--id`, `-B/--before`, `-A/--after-lines`, `--no-same-trace`, no `--after` cursor."

### T9. `diff`

Scope: new `tools/diff.py`, `cli.py`, `tests/test_tools_diff.py`, `tests/test_cli.py`. Depends on T5.

Contract: D9.

Acceptance:
- `diff(A_LOG, B_LOG)` (interleaved a/b) → `totals.records == {"before": 4, "after": 4, "abs": 0, "pct": 0.0}`.
- `diff(BASIC, GROUPED)` → `records before 6 after 8 abs 2 pct 33.33…`.
- `diff(TRACE, DURATIONS, spans=True)` → `totals.spans before 5 after 12`; `duration_ms.p50 before 100 after 5 abs -95 pct -95.0`; `failed before 1 after 1 abs 0 pct 0.0`.
- `diff(BASIC, GROUPED, group_by="request_id")` → `groups []`, `removed []`, `added` has 5 rows ordered by `(type, value)` asc: `array '["r1"]'`, `null`, `number 7.0`, `str "r1"`, `str "r2"`.
- Zero baseline: `diff([], BASIC)` → `records before 0 after 6 abs 6 pct null`.
- Relative window: with `now` fixed via `Filters` built by the CLI once, both sides receive the same `since`; test by passing `filters=Filters(since=T)` and asserting both `before.records` and `after.records` reflect it.
- CLI: `diff BASIC GROUPED --format table` prints `metric, before, after, abs, pct`; three positionals → 64.

Prompt: "Implement T9 of `docs/plans/cli-p1-handoff.md`: `tools/diff.py` `diff()` that runs `stats()` on two source sets with identical parameters, aligns totals and groups, computes `abs`/`pct` with `null` on zero baseline or missing metrics, marks `approximate` when percentiles were capped, and lists `added`/`removed` groups; CLI `diff BEFORE AFTER`."

### T10. `watch`

Scope: new `tools/watch.py`, `cli.py`, `tests/test_tools_watch.py`, `tests/test_cli.py`. Depends on T1 (uses `tail_once`).

Contract: D10.

Acceptance (all with an injected fake clock/sleep; no real waiting):
- Quiet file, `timeout=1.0`, `interval=0.25`: `timed_out True`, `matched None`, `elapsed_ms == 1000.0`, four polls observed.
- File that gains a matching line on the second poll: `matched["message"]` equals it, `timed_out False`, `records_seen 1` (or 2 if a non-matching line preceded it).
- Partial line `{"message":"go"` present at start; completed on poll 3 → match on poll 3, not earlier.
- Rotation between polls (rename + new file with a matching line) → match from the new file, `on_reopen` called once.
- `existing=True` on `BASIC` with `Filters(grep="stopped")` → immediate match, zero sleeps.
- `existing=False` on `BASIC` with the same filter and no appends → timeout.
- Stdin: feed a `io.StringIO`-backed fake with two lines → match on the second; empty stdin → `eof_without_match` (`ToolError`), CLI exit 2.
- `stop()` returning `True` on poll 2 → `WatchResult(matched=None, timed_out=False)`; the CLI does not use `stop` and returns 130 only on a real `KeyboardInterrupt`.
- CLI: `watch BASIC --timeout 0` → 64; `watch a.log b.log` → 64; `watch BASIC --order time` → 64; a subprocess test with `--timeout 0.2 --interval 0.05` on an empty temp file exits 3 and prints a single `_meta` line with `"matched": false`; a subprocess test that appends a matching line after start exits 0 and prints the record then `_meta`.

Prompt: "Implement T10 of `docs/plans/cli-p1-handoff.md`: `tools/watch.py` `watch()` returning `WatchResult`, using `tail_once` polling with the same reopen rules as `follow`, a monotonic deadline via injectable `clock`/`sleep`, `existing` backlog scan, and a threaded reader for stdin; CLI `watch SOURCE --timeout --existing --interval` with exit 0/3/2/64/130."

### T11. `--format table` wiring

Scope: `cli.py`, `tests/test_cli.py`. Depends on T4–T9.

Deliverables: `--format {console,json,table}` on `query` (valid only with `--summary`), `meta`,
`fields`, `tree`, `stats`, `errors`, `validate`, `diff`; column lists per D11 and the task
sections; `table` on other commands → 64. `NO_COLOR`/`FORCE_COLOR` have no effect on tables.

Acceptance: each supported command produces a header, rule, and rows from the fixtures; `query BASIC --format table` (no `--summary`) → 64; `stats DURATIONS --spans --format table` shows `~` prefixes only when `percentiles_capped`; empty `tree` result prints `(no rows)`.

Prompt: "Implement T11 of `docs/plans/cli-p1-handoff.md`: add the `table` format choice to the listed commands using `render_table`, with the specified columns, and reject it elsewhere with exit 64."

### T12. Documentation and plan status

Scope: `README.md` (extend "Reading logs" with the new commands, `--order time`, table format,
exit code 3), `CHANGELOG.md` (Unreleased), `AGENTS.md` (layout entries for new modules; sentence
that tools/CLI names are exported from `slogger.tools.__all__`, not the package root; move CLI
P1 out of the deferred table and add "CLI P2"), `docs/plans/cli.md` (fix the stale Python API
block to real signatures; `context -B/-A`; status line "P1 implemented"), this file (status line).

Acceptance: `python3 -m slogger --help` lists all eleven commands; README examples run against the
fixtures; ruff/pyrefly/pytest green.

Prompt: "Implement T12 of `docs/plans/cli-p1-handoff.md`: update README, CHANGELOG, AGENTS.md, and `docs/plans/cli.md` as listed, correcting the stale API examples, and mark P1 implemented in both handoff and plan."

## Checks (verified in this environment)

```bash
python3 -m pytest -q                        # 143 passed at handoff time
python3 -m ruff check src tests examples    # All checks passed
python3 -m pyrefly check                    # 0 errors
python3 -m slogger --help
```

Per-task: `python3 -m pytest -q tests/test_tools_<module>.py tests/test_cli.py`. Python 3.10 and
3.13 are unavailable on this VM; none of the P1 modules touch stack walking, so the 3.12 run is
the acceptance baseline, and the multi-version run in `AGENTS.md` remains a CI item.

## Maintainer decisions still open

Defaults are chosen so implementation can start; change them before T2/T3 if you disagree.

1. Merge cursor format `time;<id>;<id>` (one CLI token, `;`-separated) versus a JSON array — the
   former is chosen for shell friendliness; paths containing `;` are rejected in time mode.
2. `errors` command implemented as `slogger.tools.failures.failures()` to avoid shadowing the
   exception module; the CLI name stays `errors`.
3. `query --group-by` implies `--summary` (no grouped record listing in P1).
4. `watch` default ignores existing records (`--existing` opts in) and exits 3 on timeout with the
   payload on stdout.

## Start here

Run T1 first: it fixes the P0 discrepancies every later task depends on (materialised iterables,
unique in-memory labels, `ValueError` → 64), adds `Reader.iter_lines()`, `render_table`,
`grouping`, `timeparse`, and all six new fixtures.
