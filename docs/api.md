# Public API reference

Python 3.10+. Install with `pip install -e ".[dev]"` so imports resolve through the
editable install (the package lives under `src/slogger`).

Public names fall into two packages:

| Import | What it covers |
| --- | --- |
| `import slogger` | Logging: configure, loggers, spans, `@instrument`, formatters, schema, testing |
| `from slogger.tools import ...` | Finite structured-log queries through direct IXR expressions |

Tooling names are **not** re-exported from `slogger.__init__`. Prefer
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

The tooling library exposes immutable finite-source query plans. Legacy filters,
query/Page/summary, specialized reconstruction tools, CLI, completion, and MCP
have been removed without compatibility aliases. The core logging API above is
unchanged. Grouping queries do not reconstruct trace or span trees.

### Typed IXR expressions

Use `Field`, `all_of`, `any_of`, and `not_` to build richer Python filters:

```python
from slogger.tools import Field, all_of, any_of, logger_prefix, not_, scan

predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    any_of(Field("duration_ms").ge(500), Field("error_type").eq("TimeoutError")),
    Field("request", "method").eq("POST"),
    Field("tags").contains_all(["payment", "retry"]),
    not_(Field("synthetic").eq(True)),
    logger_prefix("app.pay"),
)
result = scan("app.log").filter(predicate).limit(50).execute()
```

`Field` and composition helpers are exported from `slogger.tools`, independently
of the root logging package. They return immutable IXR nodes directly. Explicit
node constructors such as `Compare`, `Literal`, and `And` are also exported there.

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

IXR expressions preserve operand types: `eq(42)` differs from `eq("42")`.
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
one `"a"`. Regex/prefix expressions require strings and never stringify arrays.
Operands must be finite JSON-compatible values and are snapshotted at construction.
Invalid paths, operands, composition arguments, or regex patterns raise immediately.

Empty `all_of()` matches every record; empty `any_of()` matches none. `in_([])`
matches none; `not_in([])` matches present scalars. For arrays, `contains_any([])`
is false and `contains_all([])` is true. Missing fields still fail both.
Use composition functions or the `&`, `|`, and `~` operators. Python `and`, `or`,
and `bool()` raise `TypeError` to prevent accidental evaluation during construction.

```python
from slogger.tools import Field, scan

expression = Field("duration_ms").ge(500) & ~Field("synthetic").eq(True)
result = scan([{"duration_ms": 700}]).filter(expression).execute()
```

Compilation and matching belong to the selected adapter. Expressions contain no
cached matchers, conversion methods, callbacks, or dataframe objects. Membership
construction snapshots candidate iterables once, independently of reading sources.

#### Execution-independent IXR inspection

Field paths are explicit tuples and literals are immutable snapshots. Builders
already return the logical expression; no conversion is necessary.

```python
fields_needed = expression.required_fields()  # frozenset of path tuples
inspection = expression.explain()  # {"version": 1, "expression": ...}
```

IXR inspection is versioned and detached from execution. It is not a JSON query
loader contract.

### Finite-source query plans

`scan()` creates an immutable `QueryPlan` using the same paths, globs, stdin,
source sequences and finite in-memory iterables. Construction and
static explanation do not open files or consume iterators.

```python
from slogger.tools import Field, scan

base = scan([{"level": "INFO", "message": "one"},
             {"level": "ERROR", "message": "two"}])
plan = base.filter(Field("level").eq("ERROR")).select("message").limit(1)
result = plan.execute()  # backend="python" is the default
assert result.records == [{"message": "two"}]
assert result.origins[0].source == "mem"
assert result.origins[0].position == 1
assert result.schema == ("message",)
explanation = plan.explain()
```

Each builder method returns a new plan. Call order determines meaning:
filter-before-limit finds the first N matches; limit-before-filter checks only
those first N input records. `limit(0)` consumes no input even after a blocking operation. It skips
input-dependent checks and diagnostics upstream; static validation still runs.
A subsequent ungrouped aggregation can produce a summary of empty input. Negative, boolean,
and non-integer limits are rejected. `select()` requires distinct nonempty literal
top-level field names; nested predicates use `Field("request", "method")`.

A scan has an open schema: unknown fields may be missing. Selection closes that
schema; filtering or selecting a removed field raises `ToolError` with
`code="plan_invalid"` before reading the source. Projection preserves origin alongside records. A discarded application field
is unavailable to later expressions. Missing selected fields remain absent.

