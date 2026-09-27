# Changelog

## Unreleased

- Adds `slogger.tools` and `python3 -m slogger` for reading JSONL logs: `query`, `meta`,
  `fields`, `trace`, and `tail` (follow / `--once`). See `docs/plans/cli.md`.

## 0.2.0

Configuration is explicit, loggers are named, and spans record their own start and end.

- Package moved to a `src/` layout; install with `pip install -e ".[dev]"` before running tests or examples.
- Supports Python 3.10 through 3.13 (caller attribution adjusts for the 3.11 `findCaller` change).
- Publishes a formal log-record contract as `LogRecord` (TypedDict), JSON Schema, and `validate_log_record()`.
- Adds [pyrefly](https://pyrefly.org/) to the `dev` extra with `[tool.pyrefly]` project settings.
- Adds `capture_logs()` for asserting on structured records in tests.
- Defers the processor pipeline; design notes live in `docs/plans/processor-pipeline.md`.

- `import slogger` no longer creates `app.log` or attaches handlers. Call `configure()`.
- `get_logger(name)` returns a cached logger. `builtin_logger` is `get_logger("slogger")`.
- `bind()` / `unbind()` add fields without mutating the original logger.
- Handlers installed by `configure()` sit on the root logger by default, so stdlib and third-party records are rendered the same way and pick up the active span.
- Spans emit `span.start` and `span.end` with `span_id`, `parent_span_id`, `trace_id`, `duration_ms`, and `status`.
- Console output includes the structured fields. Timestamps are UTC ISO-8601. Colour follows the TTY, `NO_COLOR`, and `FORCE_COLOR`.
- `wrap_context()` and `run_in_executor()` carry the active span into worker threads.
- Requires Python 3.10+.

## 0.1.0

Initial release: JSON logging, `span`, and `instrument`, including async functions.
