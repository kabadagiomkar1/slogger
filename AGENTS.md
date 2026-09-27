# AGENTS.md

Guidance for AI agents working on **slogger** — a structured logging library on top of Python’s stdlib `logging`.

## What this project is

- Small, opinionated wrapper: keyword fields, named loggers, `bind()`, spans with start/end events, `@instrument`, stdlib context injection.
- Distinctive idea: `@instrument(capture=[...])` with sync/async support and ContextVar spans.
- Not a reimplementation of structlog/loguru; keep the surface small and stdlib-native.
- Target users will build tooling on top (CLI, OTel bridge, etc.). Prefer a stable record schema over feature sprawl.

## Layout

```text
src/slogger/          # installable package (src layout — required)
  logger.py           # SLogger, get_logger, bind/unbind
  span.py             # Span, SPAN_CONTEXT, span events / IDs
  instrument.py       # @instrument
  config.py           # configure(), reset(), emission gate
  formatters.py       # JSONFormatter, ConsoleFormatter, record_to_dict
  formators.py        # deprecated compat re-export — keep until announced removal
  filters.py          # ContextFilter (span → stdlib records)
  handlers.py         # console / rotating JSON file factories
  schema.py           # LogRecord TypedDict, validate_log_record, SCHEMA_KEYS
  schemas/            # log-record.schema.json (package data)
  testing.py          # capture_logs()
  context.py          # wrap_context, run_in_executor
  slogger.py          # thin compat shim for old imports
  tools/              # log-file reader API (query, trace, meta, fields, tail)
  cli.py              # argparse layer for python -m slogger
  __main__.py         # python -m slogger entry point
tests/                # pytest; imports the *installed* package
  fixtures/logs/      # shared JSONL fixtures for tools/CLI tests
examples/             # runnable demos (fastapi example needs [examples])
docs/plans/           # designs: cli.md + cli-p0-handoff.md; processor-pipeline.md (deferred)
```

Do **not** put the package back at the repo root. Tests must not rely on `PYTHONPATH=.` to import a checkout-flat `slogger/`.

## Dev setup

```bash
pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests examples
python -m pyrefly check
python -m slogger --help
```

- Python **3.10–3.13** (`requires-python = ">=3.10"`).
- Caller attribution uses `_STACKLEVEL_OFFSET` (0 on &lt;3.11, 2 on 3.11+) because `Logger.findCaller` semantics changed. Keep both versions green when touching stack walking.
- Examples: `pip install -e ".[examples]"` for FastAPI/uvicorn.

## Core conventions

### Configuration

- `import slogger` must **not** create files or attach handlers.
- Call `configure(...)` at app startup. Lazy default on first emit: console only, no file.
- Handlers from `configure()` attach to **root** by default (`capture_stdlib=True`) so third-party logs share formatting and span context.
- Reconfigure is transactional: build new handlers first; restore previous config on failure. Use the emission gate so in-flight slogger emits aren’t dropped mid-swap.

### Context and spans

- User/span context lives under one LogRecord attribute (`CONTEXT_ATTR = "slog_context"`), never spread into `extra=` keys that collide with LogRecord attrs.
- Merge order on emit: bound fields → active span context → call kwargs.
- Spans emit `span.start` / `span.end` with `span_id`, `parent_span_id`, `trace_id`, `duration_ms`, `status`. Toggle with `configure(span_events=...)` or `span(..., events=False)`.
- Close spans only in the ContextVar context that entered them; cross-task `end()` must not strand the owner.
- Threads need `wrap_context` / `run_in_executor`; asyncio tasks copy contextvars already.

### Schema

- Fixed keys: `timestamp`, `level`, `logger`, `message`, `file`, `func`, `line` (+ optional `exception`, `stack`).
- Span fields when present: `event`, `status`, `duration_ms`, `error_type`, `error`, `span`, `span_id`, `parent_span_id`, `trace_id`.
- Collisions with reserved keys → `ctx_<key>` (and unique `ctx_` prefixes if needed).
- Contract sources of truth: `schema.py` (`LogRecord`, `SCHEMA_KEYS`) and `schemas/log-record.schema.json`. Keep them aligned.
- Timestamps: UTC ISO-8601 with milliseconds (`...Z`) unless `datefmt` overrides.
- JSON serialization must never fail the log call (`json_default` / `repr` fallback).

### Public API

- Export new public names from `slogger/__init__.py` and `__all__`.
- Keep `from slogger.slogger import builtin_logger, instrument` working via the shim.
- `builtin_logger` is `get_logger("slogger")` (not the old `"builtin_logger"` name).
- `level` / `msg` on log methods are positional-only so they can be used as context field names.
- Support `exc_info`, `stack_info`, `stacklevel`, and `exception()`.

## Testing

- Prefer **`capture_logs()`** for structured assertions (same JSON shape as file output).
- The shared `records` fixture in `tests/conftest.py` wraps `capture_logs()`.
- Use raw `logging.Handler`s only when testing handler lifecycle or needing a live `LogRecord` (formatters).
- Do not add `src` to pytest `pythonpath`; editable install is required.
- After behavioral changes, run pytest on **3.10 and 3.13** when stacklevel/findCaller or typing is involved.

## Packaging / naming

- PyPI name **`slogger` is already taken** (unrelated package). Do not assume `pip install slogger` publishes this repo; pick a different name before publishing.
- Ship `py.typed` and JSON schemas via package-data.
- `formators.py` is intentionally kept as a deprecated alias of `formatters.py`.

## Deferred / out of scope (for now)

Do not implement these unless the user asks; designs may live under `docs/plans/`:

| Item | Notes |
|------|--------|
| Processor pipeline | Redact / sample / `configure(processors=...)` — see `docs/plans/processor-pipeline.md` |
| OpenTelemetry exporter | Bridge span lifecycle → OTel; keep optional and off the hot path by default |
| CLI P1+ | `tree`, `stats`, `errors`, `validate`, `context`, `diff`, `watch`, `--group-by`, completion — see `docs/plans/cli.md` |
| Framework middleware | e.g. FastAPI request spans beyond `@instrument` examples |
| CI workflows | Not present yet |

## When changing code

- Match existing module style: focused modules, explicit `__all__`, type hints on the public surface.
- Prefer fixing edge cases (config ownership, ContextVar lifecycle, serialization) over new abstractions.
- Update `CHANGELOG.md` (Unreleased / 0.2.x) and README when public behavior changes.
- Keep examples runnable and aligned with `configure()` (no import-time `app.log`).