`PlanResult` contains `records`, aligned `origins`, `schema`, `warnings`, and
`metadata`. Schema contains application fields, including a logged `_id`.
Origin is a `SourceOrigin(source, position, kind)` (`kind` is `"file"`,
`"stdin"`, or `"iterable"`) or `None` for an aggregate
summary. File origins identify the concrete expanded path with one-based physical
line numbers; blank and malformed lines do not renumber subsequent records.
Stdin uses source `"-"` and one-based lines. Iterable sources use `"mem"`,
`"mem1"`, and so on, with zero-based original positions. Origin is navigation
metadata, not an automatically queryable field. Filtering, projection, and sorting
preserve alignment. No synthetic `_id` is inserted into records.

Metadata includes backend, input/output rows, skipped lines, ordering, and origin
preservation. Input counts describe yielded records, not all physical lines.
Warnings/skips can include timestamp-merge read-ahead. These counters do not
perform an independent full-source scan. Malformed JSON and non-object JSON are
skipped; blank lines are ignored.

Python filter/select/limit consumes records lazily and materializes output.
Polars filters consume native batches and may read ahead of a downstream limit.
Global sorting and aggregation materialize upstream input on both adapters.
Sources are not consumed at construction or explanation. Re-iterable collections
and files can execute again; iterators and stdin remain one-shot. Collection
records are copied when consumed, including nested data. No hidden replay occurs.
Owned files close on success, limits, and failures; caller-owned stdin and
iterators are not closed. Sources must finish; live watching is not supported.

`explain()` reports operations, dependencies, schema, ordering, origin
preservation, output bounds, and pending runtime checks. It does not verify
source existence or finiteness. Unsupported backends raise `backend_unsupported`.
Execution failures raise `execution_failed` and retain their cause.



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
use relative tolerance `1e-12` and absolute tolerance `1e-12`. Native Polars floating
sum/mean use exact binary fixed-point Int128 lanes with explicit scale/range checks;
integer-only sum/mean use native Int128 numerators. Minimum/maximum are unaffected.
Python uses compensated `math.fsum` for reductions containing floats and exact
integer accumulation otherwise, consistently across supported Python versions.

Empty ungrouped input produces one row: count/sum zero and mean/min/max null.
Empty grouped input produces no rows. Missing grouping keys remain absent in the
output, distinct from present null. Boolean and numeric groups are distinct;
compatible numbers such as 1 and 1.0 share a group without converting integers
universally to float. Arrays/objects and nonfinite group keys are rejected.
Groups follow first appearance in input order and retain the first key value.

Grouping keys must be unique. Aggregate aliases must not collide with grouping
keys. `_id` is ordinary application data, including as a group key or alias.
Aggregation drops single-record origin and closes the output schema to
group keys and aggregate aliases; subsequent filters/projections/limits operate
on those fields. Aggregation consumes the full finite upstream input and initially
uses input-proportional working memory, even with a downstream limit.


#### Optional native Polars execution

Install the `tools-polars` extra from this checkout (`pip install -e ".[tools-polars]"`)
and explicitly call `plan.execute(backend="polars")`. Polars is imported only when
selected; ordinary logging and Python tooling need no dataframe dependency.
The supported compatibility floor is Polars 1.29 on Python 3.10–3.13.

[Native global sorting](native-sorting.md) and
[native aggregation](polars-aggregation.md) are available with explicit domain/precision
limits. Native filter/select/limit supports sparse
fields and explicit nested mapping paths containing mixed scalar values: booleans,
signed Int64 integers, finite floats, strings, and nulls. Presence and typed value
lanes keep missing distinct from null and booleans distinct from numbers. Non-mapping
path intermediates count as missing; dotted keys remain literal.
Equality, inequality, ordering, scalar membership, presence and boolean composition
execute as native expressions. Original records are
reconstructed using source ordinals, preserving nested values and absent
projected fields. Projection does not require unrelated values to be scalar.

Native [array membership](native-arrays.md) supports homogeneous scalar
arrays, including empty arrays and null members, with explicit domain limits.
Structural equality and nested/object array members remain unsupported. Object
values can be checked for presence without profiling their contents. Native prefixes/logger matching and a [plain-literal regex subset](native-strings.md)
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
String ordering uses Python Unicode ordering. Polars execution supports this ordering
for its [documented native domains](native-sorting.md), with explicit
rejection of integers outside Int64 and unsafe mixed numeric ranges.

Direction reverses present values only. When both missing and null are first,
missing precedes null; when both are last, null precedes missing. Equal values,
missing rows and null rows follow their original source traversal ordinals,
including after repeated sorts. Projection retains origins alongside output.
Filtering or sorting a projected-away field fails before reading input.

