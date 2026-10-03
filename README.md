# SLogger

Structured logging for Python, built on the standard library `logging` package.

Python 3.10 or newer.

**Docs:** [Public API](docs/api.md) · [CLI reference](docs/cli.md) · [Examples](#examples)

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

JSONL files written by `JSONFormatter` can be read with `python3 -m slogger` and
`slogger.tools`. Full option tables, exit codes, and recipes:
**[CLI reference](docs/cli.md)**. Tools API details: **[Public API — tools](docs/api.md#tools-api--sloggertools)**.

```bash
python3 -m slogger meta app.log
python3 -m slogger fields app.log
python3 -m slogger explain --level ERROR --where order_id=42
python3 -m slogger query app.log --level ERROR --where order_id=42
# MCP: python3 -m slogger.tools.mcp
python3 -m slogger query app.log --summary --group-by logger
python3 -m slogger trace app.log aaaa
python3 -m slogger tree app.log --status error --slower-than 500ms
python3 -m slogger stats app.log --spans --bucket 1m
python3 -m slogger errors app.log
python3 -m slogger validate app.log
python3 -m slogger context app.log --id 'app.log:42' -B 5 -A 5
python3 -m slogger diff before.log after.log --spans
python3 -m slogger watch app.log --level ERROR --timeout 30s
python3 -m slogger query a.log b.log --order time --limit 50
python3 -m slogger tail app.log --once --after 'app.log:100'
```

The same operations are available in Python via `slogger.tools` (exported from
`slogger.tools.__all__`, not the package root):

```python
from slogger.tools import Filters, Where, fields, meta, query, stats, summary, tail_once, trace, tree

info = meta("app.log")
page = query("app.log", filters=Filters(level_min=40), limit=50)
agg = summary("app.log", filters=Filters(where=(Where("user", "=", "ada"),)))
span_stats = stats("app.log", spans=True, bucket="1m")
rows = tree("app.log", status="error")
one = trace("app.log", trace_id="aaaa")
```

Python tooling also supports typed, composable predicates:

```python
from slogger.tools import Field, Filters, all_of, any_of, query

predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    any_of(Field("duration_ms").ge(500), Field("error_type").eq("TimeoutError")),
)
page = query("app.log", filters=Filters(predicate=predicate))
```

See [typed Python predicates](docs/api.md#typed-python-predicates) for nested fields,
array membership, presence checks, and matching rules. This API is available in
Python; CLI and MCP input interfaces retain their existing filters.

Shared CLI filter flags include `--level`, `--logger`, `--where KEYOPVALUE` (compact tokens such as
`user=ada` or `amount>=99`), `--has` / `--missing`, `--grep`, `--since` / `--until`, and
`--exclude-events`. Use `--order time` to merge multiple files by timestamp (default `concat`).
Aggregates accept `--format table` for plain-text columns.

With `--format json` (the default when stdout is not a TTY), `query`, `context`, and
`tail --once` write JSONL records plus a trailing `{"_meta": {...}}` control line that carries `next_cursor`, `returned`, and
`skipped_lines`. Live `tail` streams records without a trailing control line. `_id` and
resume cursors are preserved when truncating output. Aggregate commands write one JSON object with `schema_version`. Exit codes:
`0` success, `1` when `--fail-if-any` matched, `2` data error, `3` watch timeout, `64` usage
error, `130` interrupted.

Design notes (implementation history): [`docs/plans/cli.md`](docs/plans/cli.md),
[`docs/plans/cli-p0-handoff.md`](docs/plans/cli-p0-handoff.md),
[`docs/plans/cli-p1-handoff.md`](docs/plans/cli-p1-handoff.md),
[`docs/plans/cli-p2-handoff.md`](docs/plans/cli-p2-handoff.md).

### Shell completion

Activate the Python environment where slogger is installed, then install the
completion extra from the repository root (already included in `[dev]`):

```bash
python3 -m pip install -e '.[cli]'
```

Completion registers the `slogger` command, so create a shell function for the module
invocation and load the script for your shell.

**Bash** — run these lines, or add them to `~/.bashrc` for future sessions:

```bash
slogger() { python3 -m slogger "$@"; }
eval "$(python3 -m slogger completion --shell bash)"
```

**Zsh** — run these lines, or add them to `~/.zshrc`. If your shell framework
already initializes completion, omit the `compinit` line and load slogger's
script after that initialization:

```zsh
unalias slogger 2>/dev/null
autoload -Uz compinit && compinit
slogger() { python3 -m slogger "$@"; }
eval "$(python3 -m slogger completion --shell zsh)"
```

Use the function above instead of an alias in Zsh: alias expansion can bypass
the registered `slogger` completer. The `unalias` line removes an older setup.
If you used the previous instructions, replace the old `alias slogger=...` line
in `~/.zshrc` with this block, then run `source ~/.zshrc` in your terminal.
Verify it by typing `slogger tre` and pressing Tab: it should become
`slogger tree`. Likewise, `slogger tra` should complete to `slogger trace`.
Use the `slogger` command for completion; this setup does not register completion
for the literal `python3 -m slogger` invocation.

**Fish** — run these lines, or add them to `~/.config/fish/config.fish`:

```fish
alias slogger 'python3 -m slogger'
python3 -m slogger completion --shell fish | source
```

When saving this setup in a startup file, place it after your Python environment
activation so `python3` can import slogger and argcomplete. Open a new shell or
source the edited startup file to apply it.

Type `slogger ` and press Tab to complete subcommands and options. With a log
file on the command line, `slogger query app.log --logger ` offers logger names,
`--where ` offers field names, and `--where user=` offers values from the file.
Replace `app.log` and `user` with your own file and field. See the
[completion reference](docs/cli.md#completion) for more details.

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

Typed tooling predicates expose immutable execution-independent IXR through
`predicate.to_ixr()`, including required-field analysis and versioned inspection.
Python matching compiles lazily; see [the Python interface](docs/api.md).
