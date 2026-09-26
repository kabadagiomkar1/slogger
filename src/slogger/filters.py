"""Inject the active span into records that did not come from slogger."""

from __future__ import annotations

import logging

from slogger.formatters import CONTEXT_ATTR
from slogger.span import SPAN_CONTEXT


class ContextFilter(logging.Filter):
    """Copy the active span's context onto records that lack it.

    Install this on handlers, not loggers: logger filters are not applied to
    records that propagate in from a child logger, but handler filters are.
    Records emitted by :class:`slogger.logger.SLogger` already carry
    ``slog_context`` and are left untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, CONTEXT_ATTR):
            span = SPAN_CONTEXT.get()
            setattr(record, CONTEXT_ATTR, dict(span.context) if span is not None else {})
        return True