Sorting materializes its entire input and requires finite sources. A downstream
limit does not bound sorting memory or input reads. An upstream limit restricts
the domain to sort, so `limit(10).sort_by(...)` differs from
`sort_by(...).limit(10)`. Static explanation reports blocking execution and
input-proportional working memory, with value-domain checks pending until execution.
Sorted output preserves origins alongside records. The finite-source interface
has no live/unbounded execution mode; callers must ensure supplied iterators finish.

## Query entry points

Import `Field`, `all_of`, `any_of`, `not_`, `logger_prefix`, `scan`, `QueryPlan`,
`PlanResult`, `GroupedPlan`, aggregation helpers, and `ToolError` from
`slogger.tools`. Builders return IXR directly; there is no separate predicate facade.
`SourceOrigin` and explicit IXR node types are also exported here.

`order="concat"` traverses sources in turn; `order="time"` merges already ordered
sources by timestamp. Timestamp merging is not global sorting. Rotated siblings
sort before the live file within a glob.


### Source examples and lifetime

```python
from slogger.tools import scan

files = scan(["worker.log", "api.log"])       # concatenate in the supplied order
rotations = scan("logs/app.log*")             # expand glob deterministically
chronological = scan(["worker.log", "api.log"], order="time")
redirected_input = scan("-")                  # finite stdin, read when executed
reusable = scan([{"message": "first"}, {"message": "second"}])
one_shot = scan(record for record in [{"message": "first"}])
```

These declarations read nothing. `reusable.execute()` can be called repeatedly;
executing `one_shot` consumes its generator and another execution sees only what
remains. Supply a fresh iterator for another complete query. Files are reopened
on each execution, so repeated queries may observe changed file contents.

`order="concat"` follows supplied source order. A glob sorts matches and places
recognized dated rotation siblings before their live file. `order="time"` uses a
k-way merge of individually timestamp-ordered sources, with equal timestamps
resolved by source order. It does not repair unsorted files. Missing/unparseable
timestamps use the previous timestamp from that source, or an initial minimum;
`untimestamped` and `out_of_order` warnings count affected consumed/buffered records.

Source resolution errors become `execution_failed` with the original exception
as cause. A zero limit does not open or consume input, even when earlier stages
would otherwise materialize it. Owned file handles close on errors and early
termination. Caller-owned stdin and iterator resources remain caller-owned.


## Stable investigation operations

`CacheStore`, `CacheClearResult`, `default_cache_dir`, `Investigation`, `CaptureStatus`,
`Diagnostic`, `SourceBoundary`, `RecordIdentity`,
`RecordPage`, `ResourceLimits`, `ResourceUsage`, and `ManagedStorage` are exported
from `slogger.tools` and `slogger.tools.investigation`. Headless capture and paging
do not import Textual. `Investigation.open(..., background=True)` establishes
source boundaries before returning and runs capture in its own worker; `wait(timeout)`
observes its status and `cancel()` retains an incomplete prefix. The default open
remains synchronous. Supplying `cache_dir` enables verified durable reuse;
`CacheStore.usage` reports global allocated/reserved bytes and `clear()` returns
protected/removed/reclaimed counts. The native launcher uses a durable default.
All complete-dataset operations use `require_ready`.
The optional `slogger.tools.tui.launch` consumer is installed
through `tools-tui` and the `slogger-tui` entry point. See the
[native investigation guide](native-investigation.md) for resource admission,
status/readiness, source boundaries, diagnostic paging, and close semantics.
Existing `QueryPlan.execute()` continues to return materialized results unchanged.


`parse_filter(text)` translates complete infix predicates into existing IXR;
`parse_field_path` and `format_field_path` round-trip nested and JSON-quoted exact
components. `FilterSyntaxError` carries offset, line and column. They are exported
from `slogger.tools`, independently of the native editor.

`Investigation.filter(expression, input_view=None, request_generation=0)` starts
reference evaluation over an explicit complete dataset/view scope. Exported
`ViewScope`, `FilterScope`, `OperationStatus`, `FilterJob`, and `RecordView` keep
requests and successful complete results structured and headless. Jobs support
status, diagnostics, `done`, cancellation, and `wait(timeout)`; timed waits raise
`TimeoutError`. Successful views support complete record counts, bounded pages,
dataset-ordinal position lookup and close. Failure/cancellation publishes no
partial view; old handles remain usable until their consumer closes them. Input
view leases protect dependent jobs. Session close joins registered operations
before releasing successful views and managed storage. See the native guide for
language, isolated regex execution, scope and admission details.
