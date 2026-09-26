from contextvars import ContextVar
import functools
import inspect
import logging
import sys

from slogger.formators import CONTEXT_ATTR
from slogger.handlers import *

__all__ = ["builtin_logger", "instrument", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"]


DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL

# Key under which the active span's name is recorded in the log context.
SPAN_KEY = "span"


class _SLogger():
    SPAN_CONTEXT = ContextVar("SPAN_CONTEXT", default=None)

    def __init__(
        self,
        logger_name: str,
        level=logging.DEBUG
    ):
        self._logger = logging.getLogger(logger_name)

        self._logger.setLevel(level)

    def __log(self, level, msg, /, *args, **kwargs):
        if not self._logger.isEnabledFor(level):
            return

        # Standard logging keyword arguments are honoured rather than being
        # treated as context fields.
        exc_info = kwargs.pop("exc_info", None)
        stack_info = kwargs.pop("stack_info", False)
        stacklevel = kwargs.pop("stacklevel", 1)

        if exc_info:
            if isinstance(exc_info, BaseException):
                exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
            elif not isinstance(exc_info, tuple):
                exc_info = sys.exc_info()

        current_span = self.SPAN_CONTEXT.get()
        context = {**current_span.context, **kwargs} if current_span else kwargs

        # +2 skips this method and the public level method (info/error/...)
        # so that ``stacklevel=1`` points at the user's call site.
        fn, lno, func, sinfo = self._logger.findCaller(stack_info=stack_info, stacklevel=stacklevel + 2)
        record = self._logger.makeRecord(
            self._logger.name, level, fn, lno, msg, args, exc_info, func,
            extra={CONTEXT_ATTR: context}, sinfo=sinfo,
        )
        self._logger.handle(record)

    def span(self, name, **context):
        parent_span = self.SPAN_CONTEXT.get()
        if parent_span:
            context = {**parent_span.context, **context}

        context[SPAN_KEY] = name
        span = _Span(self, name, **context)

        return span

    def debug(self, msg, /, *args, **kwargs):
        self.__log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, /, *args, **kwargs):
        self.__log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, /, *args, **kwargs):
        self.__log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, /, *args, **kwargs):
        self.__log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg, /, *args, **kwargs):
        kwargs.setdefault("exc_info", True)
        self.__log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, /, *args, **kwargs):
        self.__log(logging.CRITICAL, msg, *args, **kwargs)

    def fatal(self, msg, /, *args, **kwargs):
        self.__log(logging.FATAL, msg, *args, **kwargs)

    def add_handler(self, handler):
        self._logger.addHandler(handler)


class _Span():
    def __init__(self, logger: _SLogger, name: str, **context):
        self._logger = logger
        self._name = name
        self._token = None
        self._context = context
        self._closed = False

    def __enter__(self):
        self._token = _SLogger.SPAN_CONTEXT.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True

        # Never entered: nothing to restore.
        if self._token is None:
            return

        try:
            _SLogger.SPAN_CONTEXT.reset(self._token)
        except ValueError:
            # The span is being closed from a different context than the one
            # it was entered in (e.g. it outlived its task). There is nothing
            # meaningful to restore there.
            pass

    @property
    def name(self):
        return self._name

    @property
    def context(self):
        return self._context


builtin_logger = _SLogger("builtin_logger")
builtin_logger.add_handler(get_console_handler(logging.INFO))
builtin_logger.add_handler(get_structured_file_handler("app.log", logging.DEBUG))


def instrument(name=None, capture=(), **context):
    if isinstance(capture, str):
        capture = (capture,)
    capture = tuple(capture)

    def decorator(func):
        is_async_fn = inspect.iscoroutinefunction(func)
        sig = inspect.signature(func)

        unknown = [param for param in capture if param not in sig.parameters]
        if unknown:
            raise ValueError(
                f"instrument(): {func.__qualname__}() has no parameter(s) {unknown}; "
                f"available: {list(sig.parameters)}"
            )

        def _span_context(args, kwargs):
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            selected_args = {k: v for k, v in bound_args.arguments.items() if k in capture}
            return {**selected_args, **context}

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with builtin_logger.span(name or func.__name__, **_span_context(args, kwargs)):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            async with builtin_logger.span(name or func.__name__, **_span_context(args, kwargs)):
                return await func(*args, **kwargs)

        return async_wrapper if is_async_fn else sync_wrapper

    return decorator
