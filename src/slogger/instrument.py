"""Open a span for the duration of a function call."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterable


def instrument(
    name: str | None = None,
    capture: Iterable[str] | str = (),
    *,
    logger=None,
    events: bool | None = None,
    **context: object,
):
    """Decorator that opens a span around a sync or async function.

    ``capture`` names parameters to copy into the span (a single string is
    accepted). Unknown names raise :class:`ValueError` at decoration time.
    ``context`` is added to every call. ``logger`` defaults to
    :func:`slogger.get_logger` ``("slogger")`` and is resolved when the function
    runs. ``events`` is forwarded to :meth:`~slogger.logger.SLogger.span`.

    Span start/end events for a sync function are attributed to its caller.
    Async events stay on this wrapper: the event loop, not the original caller,
    is what resumes the coroutine.
    """
    if isinstance(capture, str):
        capture_names = (capture,)
    else:
        capture_names = tuple(capture)

    def decorator(func: Callable):
        is_async_fn = inspect.iscoroutinefunction(func)
        signature = inspect.signature(func)

        unknown = [param for param in capture_names if param not in signature.parameters]
        if unknown:
            raise ValueError(
                f"instrument(): {func.__qualname__}() has no parameter(s) {unknown}; "
                f"available: {list(signature.parameters)}"
            )

        def span_context(args, kwargs) -> dict:
            bound_args = signature.bind(*args, **kwargs)
            bound_args.apply_defaults()
            selected = {
                key: value
                for key, value in bound_args.arguments.items()
                if key in capture_names
            }
            return {**selected, **context}

        def active_logger():
            if logger is not None:
                return logger
            from slogger.logger import get_logger

            return get_logger()

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with active_logger().span(
                name or func.__name__,
                events=events,
                event_stacklevel=2,
                **span_context(args, kwargs),
            ):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # One frame above this wrapper is whoever resumed the coroutine
            # (often the event loop), not the code that first called it.
            # Stay on this wrapper so the event is not attributed to asyncio.
            async with active_logger().span(
                name or func.__name__,
                events=events,
                event_stacklevel=1,
                **span_context(args, kwargs),
            ):
                return await func(*args, **kwargs)

        return async_wrapper if is_async_fn else sync_wrapper

    return decorator
