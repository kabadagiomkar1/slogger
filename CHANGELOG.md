# Changelog

## 0.2.0

Configuration is explicit, loggers are named, and spans record their own start and end.

- Package moved to a `src/` layout; install with `pip install -e ".[dev]"` before running tests or examples.

- `import slogger` no longer creates `app.log` or attaches handlers. Call `configure()`.
- `get_logger(name)` returns a cached logger. `builtin_logger` is `get_logger("slogger")`.
- `bind()` / `unbind()` add fields without mutating the original logger.
- Handlers installed by `configure()` sit on the root logger by default, so stdlib and third-party records are rendered the same way and pick up the active span.
- Spans emit `span.start` and `span.end` with `span_id`, `parent_span_id`, `trace_id`, `duration_ms`, and `status`.
- Console output includes the structured fields. Timestamps are UTC ISO-8601. Colour follows the TTY, `NO_COLOR`, and `FORCE_COLOR`.
- `wrap_context()` and `run_in_executor()` carry the active span into worker threads.
- Requires Python 3.11+.

## 0.1.0

Initial release: JSON logging, `span`, and `instrument`, including async functions.
