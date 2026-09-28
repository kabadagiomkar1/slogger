# Public API reference

Python 3.10+. Install with `pip install -e ".[dev]"` so imports resolve through the
editable install (the package lives under `src/slogger`).

Public names fall into two packages:

| Import | What it covers |
| --- | --- |
| `import slogger` | Logging: configure, loggers, spans, `@instrument`, formatters, schema, testing |
| `from slogger.tools import ...` | Reading JSONL logs (same operations as `python3 -m slogger`) |

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
are converted via `json_default` so a log call never fails on its payload.

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
for the duration of setup. Pass `logger="shop.api"` to attach only to that name,
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

Read JSONL written by `JSONFormatter`. Every function accepts a path, a list of
paths/globs, `"-"`, or an in-memory iterable of dicts (for example the list from
`capture_logs()`).

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
    since=..., until=...,                 # datetime
    span="checkout",
    trace="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    exclude_events=True,                  # drop span.start / span.end
)
```

`--where` / `Where` operators: `= != > < >= <= ~ !~` (regex). Multiple clauses
are ANDed. Comparison follows the type of the record value; a missing key never
matches (use `missing=` / `--missing`).

### Main entry points

| Function | Role |
| --- | --- |
| `meta` | File sizes, record counts, time range, loggers, spans, level histogram |
| `fields` | Key discovery (types, cardinality, samples); `key=` for top values |
| `query` | Filtered page of records (`limit`, `after` cursor, `last`, projection) |
| `summary` | Aggregate counts (`group_by` optional); also `query --summary` on the CLI |
| `trace` | One trace (or `--group-by` group) as a span tree |
| `tree` | One row per reconstructed trace |
| `stats` | Level/logger/span aggregates, percentiles, optional time buckets |
| `failures` | Grouped error records and failed spans (CLI: `errors`) |
| `validate` | Schema-check lines with `validate_log_record` |
| `context` | Neighbours / same-trace window around a record id |
| `diff` | Compare `stats` between two source sets |
| `tail_once` / `follow` | Poll or follow new records |
| `watch` | Block until a match or timeout |

`Page` (from `query` / `tail_once` / `context`) carries `records`, `next_cursor`,
`skipped_lines`, and `warnings`. Record ids look like `app.log:42` (or
`mem:0` for in-memory sources).

Ordering: `order="concat"` (default) walks sources in turn; `order="time"` merges
by timestamp. Rotated siblings (`app.log.2026-09-26`) sort before the live file
within a glob.

CLI JSON mode defaults `query` / `tail --once` to a limit of 200 when unset
(`--limit 0` removes the cap). The Python `query(..., limit=None)` API stays
unbounded unless you pass a limit.

Full CLI option tables and shell examples: [`cli.md`](cli.md). Design notes:
[`plans/cli.md`](plans/cli.md). P2 plan (`explain`, schemas, completion, MCP):
[`plans/cli-p2-handoff.md`](plans/cli-p2-handoff.md).
