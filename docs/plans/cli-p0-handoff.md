# P0 handoff: `slogger.tools` and `python3 -m slogger`

Historical implementation handoff. Baselines, findings, and proposed signatures
below describe that phase, not the current repository. For current behavior use
[the API reference](../api.md) and [CLI reference](../cli.md); Python-only rich
filters are documented in [typed predicates](../api.md#typed-python-predicates).
Historical precedence statements below apply only to that phase.

Implementation-ready breakdown of P0 from [`cli.md`](cli.md). Where this file and `cli.md`
disagree, this file wins. **P0 is implemented** on the branch that landed `slogger.tools` and
`python3 -m slogger`.

Verified against the repository on 2026-09-27 (66 tests, ruff, pyrefly all green with
`python3 -m ...`; `python` is not on `PATH` in the Cloud Agent VM, so every command below uses
`python3`).

## Facts checked in the code

| Assumption in `cli.md` | Reality | Consequence |
|---|---|---|
| Console output reuses `ConsoleFormatter` | `ConsoleFormatter.format` takes a `logging.LogRecord` ([`formatters.py`](../../src/slogger/formatters.py)) | Add a dict-based `render_console_line()` in `tools/render.py` that reuses `format_value`, `ConsoleFormatter.COLORS`, `SCHEMA_KEYS`, `SPAN_FIELD_ORDER`. Do not refactor the formatter. |
| Timestamps are ordered | Millisecond resolution; a whole span tree usually shares one timestamp | Never sort by timestamp alone; reading order is the tie-breaker everywhere. |
| Rotated files `app.log.YYYY-MM-DD` | `TimedRotatingFileHandler(when="midnight", utc=True)`, `suffix="%Y-%m-%d"`, `extMatch=(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)` ([`handlers.py`](../../src/slogger/handlers.py)) | Rotation renames the live file. Cursors into `app.log` are invalid after midnight. |
| Span record shape | `span.start`: `event`, `span`, `span_id`, `trace_id`, `parent_span_id` (nested only), plus context. `span.end`: same plus `duration_ms`, `status`, and on error `error_type`, `error`, `exception`, level `ERROR`. Both at `DEBUG` otherwise. ([`span.py`](../../src/slogger/span.py)) | Fixtures below match this exactly. |
| Exit code 2 = data error | `argparse` exits `2` on usage errors | Subclass `ArgumentParser.error` to exit `64`. |
| `--level` compares names | `logging.getLevelName("FOO")` returns `"Level FOO"`, custom levels are possible | Map through `logging.getLevelNamesMapping()` (3.11+) / `logging._nameToLevel` fallback; unknown level names never satisfy a minimum-level filter. |
| Package data | `[tool.setuptools.package-data] slogger = ["py.typed", "schemas/*.json"]`; no `[project.scripts]`, no `__main__.py`, no `[cli]` extra | Add `__main__.py`; do not add a console script or extra in P0. |
| Tests import installed package | `pip install -e ".[dev]"`; `testpaths=["tests"]`; no `pythonpath` | New fixtures live under `tests/fixtures/`; tests import `slogger.tools`. |
| `capture_logs()` output shape | list of `LogRecord` dicts identical to `JSONFormatter` output ([`testing.py`](../../src/slogger/testing.py)) | In-memory sources accept that list directly. |
| Lint/type settings | ruff `E F I B`, line length 100, `known-first-party=["slogger"]`; pyrefly includes `src`, `tests` | Every new file must pass both. |

## Resolved decisions

### D1. `--where` syntax

- One token per flag, **compact only**: `KEY OP VALUE`, no whitespace around `OP`. Spaced forms
  are not accepted (`--where user = ada` is a usage error).
- Operators, longest match first: `!=`, `>=`, `<=`, `!~`, `=`, `>`, `<`, `~`.
- Split on the **first** operator occurrence. `KEY` is everything before it and must be non-empty
  and contain none of `= ! < > ~`. `VALUE` is the rest, may be empty, may contain any character
  including `=`. There is no escaping; the shell does quoting.
- Existence tests are separate flags: `--has KEY`, `--missing KEY` (repeatable). `KEY?` from
  `cli.md` is withdrawn so the token grammar stays `KEY OP VALUE`.
- Multiple `--where`/`--has`/`--missing` are ANDed. No OR, no grouping.

Type conversion, driven by the **record** value:

| Record value | `=` / `!=` | `<` `>` `<=` `>=` | `~` / `!~` |
|---|---|---|---|
| `str` | string equality | lexicographic (works for ISO timestamps) | `re.search` on the string |
| `int` / `float` | parse `VALUE` as number; unparseable → no match | numeric; unparseable → no match | regex on `str(value)` |
| `bool` | `VALUE.lower()` in `{"true","false"}` | no match | regex on `"true"/"false"` |
| `None` | `VALUE == "null"` | no match | regex on `"null"` |
| `dict` / `list` | compare to `json.dumps(value, sort_keys=True, separators=(",",":"))` | no match | regex on that JSON |

Missing key: **no match for every operator, including `!=` and `!~`**. Use `--missing KEY` to
select absent keys. Rationale: `!=` on a missing key silently selecting most of the file is the
common footgun.

Other filters: `--level LEVEL` is a minimum (`--level =LEVEL` exact); names case-insensitive,
integers accepted. `--logger NAME` matches `NAME` or `NAME.` prefix. `--grep PATTERN` is
`re.search` on `message`. `--since`/`--until` accept ISO-8601 (`Z`, offset, or naive = UTC) or
relative `Ns`/`Nm`/`Nh`/`Nd` from now; a record whose `timestamp` does not parse is **excluded**
when either flag is present, included otherwise. `--span NAME` is `span == NAME`.
`--trace ID` is exact `trace_id`. `--exclude-events` drops `event in {span.start, span.end}`.

### D2. Record identity and cursors

- Every record yielded by the reader gets `_id = "<source>:<n>"`.
  - File: `<source>` is the path **exactly as given** on the command line or to the API (not
    resolved), `<n>` is the 1-based physical line number. Split with `rsplit(":", 1)` so Windows
    drive letters survive.
  - Stdin: `-:<n>`. Cursors are accepted for filtering within one invocation but `--after` with
    stdin is a usage error (64).
  - In-memory iterable: `mem:<index>`, 0-based position in the iterable. `after=` works only when
    the same iterable is passed again in the same process.
- A **cursor is the `_id` of the last returned record**. `--after CURSOR` resumes strictly after
  it in reading order: skip whole files that precede the cursor's file, skip lines `<= n` in that
  file, read subsequent files fully.
- Validity: a cursor is valid while the file at that path has not been truncated, renamed, or
  rotated. If `--after path:n` names a path not in the input set, or the file has fewer than `n`
  lines, fail with `{"error": "cursor_invalid", ...}` and exit `2`. No silent restart.
- Not in P0: inode tracking, content hashes, cursors that survive rotation.

### D3. Input ordering

- **Concatenation order, not a timestamp merge.** Files are read one after another; lines in file
  order. Records are never re-sorted. Out-of-order records stay where they are. This is what makes
  line-based cursors meaningful.
- File order: as given on the command line. Each glob expands to a lexicographically sorted list,
  **except** that a base file whose rotated siblings (`<base>.<YYYY-MM-DD>` matching `extMatch`)
  are also in the list is moved after them. So `logs/app.log*` yields
  `app.log.2026-09-25, app.log.2026-09-26, app.log`.
- Timestamp ties: reading order. Missing or unparseable timestamp: record kept, treated as
  `None` for `--since/--until` (see D1) and sorts last inside a trace (D5).

### D4. Streaming, memory, pagination

- `Reader` is a streaming iterator with bounded state (open file handle, current line). It counts
  `skipped_lines` (non-JSON or JSON that is not an object). Blank/whitespace-only lines are
  ignored and not counted.
- `query()` returns a `Page`; memory is bounded by `limit`. `limit=None` means unbounded and is
  the caller's responsibility. `--last N` keeps a `deque(maxlen=N)` and is mutually exclusive
  with `--after`.
- Default limits: CLI `--format json` → `200`; console → unlimited. `--limit 0` means unlimited.
- `fields()` scans at most `scan=100_000` records by default (`--scan N`, `0` = all), keeps up to
  `10_000` distinct values per key (reported as `"distinct": 10000, "distinct_capped": true`
  beyond that) and `5` sample values per key (first seen).
- `meta()` scans everything but keeps only counters and sets of logger/span names (span names
  capped at 1 000, loggers at 1 000, both with `_capped` flags).
- `trace()` buffers only the selected trace. Selection by `--where` needs two passes over files
  (find `trace_id`, then collect); stdin is buffered in full (documented limitation).
- `--fields a,b,c` projects record keys; `_id` is always kept in JSON output. `--truncate N` cuts
  every string value longer than `N` to `N` characters and appends `...`; it affects output only,
  never filtering.

### D5. Trace selection and reconstruction

Selection (exactly one of):
- Positional `TRACE_ID`: full 32-hex id, or a prefix of at least 4 characters. Prefix matching
  more than one `trace_id` → `{"error": "ambiguous_trace", "candidates": [...up to 10]}` exit `2`.
  No match → `{"error": "trace_not_found"}` exit `2`.
- `--where ...` (plus other filters): the trace is the `trace_id` of the **first matching record in
  reading order**. Output reports `"matched_records": n, "matched_traces": m`. If the first match
  has no `trace_id` → `{"error": "no_trace_on_match"}` exit `2`.

Reconstruction rules, in order:
1. Collect all records with that `trace_id`.
2. A span node is keyed by `span_id`. `span.start` creates it (name from `span`, fields from the
   record minus `SCHEMA_KEYS`, span keys and `event`). A second `span.start` for the same id is
   ignored, warning `duplicate_start`.
3. `span.end` closes it (`ended`, `duration_ms`, `status`, `error_type`, `error`). A second
   `span.end` is ignored, warning `duplicate_end`. `span.end` with no prior start creates the node
   with `missing_start: true`, `started: null`.
4. Unfinished (start without end): `status: "unknown"`, `ended: null`, `duration_ms: null`.
5. Parenting: `parent_span_id` present and known → child. Present but unknown → root-level node
   with `orphan: true`, warning `missing_parent`. Absent → root.
6. Non-event records with `span_id` attach as `logs` of that span (created as `missing_start` if
   the span is unknown). Records with `trace_id` but no `span_id` go to trace-level `logs`.
7. Ordering of children and logs: stable sort by `(timestamp or "~", reading order)` so ties and
   missing timestamps keep file order and missing timestamps sort last.
8. Trace `status`: `error` if any span is `error`; else `unknown` if any root is `unknown`; else
   `ok`. Trace `started` = min `started` of roots (or first record timestamp when all are missing);
   `ended` = max `ended` of roots or `null`; `duration_ms` = root `duration_ms` when exactly one
   root has one, else `null`.

### D6. Following a file (`tail`)

- Follow mode (`tail` without `--once`): a trailing line **without `\n` is held back**, never
  parsed, and retried when more bytes arrive. Poll interval `--interval 0.25` seconds.
- `--once`: read from `--after` (or from the start) to EOF, emit, exit. A trailing partial line is
  not returned and `next_cursor` stops before it, so the next `--once` call picks it up complete.
- Non-follow commands (`query`, `trace`, `meta`, `fields`) on a regular file parse a final
  unterminated line normally; the file is treated as complete.
- Rotation while following: if the file at the path shrinks or its inode changes, reopen the path
  from offset 0 and continue; the renamed file is not followed. Emit console notice
  `-- reopened <path>` on stderr; nothing in stdout JSON.
- Stdin follow: read until EOF, then exit `0`.
- `SIGINT` → flush, exit `130`.

### D7. Machine output and exit codes

- `--format` defaults to `console` when stdout is a TTY, otherwise `json`. `--format table` is
  **P1** (not in P0).
- List commands (`query`, `tail`) in JSON write **JSONL**: one record per line (with `_id`), then
  exactly one trailing control line
  `{"_meta": {"schema_version": 1, "returned": n, "skipped_lines": k, "next_cursor": "..."|null, "warnings": [...]}}`.
  For `query`, `next_cursor` is the last returned `_id` when `limit` was reached, else `null`
  (end of results). For `tail --once`, `next_cursor` is always the last returned `_id` (or the
  `--after` value when nothing was returned) so a poller can resume. A follow-mode `tail` never
  writes `_meta` (it does not end).
- Aggregate commands (`meta`, `fields`, `trace`) in JSON write **one object** containing
  `"schema_version": 1` plus the payload defined in each task below.
- Errors: one JSON object on stderr `{"error": "<code>", "message": "...", ...}` when
  `--format json`; a plain `error: ...` line otherwise. Stdout is left clean.
- Console mode: when `skipped_lines > 0`, one stderr line at the end:
  `skipped 3 lines that were not JSON objects`.
- Exit codes: `0` success; `1` `--fail-if-any` and at least one record matched; `2` data error
  (`file_not_found`, `cursor_invalid`, `ambiguous_trace`, `trace_not_found`, `no_trace_on_match`,
  `permission_denied`); `64` usage error (argparse override, `--after` with stdin, `--last` with
  `--after`, bad `--where` token, bad `--since`); `130` interrupted.
- Reserved output keys `_id` and `_meta` start with an underscore. User context keys starting with
  `_` are passed through unchanged; a user `_id` is overwritten in output (documented limitation).

### D8. P0 / P1 boundary

P0 ships: `Reader`, filters, console+JSON renderers, `meta`, `fields`, `query`, `trace`, `tail`
(follow and `--once`), `python3 -m slogger`, Python API for the same, fixtures and tests, README
section, CHANGELOG, `AGENTS.md` layout update.

Not in P0 (do not build even if convenient): `tree`, `stats`, `errors`, `validate`, `context`,
`diff`, `watch`, `explain`, `completion`, `--group-by`, `--format table`, `--summary` on `query`,
output JSON Schemas, `[cli]` extra, console script, `rich`, sidecar caches for `fields`, inode
cursors, timestamp merging across files, `--bucket`, percentiles.

## Decisions that need the maintainer

Defaults are chosen so work can start; say so if you want them changed.

1. **Reserved keys `_id` / `_meta`** in JSON output (D7). Alternative: nest records as
   `{"record": {...}, "id": "..."}`, which is collision-free but breaks "same shape as the file".
2. **Concatenation order instead of timestamp merge** across files (D3). Simpler and cursor-safe;
   means multi-process logs into separate files will interleave incorrectly until a P1 merge mode.
3. **`!=` on a missing key is no match** (D1). SQL-like; some users expect the opposite.
4. **`cursor_invalid` is a hard error** (D2) rather than a restart-from-zero for `tail --once`.

## Shared fixtures

Create `tests/fixtures/logs/` with these files. Timestamps are fixed. Ids are deliberately short
but valid hex. The expected behaviour below is the contract; do not derive it from the code.

`basic.log` — 6 records, two loggers, mixed types:

```json
{"timestamp": "2026-09-26T16:00:00.000Z", "level": "INFO", "logger": "app", "message": "started", "file": "main.py", "func": "main", "line": 10, "version": "1.4.0", "debug": false}
{"timestamp": "2026-09-26T16:00:01.000Z", "level": "DEBUG", "logger": "app.db", "message": "connected", "file": "db.py", "func": "connect", "line": 22, "host": "localhost", "port": 5432}
{"timestamp": "2026-09-26T16:00:02.000Z", "level": "INFO", "logger": "app.pay", "message": "charging", "file": "pay.py", "func": "charge", "line": 40, "order_id": "42", "amount": 99.5, "user": "ada"}
{"timestamp": "2026-09-26T16:00:02.000Z", "level": "WARNING", "logger": "app.pay", "message": "retrying", "file": "pay.py", "func": "charge", "line": 44, "order_id": "42", "attempt": 2, "user": "ada"}
{"timestamp": "2026-09-26T16:00:03.000Z", "level": "ERROR", "logger": "app.pay", "message": "charge failed", "file": "pay.py", "func": "charge", "line": 48, "order_id": "42", "user": "ada", "error_type": "TimeoutError", "tags": ["billing", "retry"]}
{"timestamp": "2026-09-26T16:00:04.000Z", "level": "INFO", "logger": "app", "message": "stopped", "file": "main.py", "func": "main", "line": 12, "ctx_message": "user supplied", "note": null}
```

`malformed.log` — 8 physical lines; **line 8 has no trailing newline**:

```text
{"timestamp": "2026-09-26T17:00:00.000Z", "level": "INFO", "logger": "m", "message": "one", "file": "a.py", "func": "f", "line": 1}

not json at all
[1, 2, 3]
{"timestamp": "2026-09-26T17:00:01.000Z", "level": "INFO", "logger": "m", "message": "two", "file": "a.py", "func": "f", "line": 2}
{"level": "INFO", "logger": "m", "message": "no timestamp", "file": "a.py", "func": "f", "line": 3}
{"timestamp": "not-a-date", "level": "INFO", "logger": "m", "message": "bad timestamp", "file": "a.py", "func": "f", "line": 4}
{"timestamp": "2026-09-26T17:00:02.000Z", "level": "INFO", "logger": "m", "message": "three", "file": "a.py", "func": "f", "line": 5}
```

Expected: 5 records (`_id`s `malformed.log:1,5,6,7,8` when read as a complete file), `skipped_lines == 2`
(lines 3 and 4), blank line 2 not counted.

`trace.log` — one complete trace `aaaa...` (32 chars of `a`), one unfinished trace `bbbb...`,
one orphan and duplicate-end trace `cccc...`. Span ids are 16 hex chars.

```json
{"timestamp": "2026-09-26T18:00:00.000Z", "level": "DEBUG", "logger": "app", "message": "span.start", "file": "shop.py", "func": "checkout", "line": 5, "user": "ada", "span": "checkout", "span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "event": "span.start"}
{"timestamp": "2026-09-26T18:00:00.000Z", "level": "INFO", "logger": "app.db", "message": "connected", "file": "db.py", "func": "connect", "line": 22, "user": "ada", "span": "checkout", "span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "host": "localhost"}
{"timestamp": "2026-09-26T18:00:00.000Z", "level": "DEBUG", "logger": "app", "message": "span.start", "file": "shop.py", "func": "charge", "line": 9, "user": "ada", "span": "charge", "span_id": "2222222222222222", "parent_span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "order_id": "42", "event": "span.start"}
{"timestamp": "2026-09-26T18:00:00.150Z", "level": "INFO", "logger": "app.pay", "message": "charging", "file": "pay.py", "func": "charge", "line": 40, "user": "ada", "span": "charge", "span_id": "2222222222222222", "parent_span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "order_id": "42", "amount": 99.0}
{"timestamp": "2026-09-26T18:00:00.380Z", "level": "ERROR", "logger": "app", "message": "span.end", "file": "shop.py", "func": "charge", "line": 9, "user": "ada", "span": "charge", "span_id": "2222222222222222", "parent_span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "order_id": "42", "event": "span.end", "duration_ms": 380.0, "status": "error", "error_type": "TimeoutError", "error": "boom", "exception": "Traceback (most recent call last):\n  ...\nTimeoutError: boom"}
{"timestamp": "2026-09-26T18:00:00.390Z", "level": "WARNING", "logger": "app", "message": "rolling back", "file": "shop.py", "func": "checkout", "line": 12, "user": "ada", "span": "checkout", "span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
{"timestamp": "2026-09-26T18:00:00.410Z", "level": "DEBUG", "logger": "app", "message": "span.end", "file": "shop.py", "func": "checkout", "line": 5, "user": "ada", "span": "checkout", "span_id": "1111111111111111", "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "event": "span.end", "duration_ms": 410.0, "status": "ok"}
{"timestamp": "2026-09-26T18:01:00.000Z", "level": "DEBUG", "logger": "app", "message": "span.start", "file": "shop.py", "func": "checkout", "line": 5, "span": "checkout", "span_id": "3333333333333333", "trace_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "event": "span.start"}
{"timestamp": "2026-09-26T18:01:00.050Z", "level": "INFO", "logger": "app", "message": "working", "file": "shop.py", "func": "checkout", "line": 7, "span": "checkout", "span_id": "3333333333333333", "trace_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
{"timestamp": "2026-09-26T18:02:00.000Z", "level": "DEBUG", "logger": "app", "message": "span.start", "file": "shop.py", "func": "child", "line": 20, "span": "child", "span_id": "4444444444444444", "parent_span_id": "9999999999999999", "trace_id": "cccccccccccccccccccccccccccccccc", "event": "span.start"}
{"timestamp": "2026-09-26T18:02:00.100Z", "level": "DEBUG", "logger": "app", "message": "span.end", "file": "shop.py", "func": "child", "line": 20, "span": "child", "span_id": "4444444444444444", "parent_span_id": "9999999999999999", "trace_id": "cccccccccccccccccccccccccccccccc", "event": "span.end", "duration_ms": 100.0, "status": "ok"}
{"timestamp": "2026-09-26T18:02:00.100Z", "level": "DEBUG", "logger": "app", "message": "span.end", "file": "shop.py", "func": "child", "line": 20, "span": "child", "span_id": "4444444444444444", "parent_span_id": "9999999999999999", "trace_id": "cccccccccccccccccccccccccccccccc", "event": "span.end", "duration_ms": 100.0, "status": "ok"}
{"timestamp": "2026-09-26T18:02:00.200Z", "level": "DEBUG", "logger": "app", "message": "span.end", "file": "shop.py", "func": "other", "line": 30, "span": "other", "span_id": "5555555555555555", "trace_id": "cccccccccccccccccccccccccccccccc", "event": "span.end", "duration_ms": 5.0, "status": "ok"}
{"timestamp": "2026-09-26T18:02:00.300Z", "level": "INFO", "logger": "app", "message": "loose", "file": "shop.py", "func": "other", "line": 31, "trace_id": "cccccccccccccccccccccccccccccccc"}
```

`rotated/` — three files, each two records, to test glob ordering and cursors:

```text
rotated/app.log.2026-09-25   messages "r1", "r2"   timestamps 2026-09-25T23:59:58Z, 23:59:59Z
rotated/app.log.2026-09-26   messages "r3", "r4"   timestamps 2026-09-26T23:59:58Z, 23:59:59Z
rotated/app.log              messages "r5", "r6"   timestamps 2026-09-27T00:00:01Z, 00:00:02Z
```

(all `level=INFO`, `logger=rot`, `file=r.py`, `func=f`, `line=1`).

Also add `tests/fixtures/__init__.py` (empty) and a `fixture_path(name) -> str` helper in
`tests/conftest.py` returning the path **relative to the repo root** so `_id`s in assertions are
predictable (`tests/fixtures/logs/basic.log:3`). Tests should `os.chdir` to the repo root via a
`monkeypatch.chdir(REPO_ROOT)` fixture.

Fixture generation: write the files by hand or with a throwaway script; do not generate them at
test time. Preserve the missing final newline in `malformed.log` (`git` may warn; add
`tests/fixtures/logs/malformed.log -text` to `.gitattributes`).

## Tasks

Run after every task: `python3 -m pytest -q`, `python3 -m ruff check src tests examples`,
`python3 -m pyrefly check`. All three are currently green and must stay green.

### T1. Fixtures, `Reader`, source resolution

Scope: `src/slogger/tools/__init__.py`, `src/slogger/tools/reader.py`, fixtures above,
`tests/test_tools_reader.py`. No CLI. Depends on nothing.

Inspect: `formatters.format_timestamp` (timestamp shape), `handlers.get_structured_file_handler`
(rotation naming), `testing.capture_logs` (in-memory shape).

Signatures:

```python
Source = str | os.PathLike[str] | Iterable[Mapping[str, Any]]

def resolve_sources(sources: Source | Sequence[Source]) -> list[str | Iterable[Mapping[str, Any]]]
    # expands globs, orders per D3, keeps "-" literal, keeps iterables as-is
    # raises FileNotFoundError for a literal path that does not exist (glob with 0 matches is also an error)

class Reader:
    def __init__(self, sources, *, after: str | None = None, complete: bool = True) -> None
    def __iter__(self) -> Iterator[dict[str, Any]]   # yields shallow copies with "_id" set
    skipped_lines: int
    last_id: str | None
    warnings: list[str]

def parse_timestamp(value: object) -> datetime | None   # ISO-8601 with Z/offset/naive→UTC; None if unparseable
def parse_id(value: str) -> tuple[str, int]             # rsplit(":", 1); ValueError if malformed
```

`complete=False` is the follow-mode flag: hold back an unterminated final line (D6). `after`
follows D2 and raises `CursorError(code="cursor_invalid")` (define in `tools/errors.py` along with
`ToolError(code, message, **extra)`).

Acceptance:

- `list(Reader("tests/fixtures/logs/basic.log"))` → 6 dicts; `[r["_id"] for r in ...]` ends with
  `tests/fixtures/logs/basic.log:6`; input dicts are not the same objects when an iterable is
  passed (`rec is not src[0]`).
- `Reader("tests/fixtures/logs/malformed.log")` → 5 records with `_id` line numbers
  `[1, 5, 6, 7, 8]`, `skipped_lines == 2`.
- Same file with `complete=False` → 4 records (line 8 held back), `skipped_lines == 2`.
- `resolve_sources("tests/fixtures/logs/rotated/app.log*")` →
  `[".../app.log.2026-09-25", ".../app.log.2026-09-26", ".../app.log"]`.
- Reading that glob yields messages `r1..r6` in that order.
- `after="tests/fixtures/logs/rotated/app.log.2026-09-26:1"` → messages `r4, r5, r6`.
- `after="tests/fixtures/logs/rotated/app.log:9"` → `CursorError` with `code == "cursor_invalid"`.
- `after="nope.log:1"` with the glob → `CursorError`.
- `Reader([{"message": "a"}, {"message": "b"}], after="mem:0")` → one record, `_id == "mem:1"`.
- `parse_timestamp("2026-09-26T16:00:00.000Z")` is tz-aware UTC; `parse_timestamp("not-a-date")`
  and `parse_timestamp(None)` return `None`; `"2026-09-26T16:00:00"` is treated as UTC.
- `parse_id("C:\\logs\\app.log:12")` → `("C:\\logs\\app.log", 12)`.
- `Reader("missing.log")` raises `FileNotFoundError` at construction, not on iteration.

Exclusions: no filtering, no follow loop, no inode tracking, no sorting.

### T2. Filters

Scope: `src/slogger/tools/filters.py`, `tests/test_tools_filters.py`. Depends on T1
(`parse_timestamp`).

Signatures:

```python
@dataclass(frozen=True)
class Where:
    key: str; op: Literal["=", "!=", ">", "<", ">=", "<=", "~", "!~"]; value: str

def parse_where(token: str) -> Where            # ValueError with message on bad token
def level_number(name_or_int: str | int) -> int # ValueError if unknown

@dataclass
class Filters:
    level_min: int | None = None
    level_exact: int | None = None
    logger: str | None = None
    where: tuple[Where, ...] = ()
    has: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    grep: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    span: str | None = None
    trace: str | None = None
    exclude_events: bool = False

    def matches(self, record: Mapping[str, Any]) -> bool

def parse_relative_or_iso(text: str, *, now: datetime | None = None) -> datetime  # ValueError on bad input
```

Acceptance (all against `basic.log` records, `R[n]` is 1-based line):

- `parse_where("user=ada")` → `Where("user", "=", "ada")`; `"amount>=99"` → `>=`;
  `"message~^charg"` → `~`; `"note=a=b"` → value `"a=b"`; `"user="` → value `""`.
- `parse_where("=x")`, `parse_where("user")`, `parse_where("user = ada")` raise `ValueError`.
- `where user=ada` → `R[3], R[4], R[5]`. `where amount=99.5` → `R[3]`; `where amount=99` → none;
  `where amount>99` → `R[3]`; `where port>5000` → `R[2]`; `where debug=false` → `R[1]`;
  `where note=null` → `R[6]`; `where tags~billing` → `R[5]`;
  `where tags=["billing","retry"]` → `R[5]`.
- `where user!=ada` → `[]` (missing key is never a match); `missing=("user",)` → `R[1], R[2], R[6]`;
  `has=("order_id",)` → `R[3], R[4], R[5]`.
- `where timestamp>=2026-09-26T16:00:02.000Z` → `R[3..6]` (string comparison).
- `level_min=WARNING` → `R[4], R[5]`; `level_exact=INFO` → `R[1], R[3], R[6]`;
  `level_number("warning") == 30`; `level_number("30") == 30`; `level_number("nope")` raises.
- `logger="app"` → all 6; `logger="app.pay"` → `R[3..5]`; `logger="app.p"` → none.
- `grep="charg"` → `R[3], R[5]`.
- `since=16:00:02Z` → `R[3..6]`; `until=16:00:02Z` → `R[1..4]` (inclusive both ends).
- On `malformed.log`: `since=17:00:00Z` → messages `one, two, three` (records with missing or bad
  timestamps excluded); with no since/until → all 5.
- `parse_relative_or_iso("10m", now=T)` → `T - 10 minutes`; `"2h"`, `"1d"`, `"30s"` work;
  `"10x"` raises; `"2026-09-26T16:00:00Z"` parses.
- `exclude_events=True` on `trace.log` → 5 records (lines 2, 4, 6, 9, 14).

Exclusions: no OR/grouping, no `KEY?` token, no `--group-by`, no `explain`.

### T3. Renderers

Scope: `src/slogger/tools/render.py`, `tests/test_tools_render.py`. Depends on nothing (pure
functions over dicts). Inspect and **reuse without modifying**: `formatters.format_value`,
`ConsoleFormatter.COLORS/RESET/WHITE/DIM`, `schema.SCHEMA_KEYS`, `schema.SPAN_FIELD_ORDER`.

Signatures:

```python
def use_color(stream, *, force: bool | None = None) -> bool   # same rules as ConsoleFormatter._use_color (reimplement on a stream; do not call the private method)
def render_console_line(record: Mapping[str, Any], *, color: bool) -> str
def render_json_line(record: Mapping[str, Any]) -> str        # json.dumps(default=json_default, ensure_ascii=False)
def project(record, fields: Sequence[str] | None, truncate: int | None) -> dict  # keeps "_id"; truncation per D4
```

`render_console_line` output: `timestamp LEVEL<8 logger  message  k=v ... span-tail` with the
same key ordering as `ConsoleFormatter.format` (sorted user keys, then `SPAN_FIELD_ORDER` keys),
`_id` never printed, `exception`/`stack` appended on new lines when present. Missing `timestamp`
renders as `-`, missing `level` as `-`, missing `logger` as `-`.

Acceptance:

- `basic.log` line 3 without colour →
  `2026-09-26T16:00:02.000Z INFO     app.pay  charging  amount=99.5 order_id=42 user=ada`.
- `trace.log` line 5 without colour ends with
  `event=span.end status=error duration_ms=380.0 error_type=TimeoutError error=boom span=charge span_id=2222222222222222 parent_span_id=1111111111111111 trace_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
  followed by a newline and the exception text.
- `malformed.log` line 6 renders with `-` in the timestamp column.
- With `color=True`, the line contains `\033[1;32m` for `INFO` and `\033[2m` before `span=`.
- `project(rec, ["message", "user"], None)` → keys exactly `{"_id", "message", "user"}`;
  `project(rec, None, 5)` turns `"charging"` into `"charg..."`; non-strings are untouched.
- `render_json_line({"a": {1, 2}})` does not raise (set falls back via `json_default`).
- `use_color(io.StringIO())` is `False`; with `FORCE_COLOR=1` it is `True`; with `NO_COLOR=`
  and a fake `isatty() -> True` it is `False`.

Exclusions: no tables, no tree rendering (T6 owns the tree), no `rich`.

### T4. CLI skeleton and `query`

Scope: `src/slogger/cli.py`, `src/slogger/__main__.py`, `src/slogger/tools/query.py`,
`tests/test_cli.py`, `tests/test_tools_query.py`. Depends on T1–T3.

Inspect: `pyproject.toml` (do not add `[project.scripts]`), `slogger/__init__.py` (do not
export `tools` or `cli` from the package root; leave `__all__` unchanged).

Signatures:

```python
# tools/query.py
@dataclass
class Page:
    records: list[dict[str, Any]]
    next_cursor: str | None
    skipped_lines: int
    warnings: list[str]

def query(sources, *, filters: Filters | None = None, limit: int | None = None,
          after: str | None = None, last: int | None = None,
          fields: Sequence[str] | None = None, truncate: int | None = None) -> Page

# cli.py
def main(argv: Sequence[str] | None = None) -> int   # returns exit code; never calls sys.exit itself except via parser
def build_parser() -> argparse.ArgumentParser         # subclass whose .error() prints usage to stderr and exits 64
```

`python3 -m slogger` → `sys.exit(main())`. Shared filter flags are added by one helper
`add_filter_args(parser)` so T5–T7 reuse them verbatim. Shared output flags:
`--format {console,json}`, `--color/--no-color`, `--fields`, `--truncate`, `--limit`, `--last`,
`--after`, `--fail-if-any`.

Acceptance (CLI, run from repo root; check stdout/stderr/exit code with `subprocess` or by
calling `main()` with `capsys`):

- `python3 -m slogger query tests/fixtures/logs/basic.log --level WARNING --format json` →
  stdout is 3 lines: two records (`_id` `...:4`, `...:5`) and
  `{"_meta": {"schema_version": 1, "returned": 2, "skipped_lines": 0, "next_cursor": null, "warnings": []}}`;
  exit `0`.
- `... query basic.log --format json --limit 2` → 2 records, `next_cursor ==
  "tests/fixtures/logs/basic.log:2"`; then `--limit 2 --after tests/fixtures/logs/basic.log:2` →
  `_id`s `:3, :4`, `next_cursor ":4"`; `--after ...:6` → 0 records, `next_cursor null`.
- `... query basic.log --format json` with no `--limit` → 6 records (default 200 not hit),
  `next_cursor null`.
- `... query basic.log --format console --where user=ada` → 3 console lines on stdout, nothing on
  stderr, exit `0`.
- `... query tests/fixtures/logs/malformed.log --format console` → 5 lines on stdout and
  `skipped 2 lines that were not JSON objects` on stderr.
- `... query basic.log --level ERROR --fail-if-any --format json` → exit `1`; with
  `--level CRITICAL` → exit `0`.
- `... query basic.log --last 2 --format json` → `_id`s `:5, :6`, `next_cursor null`.
- `... query basic.log --last 2 --after x:1` → exit `64`, stderr starts with `usage:`.
- `... query - --after -:1 < basic.log` → exit `64`.
- `... query nope.log --format json` → exit `2`, stderr is one JSON object with
  `"error": "file_not_found"`, stdout empty.
- `... query basic.log --where 'user = ada'` → exit `64`.
- `... query basic.log --format json --fields message --truncate 4` → each record has exactly
  `_id` and `message`, `"star..."` for the first.
- `... query 'tests/fixtures/logs/rotated/app.log*' --format json` → messages `r1..r6` in order.
- `python3 -m slogger` with no subcommand → usage on stderr, exit `64`. `--help` → exit `0`.
- API: `query([{"message": "x", "level": "INFO"}], filters=Filters(level_min=20))` →
  `Page(records=[{..., "_id": "mem:0"}], next_cursor=None, skipped_lines=0, warnings=[])`.
- When stdout is not a TTY and `--format` is omitted, output is JSON (test with `capsys`, which
  is not a TTY).

Exclusions: `--summary`, `--group-by`, `--format table`, `tail`, `trace`, `meta`, `fields`
subcommands (register them in T5–T7), console script, `[cli]` extra.

### T5. `meta` and `fields`

Scope: `src/slogger/tools/fields.py`, `src/slogger/tools/meta.py`, CLI subcommands,
`tests/test_tools_fields.py`, `tests/test_tools_meta.py`, additions to `tests/test_cli.py`.
Depends on T1, T2, T4.

Signatures:

```python
def meta(sources, *, filters: Filters | None = None) -> dict[str, Any]
def fields(sources, *, filters: Filters | None = None, scan: int = 100_000,
           key: str | None = None, top: int = 10) -> dict[str, Any]
```

`meta` payload:

```json
{"schema_version": 1, "sources": [{"path": "...", "records": n, "skipped_lines": k, "bytes": b|null}],
 "records": n, "skipped_lines": k, "first_timestamp": "...|null", "last_timestamp": "...|null",
 "levels": {"INFO": 3, "...": 1}, "loggers": ["app", "app.db"], "loggers_capped": false,
 "spans": ["checkout"], "spans_capped": false, "traces": 3, "traces_capped": false}
```

`first_timestamp`/`last_timestamp` are min/max of parseable timestamps (not first/last seen).
`traces` counts distinct `trace_id` (cap 10 000). `bytes` is `null` for stdin and memory.

`fields` payload:

```json
{"schema_version": 1, "scanned": n, "scan_capped": false,
 "keys": {"user": {"type": "str", "types": ["str"], "count": 3, "present_pct": 50.0,
                   "distinct": 1, "distinct_capped": false, "samples": ["ada"]}, "...": {}}}
```

`type` is the most common JSON type name among `str, int, float, bool, null, object, array`
(`types` lists all seen, sorted). `samples` are the first 5 distinct values as JSON-safe values.
With `key=` the payload is instead
`{"schema_version": 1, "key": "user", "scanned": n, "top": [{"value": "ada", "count": 3}, ...]}`
sorted by count desc then value asc, limited to `top`. Non-scalar values are counted by their
sorted-compact JSON string. `_id` is never a reported key.

Acceptance:

- `meta("tests/fixtures/logs/basic.log")` → `records 6`, `levels == {"INFO": 3, "DEBUG": 1, "WARNING": 1, "ERROR": 1}`,
  `loggers == ["app", "app.db", "app.pay"]`, `spans == []`, `traces == 0`,
  `first_timestamp == "2026-09-26T16:00:00.000Z"`, `last_timestamp == "2026-09-26T16:00:04.000Z"`.
- `meta("tests/fixtures/logs/trace.log")` → `traces == 3`, `spans == ["charge", "checkout", "child", "other"]`.
- `meta("tests/fixtures/logs/malformed.log")` → `records 5`, `skipped_lines 2`,
  `first_timestamp "2026-09-26T17:00:00.000Z"`, `last_timestamp "...17:00:02.000Z"`.
- `fields("tests/fixtures/logs/basic.log")["keys"]["user"]` → `count 3`, `present_pct 50.0`,
  `distinct 1`, `samples ["ada"]`, `type "str"`. `["tags"]["type"] == "array"`,
  `["note"]["type"] == "null"`, `["amount"]["type"] == "float"`, `["port"]["type"] == "int"`,
  `["debug"]["type"] == "bool"`. `"ctx_message"` is present as a key; `"_id"` is not.
- `fields(..., key="logger", top=2)["top"]` → `[{"value": "app.pay", "count": 3}, {"value": "app", "count": 2}]`.
- `fields(..., scan=2)` → `scanned 2`, `scan_capped True`, no `user` key.
- CLI: `python3 -m slogger fields tests/fixtures/logs/basic.log --format json` is one JSON object
  with `schema_version 1`; `... fields basic.log --key user --format console` prints a two-column
  `value  count` listing; `... meta basic.log --format console` prints the summary block from
  `cli.md` (exact layout is free, must include record count, time range, level counts, loggers).
- `fields` and `meta` honour the shared filter flags (`--level ERROR` on `basic.log` → `meta`
  reports `records 1`).

Exclusions: sidecar cache, `stats`, percentiles, `--bucket`, completion hooks.

### T6. `trace`

Scope: `src/slogger/tools/trace.py`, CLI subcommand, `tests/test_tools_trace.py`, additions to
`tests/test_cli.py`. Depends on T1–T4.

Signatures:

```python
@dataclass
class SpanNode:
    span: str | None; span_id: str; parent_span_id: str | None
    status: Literal["ok", "error", "unknown"]
    started: str | None; ended: str | None; duration_ms: float | None
    error_type: str | None; error: str | None
    fields: dict[str, Any]; logs: list[dict[str, Any]]; children: list["SpanNode"]
    orphan: bool = False; missing_start: bool = False

@dataclass
class Trace:
    trace_id: str; status: str; started: str | None; ended: str | None; duration_ms: float | None
    spans: list[SpanNode]; logs: list[dict[str, Any]]; warnings: list[str]
    matched_records: int | None; matched_traces: int | None
    def to_dict(self) -> dict[str, Any]   # {"schema_version": 1, ...} with nested spans

def build_trace(records: Iterable[Mapping[str, Any]], trace_id: str) -> Trace   # pure, in-memory, follows D5
def find_trace_id(sources, *, prefix: str | None = None, filters: Filters | None = None) -> tuple[str, int, int]
    # returns (trace_id, matched_records, matched_traces); raises ToolError(ambiguous_trace | trace_not_found | no_trace_on_match)
def trace(sources, *, trace_id: str | None = None, filters: Filters | None = None) -> Trace
def render_trace(tr: Trace, *, color: bool, logs: bool = True) -> str   # box-drawing tree as in cli.md
```

`SpanNode.fields` excludes `SCHEMA_KEYS`, span keys (`SPAN_FIELD_ORDER`), `event`, and `_id`.
Each entry in `logs` is the full record dict including `_id`.

Acceptance (`T = "tests/fixtures/logs/trace.log"`):

- `trace(T, trace_id="aaaa")` → one root `checkout` (`status ok`, `duration_ms 410.0`,
  `started "...18:00:00.000Z"`, `ended "...18:00:00.410Z"`, `fields == {"user": "ada"}`), with
  `logs` messages `["connected", "rolling back"]` in that order, one child `charge`
  (`status error`, `error_type TimeoutError`, `error boom`, `duration_ms 380.0`,
  `fields == {"user": "ada", "order_id": "42"}`, `logs` messages `["charging"]`). Trace
  `status == "error"`, `duration_ms == 410.0`, `warnings == []`.
- `trace(T, trace_id="bbbb")` → root `checkout` with `status unknown`, `ended None`,
  `duration_ms None`, logs `["working"]`; trace `status unknown`, `ended None`.
- `trace(T, trace_id="cccc")` → two roots in order `child` (`orphan True`, `parent_span_id
  "9999999999999999"`, `status ok`, `duration_ms 100.0`) and `other` (`missing_start True`,
  `started None`, `ended "...18:02:00.200Z"`); trace-level `logs` messages `["loose"]`;
  `warnings` contains `"missing_parent:4444444444444444"` and `"duplicate_end:4444444444444444"`;
  trace `status ok`, `duration_ms None` (two roots).
- `trace(T, trace_id="a")` raises `ValueError` (prefix shorter than 4 characters); the CLI maps
  this to exit `64`.
- Create an in-memory list with two records whose `trace_id`s are `"abcd1111..."` and
  `"abcd2222..."`; `find_trace_id(..., prefix="abcd")` raises `ToolError` with
  `code == "ambiguous_trace"` and `extra["candidates"]` listing both. `prefix="zzzz"` →
  `trace_not_found`.
- `trace(T, filters=Filters(where=(Where("order_id", "=", "42"),)))` → trace `aaaa...`,
  `matched_records 3`, `matched_traces 1`.
- `trace(T, filters=Filters(grep="loose"))` → trace `cccc...`.
- `trace("tests/fixtures/logs/basic.log", filters=Filters(grep="started"))` → `ToolError`
  `no_trace_on_match`.
- `build_trace` with records lacking timestamps still orders by reading order and does not raise.
- `render_trace(trace(T, trace_id="aaaa"), color=False)` first line is
  `trace aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  2026-09-26T18:00:00.000Z  total 410 ms  status=error`;
  contains lines starting with `checkout`, `├─`, `└─`; contains `charge` and `error` on one line;
  `logs=False` removes the `connected` line. Unfinished spans render `?` in the duration column
  and `unknown` as status; `orphan` spans render a trailing `(orphan)`.
- CLI: `python3 -m slogger trace tests/fixtures/logs/trace.log aaaa --format json` → one object
  with `schema_version 1`, `trace_id`, `spans[0].children[0].span == "charge"`; exit `0`.
  `... trace trace.log zzzz --format json` → exit `2`, stderr JSON `error trace_not_found`.
  `... trace trace.log --where order_id=42` and `... trace trace.log aaaa --where x=y` → the
  latter is exit `64` (positional and `--where` are mutually exclusive).
- Stdin: `python3 -m slogger trace - aaaa < tests/fixtures/logs/trace.log` works (buffered).

Exclusions: `tree`, `--group-by`, `context`, waterfall timing bars, `stats`.

### T7. `tail`

Scope: `src/slogger/tools/tail.py`, CLI subcommand, `tests/test_tools_tail.py`, additions to
`tests/test_cli.py`. Depends on T1–T4.

Signatures:

```python
def tail_once(sources, *, filters=None, after: str | None = None, limit: int | None = None,
              fields=None, truncate=None) -> Page      # Reader(complete=False) then query semantics
def follow(path: str, *, filters=None, after: str | None = None, interval: float = 0.25,
           lines: int = 10, stop: Callable[[], bool] | None = None,
           on_reopen: Callable[[str], None] | None = None) -> Iterator[dict[str, Any]]
```

`follow` accepts exactly one file path or `-`. It first yields the last `lines` matching records
already in the file (`-n/--lines`, default 10, `0` disables), then blocks and yields new complete
lines as they arrive, honouring D6 (partial-line hold-back, rotation reopen). `stop` is polled
each interval so tests can end the loop. Multiple paths or a glob with `tail` without `--once`
is a usage error (64); `--once` accepts the same sources as `query`.

Acceptance (use `tmp_path`; write files in tests with explicit `\n` handling):

- `tail_once("tests/fixtures/logs/malformed.log")` → 4 records (line 8 held back),
  `next_cursor == "tests/fixtures/logs/malformed.log:7"` (in `tail_once`, `next_cursor` is
  always the last returned `_id`, even when no limit was hit, so polling can resume); copy the
  file to `tmp_path`, append `"\n"`, call again with the corresponding cursor → 1 record
  (`three`), `next_cursor` ends with `:8`.
- File with `a\n` + `{"message":"b"` (no newline): `follow(...)` with a `stop` after 3 polls yields
  only the record for line 1; then write `}\n` and poll again → yields `b`.
- Append two complete lines while following → both yielded in order, each with increasing `_id`.
- Simulate rotation: while following `p`, rename `p` to `p.2026-09-26`, create new `p` with one
  line; the next poll yields that line with `_id == f"{p}:1"` and `on_reopen(p)` was called once.
- Truncate the file to zero and write one line → same reopen behaviour.
- `follow` with `lines=1` on `basic.log` yields `stopped` first.
- Filters apply to both backlog and new lines (`Filters(level_min=WARNING)` on `basic.log`
  backlog with `lines=10` → `retrying`, `charge failed`).
- CLI: `python3 -m slogger tail tests/fixtures/logs/basic.log --once --format json` → 6 records
  and a `_meta` line; `... tail basic.log --once --after tests/fixtures/logs/basic.log:5 --format json`
  → 1 record (`:6`). `... tail a.log b.log` → exit `64`. `... tail - --after -:1` → exit `64`.
  Follow mode is exercised by an integration test that starts `python3 -m slogger tail <tmp>
  --format json -n 0` in a subprocess, appends a line, reads one stdout line, sends `SIGINT`, and
  asserts exit code `130` and that no `_meta` line was printed.
- Console follow prints `-- reopened <path>` to stderr on rotation; JSON mode prints nothing to
  stdout for it.

Exclusions: `watch`, `--timeout`, inode-based cursors, following rotated siblings, multi-file
follow.

### T8. Docs and wiring

Scope: `README.md` (new section "Reading logs" after "Testing": install note, the five commands
with one example each, cursor/`_meta` contract, exit codes), `CHANGELOG.md` (Unreleased entry),
`AGENTS.md` (layout table: add `tools/`, `cli.py`, `__main__.py`, `tests/fixtures/`; move the CLI
row out of the deferred table; add `python3 -m slogger` to the dev-setup block), `cli.md` status
line (`P0 implemented`). Depends on T1–T7.

Acceptance: `python3 -m ruff check src tests examples`, `python3 -m pyrefly check`,
`python3 -m pytest -q` green; `python3 -m slogger --help` lists exactly `query`, `tail`, `trace`,
`meta`, `fields`; README examples run as written from the repo root against the fixtures.

Exclusions: no console script, no `[cli]` extra, no PyPI rename, no output schemas.

## Checks (verified)

```bash
pip install -e ".[dev]"                     # already done in the Cloud Agent VM
python3 -m pytest -q                        # 66 passed at handoff time
python3 -m ruff check src tests examples    # All checks passed
python3 -m pyrefly check                    # 0 errors
python3 -m slogger --help                   # exists only after T4
```

Per-task test selection: `python3 -m pytest -q tests/test_tools_reader.py` and so on. Where
behaviour depends on stack walking or typing (`_STACKLEVEL_OFFSET`), `AGENTS.md` asks for runs on
3.10 and 3.13; the tools package does not touch stack walking, so 3.12 alone is sufficient for P0
unless a task changes `logger.py` or `span.py` (none should).
