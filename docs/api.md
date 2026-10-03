# Public API reference

Python 3.10+. Install with `pip install -e ".[dev]"` so imports resolve through the
editable install (the package lives under `src/slogger`).

Public names fall into two packages:

| Import | What it covers |
| --- | --- |
| `import slogger` | Logging: configure, loggers, spans, `@instrument`, formatters, schema, testing |
| `from slogger.tools import ...` | Reading JSONL logs, including Python-only typed predicates |

Tools and CLI names are **not** re-exported from `slogger.__init__`. Prefer
`import slogger` for new code; `from slogger.slogger import builtin_logger, instrument`
still works via a compatibility shim.

---

## Quick start

```python
import slogger

slogger.configure(level=slogger.INFO, json_file="app.log")
log = slogger.get_logger("app")

log.info("started", version="1.4.0")

with log.span("checkout", user="ada") as span:
    span.set(items=3)
    log.info("charging", order_id="42", amount=99.5)
```

---

## Configuration — `slogger.configure`

`import slogger` does **not** open files or attach handlers. Call `configure` at
application startup. With no call, the first emit installs a console handler at
`INFO` and does not open a file.

```python
import slogger
import sys

slogger.configure(
    level=slogger.INFO,
    console=True,
    console_level=slogger.INFO,
    console_stream=sys.stderr,
    json_file="app.log",          # omit to skip the file
    json_file_level=slogger.DEBUG,
    capture_stdlib=True,          # attach to root so third-party logs share formatting
    span_events=True,             # emit span.start / span.end
)
```

| Argument | Default | Meaning |
| --- | --- | --- |
| `level` | `INFO` | Level of the logger handlers attach to |
| `console` | `True` | Attach a colour-aware console handler |
| `console_level` | `level` | Handler level for the console |
| `console_stream` | stderr | Stream the console handler writes to |
| `json_file` | none | UTC midnight-rotating JSONL file (7 backups) |
| `json_file_level` | `DEBUG` | Handler level for that file |
| `handlers` | none | Extra handlers, added as well as the ones above |
| `capture_stdlib` | `True` | Attach to the root logger |
| `span_events` | `True` | Emit `span.start` / `span.end` |

`capture_stdlib=False` attaches handlers to the logger named `"slogger"` and stops
it propagating. Only `slogger` and `slogger.*` are captured in that mode.

Calling `configure` again removes the handlers it installed last time. Handlers
something else installed are left alone. Reconfiguration is transactional: new
handlers are built first; a failure restores the previous config. In-flight
slogger records are gated during the swap.

Related helpers:

- `slogger.config.reset()` — tear down for tests
- `slogger.config.is_configured()` — whether `configure` has run
- `slogger.config.ensure_configured()` — lazy console default on first emit

---

## Loggers — `slogger.get_logger` / `SLogger`

```python
import slogger

log = slogger.get_logger("app.db")
log.info("connected", host="localhost", port=5432)
log.set_level(slogger.WARNING)  # this name and unset children

# builtin_logger is get_logger("slogger")
slogger.builtin_logger.debug("internal")
```

`get_logger(name)` returns the same `SLogger` instance for the same name.
`None` uses `"slogger"`. A logger with no level of its own inherits from its
parent, then from the level passed to `configure`.

### Bound fields

`bind` returns a **new** logger with extra fields. The original is unchanged.
Call kwargs override span fields, which override bound fields.

```python
request_log = log.bind(request_id="abc", user="ada")
request_log.info("started")                 # request_id=abc user=ada
request_log.unbind("request_id").info("ok") # user=ada only
```

### Log methods

`debug`, `info`, `warning`, `error`, `critical`, `fatal`, and `exception` accept
keyword fields. `level` and `msg` are positional-only so they can be used as
field names:

```python
log.info("retry", level="soft", msg="will retry")  # fields named level / msg
log.exception("charge failed")                     # ERROR + current exception
log.error("boom", exc_info=True, stack_info=True)
```

`exc_info`, `stack_info`, and `stacklevel` keep their stdlib meaning.

### Spans on a logger

```python
with log.span("checkout", user="ada") as span:
    span.set(items=3)
    log.info("charging")
```

