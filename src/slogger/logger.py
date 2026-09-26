"""Named loggers that emit structured records through stdlib ``logging``."""

from __future__ import annotations

import logging
import sys
import threading

from slogger.formatters import CONTEXT_ATTR
from slogger.span import SPAN_CONTEXT, Span

DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL

_LOGGERS: dict[str, SLogger] = {}
_LOGGERS_LOCK = threading.Lock()

# ``Logger.findCaller`` changed in 3.11: it only counts frames outside the
# logging package. Our wrappers live outside logging, so on 3.11+ we must
# skip ``_log`` and the public level method. On 3.10 and earlier every frame
# is counted, and the same absolute offset would overshoot into the caller.
_STACKLEVEL_OFFSET = 0 if sys.version_info < (3, 11) else 2


class SLogger:
    """A named structured logger.

    Keyword arguments on a log call become structured fields. Fields bound with
    :meth:`bind` and fields from the active :class:`~slogger.span.Span` are
    merged in first; call arguments win.

    ``exc_info``, ``stack_info``, and ``stacklevel`` keep their stdlib meaning.
    ``level`` and ``msg`` are positional-only, so they can be used as field names.
    """

    def __init__(self, name: str, *, _bound: dict | None = None) -> None:
        self._logger = logging.getLogger(name)
        self._bound = dict(_bound or {})

    @property
    def name(self) -> str:
        return self._logger.name

    def set_level(self, level: int) -> None:
        """Set this logger's level. Children with no level of their own inherit it."""
        self._logger.setLevel(level)

    def bind(self, **context: object) -> SLogger:
        """Return a new logger with ``context`` merged into its bound fields.

        The result shares the underlying stdlib logger (and therefore its
        handlers and level) but bound fields are not shared: binding either
        logger again leaves the other unchanged.
        """
        return SLogger(self.name, _bound={**self._bound, **context})

    def unbind(self, *keys: str) -> SLogger:
        """Return a new logger without the given bound keys."""
        bound = {key: value for key, value in self._bound.items() if key not in keys}
        return SLogger(self.name, _bound=bound)

    def span(
        self,
        name: str,
        *,
        events: bool | None = None,
        event_stacklevel: int = 1,
        **context: object,
    ) -> Span:
        """Build a span attributed to this logger.

        ``events`` overrides the global ``configure(span_events=...)`` setting.
        ``event_stacklevel`` adds frames above the ``with`` statement when the
        span is opened from a wrapper (the :func:`~slogger.instrument.instrument`
        decorator uses this).
        """
        return Span(
            self,
            name,
            events=events,
            event_stacklevel=event_stacklevel,
            bound=self._bound,
            context=context,
        )

    def add_handler(self, handler: logging.Handler) -> None:
        """Attach ``handler`` to this named logger only.

        Handlers installed here do not affect other logger names. Prefer
        :func:`slogger.configure` when every logger should share a destination.
        A :class:`~slogger.filters.ContextFilter` is added so records from
        child loggers that propagate here still receive the active span.
        """
        from slogger.filters import ContextFilter

        if not any(isinstance(existing, ContextFilter) for existing in handler.filters):
            handler.addFilter(ContextFilter())
        self._logger.addHandler(handler)

    def debug(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg, /, *args, **kwargs) -> None:
        """Log at ERROR with ``exc_info`` defaulting to the current exception."""
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def fatal(self, msg, /, *args, **kwargs) -> None:
        self._log(logging.FATAL, msg, *args, **kwargs)

    def _log(self, level: int, msg, /, *args, **kwargs) -> None:
        from slogger.config import emission_guard, ensure_configured

        ensure_configured()
        with emission_guard():
            if not self._logger.isEnabledFor(level):
                return

            exc_info = kwargs.pop("exc_info", None)
            stack_info = kwargs.pop("stack_info", False)
            stacklevel = kwargs.pop("stacklevel", 1)

            if exc_info:
                if isinstance(exc_info, BaseException):
                    exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
                elif not isinstance(exc_info, tuple):
                    exc_info = sys.exc_info()

            current = SPAN_CONTEXT.get()
            span_context = current.context if current is not None else {}
            # Lowest precedence first: bound fields, then the active span, then this call.
            context = {**self._bound, **span_context, **kwargs}

            # ``stacklevel=1`` points at the user's call site. The version
            # offset accounts for the 3.11 findCaller semantics change.
            fn, lno, func, sinfo = self._logger.findCaller(
                stack_info=stack_info,
                stacklevel=stacklevel + _STACKLEVEL_OFFSET,
            )
            record = self._logger.makeRecord(
                self._logger.name,
                level,
                fn,
                lno,
                msg,
                args,
                exc_info,
                func,
                extra={CONTEXT_ATTR: context},
                sinfo=sinfo,
            )
            self._logger.handle(record)


def get_logger(name: str | None = None) -> SLogger:
    """Return the shared :class:`SLogger` for ``name``.

    The same name always returns the same instance. ``None`` uses ``"slogger"``.
    The underlying stdlib logger is left at ``NOTSET``, so it inherits its level
    from its parents and ultimately from the level passed to
    :func:`slogger.configure`.
    """
    resolved = name or "slogger"
    with _LOGGERS_LOCK:
        existing = _LOGGERS.get(resolved)
        if existing is None:
            existing = SLogger(resolved)
            _LOGGERS[resolved] = existing
        return existing


builtin_logger = get_logger("slogger")
