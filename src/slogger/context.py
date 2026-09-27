"""Carry the active span into worker threads."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def wrap_context(fn: Callable[P, R]) -> Callable[P, R]:
    """Return ``fn`` bound to a copy of the current :mod:`contextvars` context.

    ``ThreadPoolExecutor`` and ``loop.run_in_executor`` do not copy context
    the way :func:`asyncio.create_task` does. Submit the wrapped callable so
    the worker sees the same span the caller was inside::

        pool.submit(wrap_context(work), arg)
    """
    captured = contextvars.copy_context()

    @functools.wraps(fn)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        # Context.run cannot enter one Context concurrently. Each invocation
        # gets a copy so a wrapped callable is reusable across worker threads.
        return captured.copy().run(fn, *args, **kwargs)

    return wrapped


def run_in_executor(
    loop: asyncio.AbstractEventLoop,
    executor: concurrent.futures.Executor | None,
    fn: Callable[..., R],
    *args: Any,
) -> Awaitable[R]:
    """``loop.run_in_executor`` that keeps the caller's span context."""
    return loop.run_in_executor(executor, wrap_context(fn), *args)