See [Spans](#spans--sloggerspan) below.

---

## Spans — `slogger.Span`

A span is a ContextVar scope that merges fields into every record emitted inside
the block (including stdlib loggers whose handlers carry a `ContextFilter`).

```python
with log.span("checkout", user="ada") as span:
    span.set(items=3)
    # Nested spans inherit parent fields and the same trace_id.
    with log.span("charge", order_id="42"):
        log.info("charging", amount=99.5)
```

Lifecycle without `with`:

```python
span = log.span("work", job="nightly")
span.start()
try:
    do_work()
finally:
    span.end()
```

Behaviour notes:

- Entering logs `span.start` at DEBUG; leaving logs `span.end` with
  `duration_ms` and `status` (`ok`, or `error` plus `error_type`, `error`, and
  the traceback). Exceptions are not swallowed.
- Fields on every record inside the span: `span`, `span_id`, `trace_id`, and
  `parent_span_id` when nested, plus any context passed to `span()` / `set()`.
- `span(..., events=False)` or `configure(span_events=False)` disables events.
  `events=True` on a span forces them back on.
- Close a span only in the ContextVar context that entered it.
- `asyncio.create_task` copies the span; threads do not — use
  [`wrap_context`](#thread-context--wrap_context--run_in_executor).

---

## `@instrument` — `slogger.instrument`

Opens a span for the duration of a sync or async function.

```python
from slogger import get_logger, instrument

log = get_logger("shop")

@instrument(capture=["order_id"], logger=log, attempts=1)
def charge(order_id: str, amount: float) -> None:
    log.info("charging", amount=amount)

@instrument("fetch", capture="url")
async def fetch(url: str) -> bytes:
    ...
```

| Argument | Meaning |
| --- | --- |
| `name` | Span name (defaults to the function name) |
| `capture` | Parameter name(s) to copy onto the span; unknown names raise at decoration time |
| `logger` | Logger used for span events (default: `get_logger("slogger")`, resolved at call time) |
| `events` | Forwarded to `SLogger.span` |
| `**context` | Constant fields on every call |

Sync start/end events are attributed to the caller. Async events stay on the
wrapper (the event loop resumes the coroutine).

---

## Thread context — `wrap_context` / `run_in_executor`

```python
from concurrent.futures import ThreadPoolExecutor
from slogger import get_logger, run_in_executor, wrap_context

log = get_logger("app")
pool = ThreadPoolExecutor()

def work(n: int) -> None:
    log.info("worker", n=n)

with log.span("batch"):
    pool.submit(wrap_context(work), 1)          # sees the span
    # await run_in_executor(loop, None, work, 1)
```

---

## Formatters and handlers

Usually you only call `configure`. The factories and formatters are public when
you need a custom setup:

```python
from slogger import (
    ConsoleFormatter,
    JSONFormatter,
    get_console_handler,
    get_structured_file_handler,
)

handler = get_console_handler(level=20)
file_handler = get_structured_file_handler("app.log", level=10)
```

Console lines look like:

```text
2026-09-26T16:23:56.239Z INFO     app.db  connected  host=localhost  span=checkout
```

Colour follows the TTY unless `NO_COLOR` is set; `FORCE_COLOR` forces it on.
JSON is one object per line (UTC ISO-8601 with milliseconds). Non-JSON values
are converted via `json_default`. Cyclic containers or unsupported mapping keys fall
back to a string for the affected field; a failing `repr` uses a placeholder.

`ColoredFormatter` is an alias of `ConsoleFormatter`.

---

## Schema — `LogRecord` / `validate_log_record`

Fixed keys: `timestamp`, `level`, `logger`, `message`, `file`, `func`, `line`
(+ optional `exception`, `stack`). Span fields when present: `event`, `status`,
`duration_ms`, `error_type`, `error`, `span`, `span_id`, `parent_span_id`,
`trace_id`. A context field that reuses a reserved name is written as
`ctx_<name>`.

```python
import json
from slogger import LogRecord, log_record_json_schema, validate_log_record

def load_line(line: str) -> LogRecord:
    return validate_log_record(json.loads(line))

schema = log_record_json_schema()  # draft 2020-12; also shipped as package data
```

`validate_log_record` checks required fields and known optional types. Extra
keys (user context) are allowed. It does not depend on the `jsonschema` package.

Contract sources of truth: `slogger.schema` (`LogRecord`, `SCHEMA_KEYS`) and
`slogger/schemas/log-record.schema.json`.

---

## Testing — `capture_logs`

Collects the same structured dicts a JSON handler would emit:

```python
from slogger import capture_logs, get_logger

def test_checkout():
    log = get_logger("shop")
    with capture_logs() as records:
        log.info("charging", order_id="42")
    assert records[0]["message"] == "charging"
    assert records[0]["order_id"] == "42"
```

If slogger was never configured, capture installs a silent config (no console)
that remains active after capture; the temporary handler is removed on exit. Pass `logger="shop.api"` to attach only to that name,
or `level=...` to filter what is collected.

---

## Package exports (`slogger.__all__`)

```text
CRITICAL, DEBUG, ERROR, FATAL, INFO, WARNING
SLogger, Span, builtin_logger, get_logger
configure, instrument, wrap_context, run_in_executor
ConsoleFormatter, ColoredFormatter, JSONFormatter
get_console_handler, get_structured_file_handler, get_batched_structured_file_handler
LogRecord, log_record_json_schema, validate_log_record
capture_logs
```

---

## Tools API — `slogger.tools`

Read JSONL written by `JSONFormatter`. Source-based functions accept a path, a
list of paths/globs, `"-"`, or an in-memory iterable of dicts (for example the
list from `capture_logs()`). `follow` and `watch` accept a single file path or
`"-"`; schema and filter helpers operate on their own documented inputs.
`trace` and same-trace expansion in `context` spool stdin to a temporary file
for replay, preserving physical-line record IDs. The file is removed on exit.

```python
from slogger.tools import (
    Filters,
    Where,
    context,
    diff,
    failures,
    fields,
    meta,
    query,
    stats,
    summary,
    tail_once,
    trace,
    tree,
    validate,
    watch,
)

info = meta("app.log")
keys = fields("app.log", top=10)
page = query(
    "app.log",
    filters=Filters(level_min=40, where=(Where("order_id", "=", "42"),)),
    limit=50,
)
agg = summary("app.log", group_by="logger")
rows = tree("app.log", status="error", slower_than_ms=500)
one = trace("app.log", trace_id="aaaa")
span_stats = stats("app.log", spans=True, bucket="1m")
```

### Shared filters

```python
from slogger.tools import Filters, Where, parse_where

filters = Filters(
    level_min=40,                         # or level_exact=...
    logger="app.pay",                     # exact or prefix (stdlib hierarchy)
    where=(Where("user", "=", "ada"), parse_where("amount>=99")),
    has=("order_id",),
    missing=("exception",),
    grep=r"timeout",
    since=None, until=None,               # optional datetime bounds
    span="checkout",
    trace="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    exclude_events=True,                  # drop span.start / span.end
)

# Inspect / rebuild legacy filters (also accepted by MCP):
explained = filters.explain()             # {"schema_version", "filters", "notes"}
restored = Filters.from_mapping(explained["filters"])
```

`--where` / `Where` operators: `= != > < >= <= ~ !~` (regex). Multiple clauses
are ANDed. Comparison follows the type of the record value; a missing key never
matches (use `missing=` / `--missing`).

### Typed Python predicates

Use `Field`, `all_of`, `any_of`, and `not_` to build richer Python filters:

```python
from slogger.tools import Field, Filters, all_of, any_of, logger_prefix, not_, query

predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    any_of(Field("duration_ms").ge(500), Field("error_type").eq("TimeoutError")),
    Field("request", "method").eq("POST"),
    Field("tags").contains_all(["payment", "retry"]),
    not_(Field("synthetic").eq(True)),
    logger_prefix("app.pay"),
)
page = query("app.log", filters=Filters(predicate=predicate), limit=50)
```

`Field`, `Predicate`, and the composition helpers are exported from `slogger.tools`,
not the root logging package. `Predicate` is an abstract base for the expressions
returned by field methods and helpers; do not construct it directly.
`Filters(predicate=...)` works wherever a tool accepts `filters=`. Existing
`Filters` conditions AND with the new predicate. There is no new CLI or MCP
input syntax.

| Python API | Matching behavior |
| --- | --- |
| `Field(*path)` | One literal key or explicit nested mapping path |
| `.eq(value)`, `.ne(value)` | Typed equality/inequality, including structural JSON equality |
| `.gt(value)`, `.ge(value)`, `.lt(value)`, `.le(value)` | Number or string ordering |
| `.in_(values)`, `.not_in(values)` | Scalar membership/exclusion against scalar candidates |
| `.exists()`, `.missing()` | Presence/absence, distinct from null |
| `.regex(pattern)` | Python regex search on a string field |
| `.starts_with(prefix)` | Ordinary string prefix |
| `.contains_any(values)`, `.contains_all(values)` | Array contains any/all scalar candidates |
| `all_of(*predicates)`, `any_of(*predicates)`, `not_(predicate)` | Nested AND, OR, and logical NOT |
| `logger_prefix(name)` | Exact logger name or descendants under `name + "."` |

`Field("request.method")` reads a literal key containing a dot;
`Field("request", "method")` traverses two mappings. Non-mapping intermediate
values make the path missing. Paths do not index arrays or implicitly traverse
array elements.

New predicates preserve operand types: `eq(42)` differs from `eq("42")`.
Integers and floats compare numerically, but booleans remain distinct from numbers,
including inside JSON arrays and objects. Ordering supports numbers with numbers
and strings with strings. Missing or incompatible values fail comparisons,
including `ne` and `not_in`; `exists()` includes present nulls. Logical negation
inverts that result, so `not_(Field("x").eq(1))` also matches a missing `x`.
For `not_in`, a present scalar must have a compatible type with at least one
candidate (or the candidate list must be empty).

Membership candidates must be JSON scalars; `in_` does not search inside a record
array. Array operations accept list/tuple record values, compare immediate
members, and ignore candidate multiplicity. `contains_all(["a", "a"])` only needs
one `"a"`. New regex/prefix predicates require strings and never stringify arrays.
Operands must be finite JSON-compatible values and are snapshotted at construction.
Invalid paths, operands, composition arguments, or regex patterns raise immediately.
Existing `Where` clauses retain their previous string conversion behavior.

Empty `all_of()` matches every record; empty `any_of()` matches none. `in_([])`
matches none; `not_in([])` matches present scalars. For arrays, `contains_any([])`
is false and `contains_all([])` is true. Missing fields still fail both.
Use composition functions; applying Python `and`, `or`, or `bool()` to a predicate
raises `TypeError`.

Predicates also work directly on mappings:

```python
from slogger.tools import Field

predicate = Field("duration_ms").ge(500)
assert predicate.matches({"duration_ms": 700})
matcher = predicate.compile()  # lazy cached callable; regex validated at construction
assert matcher({"duration_ms": 700})
description = predicate.explain()  # detached JSON-compatible inspection data
```

Compiled matchers short-circuit boolean branches and do not mutate records.
File filtering remains streaming; the existing reader materializes in-memory
iterables to support replay and cursors. Predicate construction consumes candidate
iterables once, independently of reading log sources.

`trace()` uses matching records to select a trace and reconstructs all its records.
`tree()` and `stats(spans=True)` select groups/traces using matching source records,
then reconstruct spans from their full lifecycle. Predicates do not run on synthetic
span summaries. Existing span-name and anchor-time aggregate rules still apply.
`context()` always retains its requested anchor; predicates select neighboring
records, while same-trace context remains unfiltered. Filtered `fields()` calls
bypass the unfiltered field-discovery cache.

`Filters.explain()` preserves the legacy version-1 shape when no predicate is
present. Rich filters add `filters.predicate` containing its own `schema_version: 1`
and `expression` description. These descriptions are inspection-only:
`Filters.from_mapping()` rebuilds legacy filters and rejects mappings containing
`predicate` rather than silently discarding it. Store/reuse Python predicates
for library calls; a JSON query-loading API is outside this release.

#### Execution-independent IXR inspection

`Predicate.to_ixr()` returns an immutable logical expression from
`slogger.tools.ixr`. Field paths are explicit tuples; the tree contains typed
literal snapshots and no executable callbacks or dataframe objects.

```python
expression = predicate.to_ixr()
fields_needed = expression.required_fields()  # frozenset of path tuples
inspection = expression.explain()  # {"version": 1, "expression": ...}
```

IXR inspection is versioned and detached from execution. It is not a JSON query
loader contract. Existing `Predicate.explain()` and `Filters.explain()` retain their
inspection shapes, and `Filters.from_mapping()` continues its existing legacy
mapping contract. Python matching compiles lazily and reuses its callable.
Custom `Predicate` subclasses remain usable for Python matching; their default
`to_ixr()` raises a clear `TypeError` unless they provide a logical representation.

### Finite-source query plans

`scan()` creates an immutable `QueryPlan` using the same paths, globs, stdin,
source sequences and finite in-memory iterables as `Reader`. Construction and
static explanation do not open files or consume iterators.

```python
from slogger.tools import Field, scan

base = scan([{"level": "INFO", "message": "one"},
             {"level": "ERROR", "message": "two"}])
plan = base.filter(Field("level").eq("ERROR")).select("message").limit(1)
result = plan.execute()  # backend="python" is the default
assert result.records == [{"message": "two", "_id": "mem:1"}]
assert result.schema == ("message",)
explanation = plan.explain()
```

Each builder method returns a new plan. Call order determines meaning:
filter-before-limit finds the first N matches; limit-before-filter checks only
those first N input records. `limit(0)` returns no rows. This differs from legacy
`query(limit=0)`, whose existing behavior remains unchanged. Negative, boolean,
and non-integer limits are rejected. `select()` requires distinct nonempty literal
top-level field names; nested predicates use `Field("request", "method")`.

A scan has an open schema: unknown fields may be missing. Selection closes that
schema; filtering or selecting a removed field raises `ToolError` with
`code="plan_invalid"` before reading the source. Projection preserves `_id` in
returned records, but hidden identity does not make a discarded user field
available to later expressions. Missing selected fields remain absent.

`PlanResult` contains `records`, `schema`, `warnings`, and `metadata`. Schema is
an ordered tuple of possible output field names; on an unprojected result it is
inferred from returned records. Hidden `_id` is excluded unless explicitly
selected. Metadata includes backend, input/output row counts, skipped lines,
ordering and identity preservation. Input counts describe rows yielded by Reader, not physical lines or prefetched
records. Skipped-line counts and warnings can include Reader prefetch for time
ordering. These counters are not an independent full-source scan.
Original nested values and absent keys are preserved.

Python filter/select/limit execution streams file records and materializes output.
Use a limit to bound returned records. Reader materializes in-memory iterables at
execution time; a one-shot generator is consumed and cannot be replayed by a later
execution. Supplied collections are read at execution time, not snapshotted when
the plan is built. Sources must finish; arbitrary live query plans are outside
this interface. Owned file iterators close on completion, limits and failures.

`explain()` reports operations in builder order, required field paths, open/closed
schema, ordering, identity, output bounds and pending runtime checks. It does not
verify source existence or finiteness. Unsupported backends raise
`backend_unsupported`; predicates without IXR raise `expression_unsupported` on
plan preparation. Execution failures raise `execution_failed` and retain their
cause. Existing `query()` returns `Page` and retains its cursor behavior; query
plans do not accept source cursors.


#### Group-by and numeric aggregation

Python plans support multiple literal scalar grouping keys and named reductions:

```python
from slogger.tools import Field, count_rows, mean_of, scan, sum_of

result = (scan([{"logger": "pay", "duration_ms": 2},
                {"logger": "pay", "duration_ms": 4}])
          .group_by("logger")
          .aggregate(events=count_rows(), total_ms=sum_of(Field("duration_ms")),
                     average_ms=mean_of(Field("duration_ms")))
          .filter(Field("events").ge(2))
          .execute())
assert result.records == [{"logger": "pay", "events": 2,
                           "total_ms": 6, "average_ms": 3.0}]
```

`group_by(*keys)` returns an immutable, non-executable builder completed by
`aggregate(**named)`. Use `plan.aggregate(...)` directly for ungrouped reduction.
The helpers are `count_rows()`, `sum_of(Field(...))`, `mean_of(Field(...))`,
`min_of(Field(...))`, and `max_of(Field(...))`. Numeric helpers accept nested paths.
Count counts all rows. Numeric reductions skip missing/null and reject booleans,
strings, arrays, objects and nonfinite numbers with `data_incompatible`.
Integer count/sum results remain exact. Nonfinite reduction outputs and mean
intermediate sums raise `data_incompatible`. Mean is floating-point; adapter comparisons
use relative tolerance `1e-12` and absolute tolerance `1e-12`.

Empty ungrouped input produces one row: count/sum zero and mean/min/max null.
Empty grouped input produces no rows. Missing grouping keys remain absent in the
output, distinct from present null. Boolean and numeric groups are distinct;
compatible numbers such as 1 and 1.0 share a group without converting integers
universally to float. Arrays/objects and nonfinite group keys are rejected.
Groups follow first appearance in input order and retain the first key value.

Grouping keys must be unique. Aggregate aliases must not collide with grouping
keys or `_id`. Aggregation drops source identity and closes the output schema to
group keys and aggregate aliases; subsequent filters/projections/limits operate
on those fields. Aggregation consumes the full finite upstream input and initially
uses input-proportional working memory, even with a downstream limit.


#### Optional native Polars execution

Install the `tools-polars` extra from this checkout (`pip install -e ".[tools-polars]"`)
and explicitly call `plan.execute(backend="polars")`. Polars is imported only when
selected; ordinary logging and Python tooling need no dataframe dependency.
The supported compatibility floor is Polars 1.29 on Python 3.10–3.13.

Polars sorting is not yet supported. Native aggregation is supported; see
[the aggregation capability notes](polars-aggregation.md). Native filter/select/limit supports sparse
fields and explicit nested mapping paths containing mixed scalar values: booleans,
signed Int64 integers, finite floats, strings, and nulls. Presence and typed value
lanes keep missing distinct from null and booleans distinct from numbers. Non-mapping
path intermediates count as missing; dotted keys remain literal.
Equality, inequality, ordering, scalar membership, presence and boolean composition
execute as native expressions. Original records are
reconstructed using source ordinals, preserving nested values, `_id`, and absent
projected fields. Projection does not require unrelated values to be scalar.

Structural comparisons, referenced array/object values and array membership remain
unsupported. Native prefixes/logger matching and a [plain-literal regex subset](plans/ixr-polars-strings.md)
are supported; other regex constructs are rejected before reading sources. Integers outside Int64 and mixed integer/float
comparisons at magnitudes at least 2**53 are conservatively rejected to avoid precision
loss. No Python object UDF or silent Python fallback is
used. Each batch is bound independently, including late fields and types; later
incompatible data raises an error
without returning a successful partial result.

Filtering reads bounded batches of up to 1024 rows. A downstream limit can therefore
leave `input_rows` and skipped-line accounting ahead of returned rows. A limit
before a filter bounds that filter's input. Output is materialized; batching does
not make returned output bounded-memory. Static Polars explanation does not read
sources and lists data-dependent capability checks as pending.

Errors use `dependency_missing` for absent Polars, `expression_unsupported` or
`operation_unsupported` for unsupported logical features, and `data_incompatible`
for unsupported values or precision ranges. Unexpected execution errors retain their
cause under `execution_failed`. No automatic backend selection is performed.

### Sorting finite query results

```python
from slogger.tools import scan

result = scan([{"duration_ms": 2}, {"duration_ms": 1}, {}]).sort_by(
    "duration_ms", descending=True, missing="last", nulls="last",
).limit(2).execute()
assert [row["duration_ms"] for row in result.records] == [2, 1]
```

`sort_by()` accepts one literal top-level field, a boolean `descending` flag,
and independent `missing` / `nulls` placements (`"first"` or `"last"`, default
`"last"`). Present values must be finite compatible numbers or strings; booleans,
arrays, objects, nonfinite numbers and mixtures of strings/numbers raise
`ToolError(code="data_incompatible")` with the field and logical operation index.
Numeric ordering preserves exact integer values without universal float casts.
String ordering uses Python Unicode ordering.

Direction reverses present values only. When both missing and null are first,
missing precedes null; when both are last, null precedes missing. Equal values,
missing rows and null rows follow their original Reader traversal ordinals,
including after repeated sorts. Projection retains original `_id` values.
Filtering or sorting a projected-away field fails before reading input.

Sorting materializes its entire input and requires finite sources. A downstream
limit does not bound sorting memory or input reads. An upstream limit restricts
the domain to sort, so `limit(10).sort_by(...)` differs from
`sort_by(...).limit(10)`. Static explanation reports blocking execution and
input-proportional working memory, with value-domain checks pending until execution.
Sorted output preserves record identity and marks `source_cursor_eligible=False`;
this does not add cursors to the query-plan interface. The finite-source interface
has no live/unbounded execution mode; callers must ensure supplied iterators finish.

## Main entry points

| Function | Role |
| --- | --- |
| `meta` | File sizes, record counts, time range, loggers, spans, level histogram |
| `fields` | Key discovery (types, cardinality, samples); `key=` for top values; optional `cache=` sidecar |
| `scan` | Immutable finite-source filter/select/limit/sort query plans; Python execution |
| `query` | Filtered page of records (`limit`, `after` cursor, `last`, projection) |
| `summary` | Aggregate counts (`group_by` optional); also `query --summary` on the CLI |
| `Filters.explain` | Normalised filter predicate (no sources); CLI: `explain` |
| `trace` | One trace (or `--group-by` group) as a span tree |
| `tree` | One row per reconstructed trace |
| `stats` | Level/logger/span aggregates, percentiles, optional time buckets |
| `failures` | Grouped error records and failed spans (CLI: `errors`) |
| `validate` | Schema-check lines with `validate_log_record` |
| `context` | Neighbours / same-trace window around a record id |
| `diff` | Compare `stats` between two source sets |
| `tail_once` / `follow` | Poll or follow new records |
| `watch` | Block until a match or timeout |
| `output_schemas` / `validate_tool_output` | Published aggregate / list `_meta` contracts |

`Page` (from `query` / `tail_once` / `context`) carries `records`, `next_cursor`,
`skipped_lines`, and `warnings`. Record ids look like `app.log:42` (or
`mem:0` for in-memory sources).

Ordering: `order="concat"` (default) walks sources in turn; `order="time"` merges
by timestamp using a streaming merge. Each input should already be ordered;
out-of-order input produces warnings and is not globally re-sorted. Rotated siblings (`app.log.2026-09-26`) sort before the live file
within a glob.

CLI JSON mode defaults `query` / `tail --once` to a limit of 200 when unset
(`--limit 0` removes the cap). The Python `query(..., limit=None)` API stays
unbounded unless you pass a limit.

Full CLI option tables and shell examples: [`cli.md`](cli.md). Design notes:
[`plans/cli.md`](plans/cli.md). P2 plan (`explain`, schemas, completion, MCP):
[`plans/cli-p2-handoff.md`](plans/cli-p2-handoff.md).

Tool aggregate contracts are published as package data
(`slogger/schemas/tool-output.schema.json`) and checked with:

```python
from slogger.tools import meta, output_schemas, validate_tool_output

validate_tool_output("meta", meta("app.log"))
defs = output_schemas()["$defs"]
```

MCP stdio server (no extra SDK)::

```bash
python3 -m slogger.tools.mcp
```

The MCP transport uses newline-delimited JSON-RPC. Each tool advertises and
validates its own input schema, including required arguments. Stdin (`"-"`)
is unavailable as a log source through MCP because it carries protocol messages.

Span statistics reconstruct each trace before grouping. A span uses its start
record for group attribution and time-window filtering, falling back to its end
record when the start is missing. Span-name filters apply to reconstructed nodes.

Calling `configure()` or `reset()` inside a logging emission callback raises
`RuntimeError`; reconfigure outside the callback. Nested logging remains supported.
