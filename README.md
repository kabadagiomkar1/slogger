# SLogger

Structured logging for Python, built on the standard library `logging` package.

Python 3.10 or newer.

**Docs:** [Public API](docs/api.md) · [Examples](#examples)

## Features

- Structured fields on every log call, written as JSON or as a console line
- Named loggers that follow the stdlib hierarchy
- `bind()` for fields that stick to one logger
- `span()` context blocks that record start, end, duration, and status
- `@instrument` for sync and async functions
- The active span is applied to stdlib and third-party loggers as well
- `exc_info`, `stack_info`, `stacklevel`, and `exception()`

## Install

The package lives under `src/slogger`. Install it in editable mode so imports
resolve through the install, not the checkout path:

```bash
pip install -e ".[dev]"
```

The `dev` extra includes pytest, Ruff, [Pyrefly](https://pyrefly.org/), and
argcomplete for the completion tests. Activate your environment before running checks:

```bash
python3 -m pytest -W error
python3 -m ruff check src tests examples
python3 -m pyrefly check --min-severity warn
```

The `examples` extra adds FastAPI and uvicorn: `pip install -e ".[examples]"`.

## Configure

Importing slogger does not create a log file or attach handlers. Call `configure` once at startup:

```python
import slogger

slogger.configure(
    level=slogger.INFO,
    json_file="app.log",          # omit to skip the file
    json_file_level=slogger.DEBUG,
)
```

With no call at all, the first log record installs a console handler at INFO and does not open a file.

| Argument | Default | Meaning |
| --- | --- | --- |
| `level` | `INFO` | Level of the logger the handlers are attached to |
| `console` | `True` | Attach a console handler |
| `console_level` | `level` | Handler level for the console |
| `console_stream` | stderr | Stream the console handler writes to |
| `json_file` | none | Rotating JSON file (UTC midnight, 7 backups) |
| `json_file_level` | `DEBUG` | Handler level for that file |
| `handlers` | none | Extra handlers, added as well as the ones above |
| `capture_stdlib` | `True` | Attach handlers to the root logger |
| `span_events` | `True` | Emit `span.start` / `span.end` |

`capture_stdlib=False` attaches handlers to the logger named `slogger` and stops it propagating. Only `slogger` and `slogger.*` are captured in that mode.

Calling `configure` again removes the handlers it installed last time. Handlers something else installed are left alone. If building or attaching the replacement handlers fails, the previous configuration stays active.
Configure during application startup. Slogger records already in flight are protected during a
reconfiguration; direct stdlib records emitted concurrently are subject to the stdlib logging
module's normal configuration race.

## Loggers

`get_logger(name)` returns the same object for the same name. `builtin_logger` is `get_logger("slogger")`. A logger with no level of its own inherits from its parent, then from the level passed to `configure`.

```python
import slogger

log = slogger.get_logger("app.db")
log.info("connected", host="localhost")
log.set_level(slogger.WARNING)  # app.db and its children
```

`bind` returns a new logger with extra fields. The original is unchanged. Call arguments override span fields, which override bound fields.

```python
request_log = log.bind(request_id="abc")
request_log.info("started")          # request_id=abc
request_log.unbind("request_id")     # a third logger, without that field
```

`exc_info`, `stack_info`, and `stacklevel` mean the same thing they mean in the stdlib. `exception()` is ERROR plus the current exception. `level` and `msg` are positional-only, so they can be used as field names.

## Spans

```python
with log.span("checkout", user="ada") as span:
    span.set(items=3)
    log.info("charging")
```

Records inside the block include `user`, `items`, `span`, `span_id`, `trace_id`, and `parent_span_id` when there is a parent. Nested spans inherit the parent's fields and its `trace_id`. The same context is visible to `logging.getLogger(...)` calls, because handlers installed by `configure` copy it onto records that did not come from slogger.

Entering a span logs `span.start` at DEBUG. Leaving it logs `span.end` with `duration_ms` and `status` (`ok`, or `error` plus `error_type`, `error`, and the traceback). An exception is not swallowed. `span(..., events=False)` or `configure(span_events=False)` turns the events off for one span or for the process. `events=True` on a span forces them back on.

`start()` and `end()` run the same lifecycle without a `with` block. `end()` before `start()`, and a second `end()`, do nothing.

`asyncio.create_task` copies the span. A `ThreadPoolExecutor` does not; wrap the callable:

```python
from slogger import wrap_context, run_in_executor

pool.submit(wrap_context(work), arg)
await run_in_executor(loop, None, work, arg)
```

## instrument

```python
from slogger import instrument

@instrument(capture=["order_id"], logger=log, attempts=1)
def charge(order_id, amount):
    log.info("charging", amount=amount)
```

`capture` names parameters to copy onto the span (a single string is fine). A name that is not a parameter raises `ValueError` when the function is decorated. Other keyword arguments are constant fields. Sync and async functions are both supported.

Start and end events for a sync function point at its caller. Async events point at the wrapper in this package: the event loop resumes the coroutine, so the original caller is no longer on the stack.

## Console and JSON

Console lines look like:

```text
2026-09-26T16:23:56.239Z INFO     app.db  connected  host=localhost  span=checkout
```

Span and trace fields are dimmed when colour is on. Colour is on when the stream is a TTY, unless `NO_COLOR` is set. `FORCE_COLOR` turns it on anyway. Strings with spaces are quoted.

JSON is one object per line. The timestamp is UTC ISO-8601 with milliseconds. `datefmt` on the formatter still overrides it. Values that are not JSON (datetimes, `Decimal`, `UUID`, paths, sets, exceptions, arbitrary objects) are converted instead of dropping the record. Cyclic containers and unsupported mapping keys fall back to a string for that field; a failing `repr` uses a placeholder.

Fixed keys are `timestamp`, `level`, `logger`, `message`, `file`, `func`, `line`, and, when present, `exception` and `stack`. A context field that reuses one of those names is written as `ctx_<name>`. Everything else is flat on the object: call fields, bound fields, span fields (`span`, `span_id`, `parent_span_id`, `trace_id`, `event`, `duration_ms`, `status`, `error_type`, `error`).

### Formal schema

The same contract is published two ways for tooling:

- `slogger.LogRecord` — a `TypedDict` for annotating parsed JSON lines in Python
- `slogger.log_record_json_schema()` — the JSON Schema (draft 2020-12), also shipped as package data at `slogger/schemas/log-record.schema.json`

```python
import json
from slogger import LogRecord, validate_log_record

def load_line(line: str) -> LogRecord:
    return validate_log_record(json.loads(line))
```

`validate_log_record` checks required fields and known optional types. Extra keys (user context) are allowed. It does not depend on the `jsonschema` package.

## Testing

`capture_logs()` collects the same structured dicts your JSON handler would emit, without reading a file:

```python
from slogger import capture_logs, get_logger

def test_checkout():
    log = get_logger("shop")
    with capture_logs() as records:
        log.info("charging", order_id="42")
    assert records[0]["message"] == "charging"
    assert records[0]["order_id"] == "42"
```

If slogger was never configured, capture installs a silent config (no console) that remains active after capture. The temporary capture handler is removed on exit. Pass `logger="shop.api"` to attach only to that logger name, or `level=...` to filter what is collected.

## Reading logs

Query finite JSONL files or in-memory records with `slogger.tools`:

```python
from slogger.tools import Field, all_of, any_of, scan

condition = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    any_of(Field("duration_ms").ge(500), Field("error_type").eq("TimeoutError")),
)
result = scan("app.log").filter(condition).limit(50).execute()
```

Python execution is the default. Install `[tools-polars]` and pass
`backend="polars"` for the supported native dataframe operations. See the
[tools API](docs/api.md#tools-api--sloggertools) and
[execution compatibility](docs/execution-compatibility.md).

**Breaking tooling change:** legacy Filters/Where, query/Page/summary, specialized
trace/tree/context/stats/diff tools, CLI, completion, and MCP have been removed.
There are no compatibility aliases. Use query plans for retained record queries
and grouping; trace/tree reconstruction and live watching are withdrawn until
future designs. The core logging library and emitted log schema are unchanged.

## Migrating from 0.1

- Call `configure()` (or let the first record install the console default). The library no longer creates `app.log` on import, and `builtin_logger` is no longer given its own handlers.
- `builtin_logger` used to be a logger named `builtin_logger`. It is now named `slogger`.
- Timestamps used to look like `2026-09-26 21:53:56,239`. They are now `2026-09-26T16:23:56.239Z`.
- Spans emit start and end records. Pass `events=False` to keep the old silence.
- `from slogger.slogger import builtin_logger, instrument` still works. New code can use `import slogger`.

## Examples

Each example is runnable from the repository root:

```bash
python3 examples/basic.py
python3 examples/named_loggers.py
python3 examples/spans.py
python3 examples/stdlib_integration.py
python3 examples/thread_context.py
python3 examples/division.py
```

- `basic.py` — structured fields, `bind()` / `unbind()`, and exception logging
- `named_loggers.py` — logger hierarchy, inherited levels, and subsystem overrides
- `spans.py` — nested spans, trace IDs, sync/async `@instrument`, and task propagation
- `stdlib_integration.py` — context and formatting on ordinary `logging` records
- `thread_context.py` — the difference between a plain worker and `wrap_context()`
- `division.py` — JSON file output and an instrumented calculation
- `echo_server.py` — FastAPI integration; requires the `examples` extra

Run the server example with:

```bash
python3 examples/echo_server.py
```

Recent reliability fixes preserve span fields named `stacklevel`, `exc_info`, and
`stack_info`; reject reconfiguration inside emission callbacks instead of
hanging; and support stdin replay for trace/context tools. Span aggregates apply
name and anchor-time filters after reconstruction and retain bounded group state.
The MCP server uses newline-delimited JSON-RPC with per-tool argument validation.

Typed tooling builders return immutable IXR directly, including required-field
analysis and versioned inspection. Use `&`, `|`, and `~` or composition helpers;
compilation belongs to the selected adapter. See [the Python interface](docs/api.md).

Python tooling also provides immutable finite-source plans:
`scan(sources).filter(predicate).select("message").limit(50).execute()`.
Plans preserve operation order and source IDs, validate field dependencies, and
explain without reading sources. See [query plans](docs/api.md#finite-source-query-plans).

Python plans also support `.group_by("logger").aggregate(events=count_rows())`
and ungrouped numeric reductions. Aggregate results omit source IDs; grouping
keeps missing/null and boolean/number distinctions. See the query-plan docs.

With the optional `tools-polars` extra, `plan.execute(backend="polars")` runs a
native sparse/mixed scalar subset with explicit nested paths. Backend support and precision restrictions are documented
in [query plans](docs/api.md#optional-native-polars-execution); Python remains the default.

Python query plans support global `sort_by("duration_ms", descending=True)` with
explicit missing/null placement and stable source identity. Sorting requires finite
input and memory proportional to its input; a downstream limit does not bound it.

The optional Polars adapter supports native array `contains_any` / `contains_all`
for homogeneous scalar arrays with optional nulls. Mixed/nested arrays and unsafe
numeric domains fail explicitly; see [native array coverage](docs/plans/ixr-native-arrays.md).

Polars also executes global multi-key grouping and count/sum/mean/min/max natively.
See [aggregation capabilities and exactness limits](docs/polars-aggregation.md).

Polars plans support native string prefixes, logger hierarchy matching and a
[plain-literal regex subset](docs/plans/ixr-polars-strings.md). Other regex constructs
raise explicit capability errors; Python regex behavior remains unchanged.

Polars plans also support [global native sorting](docs/plans/ixr-polars-sorting.md),
with stable source ties, independent missing/null placement and explicit numeric
precision limits. Global sorting requires input-proportional memory.

New query plans coexist with existing cursor, cache, trace and live tooling calls.
See [execution compatibility](docs/execution-compatibility.md).

For executable IXR inspection, sorting and group-by examples, run
`python examples/query_plans.py` (or `--backend polars` with `tools-polars` installed).
The [benchmark report](benchmarks/README.md) includes a reproducible 100,000-row
matrix, complete query timings and peak memory. Python remains the default;
see the [API capability limits](docs/api.md#optional-native-polars-execution).

Native floating sum/mean use checked exact binary fixed-point lanes; integer-only
reductions retain native Int128 numerators. Python floating reductions use
compensated summation across supported interpreter versions. See the aggregation
capability notes for explicit scale and range limits.
