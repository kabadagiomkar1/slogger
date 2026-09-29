"""Spans: a contextvars scope that also records start and end events."""

from __future__ import annotations

import logging
import secrets
import time
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slogger.logger import SLogger

# Active span for the current task or thread. Read by SLogger and ContextFilter.
SPAN_CONTEXT: ContextVar[Span | None] = ContextVar("SPAN_CONTEXT", default=None)

# Key under which the active span's name is stored in the log context.
SPAN_KEY = "span"


def _events_enabled(override: bool | None) -> bool:
    if override is not None:
        return override
    # Imported lazily: config installs filters, and filters import this module.
    from slogger.config import span_events_enabled

    return span_events_enabled()


class Span:
    """A named context pushed onto :data:`SPAN_CONTEXT` for a block of code.

    Entering a span merges its fields into every log record emitted inside the
    block, including records from stdlib loggers whose handlers carry a
    :class:`~slogger.filters.ContextFilter`. On exit it emits ``span.end`` with
    ``duration_ms`` and ``status``.

    Use it as a context manager, or call :meth:`start` and :meth:`end` yourself.
    """

    def __init__(
        self,
        logger: SLogger,
        name: str,
        *,
        events: bool | None = None,
        event_stacklevel: int = 1,
        bound: dict | None = None,
        context: dict | None = None,
    ) -> None:
        self._logger = logger
        self._name = name
        self._events = events
        self._event_stacklevel = event_stacklevel
        self._bound = dict(bound or {})
        self._own_context = dict(context or {})
        self._context: dict = {}
        self._span_id = secrets.token_hex(8)
        self._parent_span_id: str | None = None
        self._trace_id: str | None = None
        self._token = None
        self._started = False
        self._closed = False
        self._start: float | None = None

    def start(self, *, stacklevel: int = 1) -> Span:
        """Push this span and emit ``span.start``. A second call is a no-op."""
        if self._started or self._closed:
            return self
        self._started = True

        parent = SPAN_CONTEXT.get()
        if parent is not None:
            self._parent_span_id = parent.span_id
            self._trace_id = parent.trace_id
            merged = {**self._bound, **parent.context, **self._own_context}
        else:
            self._parent_span_id = None
            self._trace_id = secrets.token_hex(16)
            merged = {**self._bound, **self._own_context}

        merged[SPAN_KEY] = self._name
        merged["span_id"] = self._span_id
        merged["trace_id"] = self._trace_id
        if self._parent_span_id is not None:
            merged["parent_span_id"] = self._parent_span_id
        else:
            merged.pop("parent_span_id", None)
        self._context = merged

        self._token = SPAN_CONTEXT.set(self)
        self._start = time.perf_counter()
        if _events_enabled(self._events):
            try:
                # ``stacklevel`` counts callers of ``start``. +1 skips ``start``
                # itself so the record points at ``with`` or at the direct caller.
                self._logger.debug(
                    "span.start",
                    event="span.start",
                    stacklevel=stacklevel + 1,
                )
            except BaseException:
                assert self._token is not None
                SPAN_CONTEXT.reset(self._token)
                self._token = None
                self._start = None
                self._started = False
                self._context = {}
                raise
        return self

    def end(self, exc: BaseException | tuple | None = None, *, stacklevel: int = 1) -> None:
        """Pop this span and emit ``span.end``. Further calls are no-ops.

        ``exc`` is an exception instance or an ``(type, value, traceback)`` tuple.
        When it is set the event is logged at ERROR with ``status="error"`` and
        the exception is not swallowed: :meth:`__exit__` still returns ``None``.
        """
        if self._closed or self._token is None:
            return

        # A ContextVar token may only be reset in the exact context where it
        # was created. Copies made for tasks and threads carry the same Span
        # object, so marking it closed before this succeeds would strand the
        # span in its owner context forever.
        try:
            SPAN_CONTEXT.reset(self._token)
        except ValueError:
            return

        self._token = None
        self._closed = True
        if self._start is not None and _events_enabled(self._events):
            # The active parent was restored before logging. Explicit span
            # fields override it so this event still belongs to the ending span.
            self._emit_end(exc, stacklevel + 1)

    def close(self) -> None:
        """Pop the span without recording an error. Alias of :meth:`end`."""
        self.end()

    def set(self, **context: object) -> None:
        """Add fields visible to later records and to the ``span.end`` event."""
        self._context.update(context)

    def __enter__(self) -> Span:
        return self.start(stacklevel=1 + self._event_stacklevel)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        exc = (exc_type, exc_value, traceback) if exc_type is not None else None
        self.end(exc, stacklevel=1 + self._event_stacklevel)

    async def __aenter__(self) -> Span:
        return self.start(stacklevel=1 + self._event_stacklevel)

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        exc = (exc_type, exc_value, traceback) if exc_type is not None else None
        self.end(exc, stacklevel=1 + self._event_stacklevel)

    @property
    def name(self) -> str:
        return self._name

    @property
    def context(self) -> dict:
        return self._context

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def parent_span_id(self) -> str | None:
        return self._parent_span_id

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    def _emit_end(self, exc: BaseException | tuple | None, stacklevel: int) -> None:
        assert self._start is not None
        duration_ms = round((time.perf_counter() - self._start) * 1000, 3)
        fields: dict = {
            **self._context,
            "event": "span.end",
            "duration_ms": duration_ms,
            "status": "ok",
        }
        if exc is None:
            # Direct dispatch skips the public level wrapper.
            self._logger._log(logging.DEBUG, "span.end", fields, stacklevel=stacklevel)
            return

        if isinstance(exc, tuple):
            exc_type, exc_value = exc[0], exc[1]
            exc_info: BaseException | tuple = exc
        else:
            exc_type, exc_value = type(exc), exc
            exc_info = exc
        fields["status"] = "error"
        fields["error_type"] = exc_type.__name__ if isinstance(exc_type, type) else str(exc_type)
        fields["error"] = str(exc_value)
        self._logger._log(
            logging.ERROR, "span.end", fields, exc_info=exc_info, stacklevel=stacklevel
        )
