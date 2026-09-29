"""Install handlers. Importing slogger does not log anywhere until this runs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from slogger.filters import ContextFilter
from slogger.handlers import get_console_handler, get_structured_file_handler
from slogger.logger import INFO

_lock = threading.RLock()
_configured = False
_span_events = True


class _EmissionGate:
    """Let records emit in parallel while configuration gets exclusive access."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0
        self._local = threading.local()

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        if getattr(self._local, "reading", False):
            yield
            return
        with self._condition:
            while self._writer or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
            self._local.reading = True
        try:
            yield
        finally:
            with self._condition:
                self._local.reading = False
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    def check_writable(self) -> None:
        if getattr(self._local, "reading", False):
            raise RuntimeError("cannot configure or reset logging during emission")

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


_emission_gate = _EmissionGate()


@dataclass
class _HandlerRegistration:
    target: logging.Logger
    handler: logging.Handler
    owns_handler: bool
    added_handler: bool
    added_filter: ContextFilter | None


@dataclass
class _LoggerState:
    logger: logging.Logger
    original_level: int
    original_propagate: bool
    installed_level: int | None = None
    installed_propagate: bool | None = None


_installed: list[_HandlerRegistration] = []
_logger_states: list[_LoggerState] = []


def is_configured() -> bool:
    return _configured


def span_events_enabled() -> bool:
    return _span_events


@contextmanager
def emission_guard() -> Generator[None, None, None]:
    """Keep handler configuration stable while one record is dispatched."""
    with _emission_gate.read():
        yield


def ensure_configured() -> None:
    """Apply the default configuration the first time a record is emitted.

    The default is a colour-aware console handler at INFO and no log file.
    """
    if _configured:
        return
    # Double-check while holding the same re-entrant lock used by configure:
    # concurrent first records must install one default handler, not one each.
    with _lock:
        if not _configured:
            configure()


def configure(
    *,
    level: int = INFO,
    console: bool = True,
    console_level: int | None = None,
    console_stream=None,
    json_file: str | None = None,
    json_file_level: int | None = None,
    handlers: list[logging.Handler] | None = None,
    capture_stdlib: bool = True,
    span_events: bool = True,
) -> None:
    """Install slogger's handlers.

    By default handlers are attached to the root logger, so records from
    stdlib and third-party loggers are rendered the same way and pick up the
    active span. Set ``capture_stdlib=False`` to attach them to the
    ``"slogger"`` logger instead and stop that logger from propagating; only
    loggers named ``slogger`` or ``slogger.*`` are captured in that mode.

    Calling :func:`configure` again removes the handlers it installed last
    time (and closes the ones it created) before installing the new set.
    Handlers it did not install are left in place. Handlers passed in
    ``handlers`` are added as well as the console and file handlers.

    Example::

        import slogger

        slogger.configure(level=slogger.INFO, json_file="app.log")
    """
    global _configured, _span_events

    _emission_gate.check_writable()

    # Construct owned handlers first. Opening a bad file must not tear down a
    # valid configuration that is already serving records.
    prepared: list[tuple[logging.Handler, bool]] = []
    try:
        if console:
            prepared.append(
                (
                    get_console_handler(
                        console_level if console_level is not None else level,
                        stream=console_stream,
                    ),
                    True,
                )
            )
        if json_file is not None:
            prepared.append(
                (
                    get_structured_file_handler(
                        json_file,
                        json_file_level if json_file_level is not None else logging.DEBUG,
                    ),
                    True,
                )
            )
        prepared.extend((handler, False) for handler in handlers or [])
    except Exception:
        for handler, owns in prepared:
            if owns:
                handler.close()
        raise

    with _lock, _emission_gate.write():
        previous_registrations = list(_installed)
        previous_states = list(_logger_states)
        previous_configured, previous_events = _configured, _span_events
        loggers = (logging.getLogger(), logging.getLogger("slogger"))
        logger_snapshots = [
            (logger, logger.level, logger.propagate, list(logger.handlers))
            for logger in loggers
        ]
        filter_snapshots = {
            handler: list(handler.filters)
            for handler in [r.handler for r in previous_registrations]
            + [handler for handler, _ in prepared]
        }
        _restore_configuration(close_handlers=False)
        _configured = False
        _span_events = span_events
        try:
            if capture_stdlib:
                target = logging.getLogger()
                slogger_logger = logging.getLogger("slogger")
                _set_propagate(slogger_logger, True)
            else:
                target = logging.getLogger("slogger")
                _set_propagate(target, False)
            _set_level(target, level)

            for handler, owns in prepared:
                _attach(target, handler, owns=owns)
        except Exception:
            _restore_configuration(close_handlers=False)
            for logger, old_level, propagate, old_handlers in logger_snapshots:
                logger.setLevel(old_level)
                logger.propagate = propagate
                logger.handlers[:] = old_handlers
            for handler, old_filters in filter_snapshots.items():
                handler.filters[:] = old_filters
            _installed[:] = previous_registrations
            _logger_states[:] = previous_states
            _configured, _span_events = previous_configured, previous_events
            for handler, owns in prepared:
                if owns:
                    handler.close()
            raise
        else:
            _configured = True
            # A reused owned handler stays open and retains its ownership.
            for registration in previous_registrations:
                if not registration.owns_handler:
                    continue
                reused = [r for r in _installed if r.handler is registration.handler]
                if reused:
                    reused[0].owns_handler = True
                else:
                    registration.handler.close()


def reset() -> None:
    """Remove handlers installed by :func:`configure` and forget that it ran.

    Logger properties changed by slogger are restored if the application has
    not changed them since. Intended for tests; applications should call
    :func:`configure` instead.
    """
    global _configured, _span_events

    _emission_gate.check_writable()

    with _lock, _emission_gate.write():
        _restore_configuration()
        _configured = False
        _span_events = True


def _attach(target: logging.Logger, handler: logging.Handler, *, owns: bool) -> None:
    context_filter = None
    if not any(isinstance(existing, ContextFilter) for existing in handler.filters):
        context_filter = ContextFilter()
        handler.addFilter(context_filter)
    added_handler = handler not in target.handlers
    if added_handler:
        target.addHandler(handler)
    _installed.append(
        _HandlerRegistration(
            target=target,
            handler=handler,
            owns_handler=owns,
            added_handler=added_handler,
            added_filter=context_filter,
        )
    )


def _remember_logger(logger: logging.Logger) -> _LoggerState:
    for state in _logger_states:
        if state.logger is logger:
            return state
    state = _LoggerState(
        logger=logger,
        original_level=logger.level,
        original_propagate=logger.propagate,
    )
    _logger_states.append(state)
    return state


def _set_level(logger: logging.Logger, level: int) -> None:
    state = _remember_logger(logger)
    logger.setLevel(level)
    state.installed_level = level


def _set_propagate(logger: logging.Logger, propagate: bool) -> None:
    state = _remember_logger(logger)
    logger.propagate = propagate
    state.installed_propagate = propagate


def _restore_configuration(*, close_handlers: bool = True) -> None:
    while _installed:
        registration = _installed.pop()
        if registration.added_handler:
            registration.target.removeHandler(registration.handler)
        if registration.added_filter is not None:
            registration.handler.removeFilter(registration.added_filter)
        if registration.owns_handler and close_handlers:
            registration.handler.close()
    while _logger_states:
        state = _logger_states.pop()
        if state.installed_level is not None and state.logger.level == state.installed_level:
            state.logger.setLevel(state.original_level)
        if (
            state.installed_propagate is not None
            and state.logger.propagate == state.installed_propagate
        ):
            state.logger.propagate = state.original_propagate
