import asyncio
import logging

import pytest

from slogger import get_logger, instrument
from slogger.config import configure
from slogger.span import SPAN_CONTEXT
from tests.support import Capture


def _events(records, name):
    return [row for row in records if row.get("event") and row.get("span") == name]


def test_span_emits_start_and_end_with_ids(records):
    logger = get_logger("trace")
    with logger.span("outer", req=1) as outer:
        with logger.span("inner") as inner:
            logger.info("nested")
            assert inner.parent_span_id == outer.span_id
            assert inner.trace_id == outer.trace_id
            assert inner.span_id != outer.span_id
        logger.info("back")

    nested = next(row for row in records if row["message"] == "nested")
    assert nested["span"] == "inner"
    assert nested["span_id"] == inner.span_id
    assert nested["parent_span_id"] == outer.span_id
    assert nested["trace_id"] == outer.trace_id
    assert nested["req"] == 1

    back = next(row for row in records if row["message"] == "back")
    assert back["span"] == "outer"
    assert "parent_span_id" not in back

    inner_events = _events(records, "inner")
    outer_events = _events(records, "outer")
    assert [row["event"] for row in inner_events] == ["span.start", "span.end"]
    assert [row["event"] for row in outer_events] == ["span.start", "span.end"]
    assert inner_events[-1]["status"] == "ok"
    assert inner_events[-1]["duration_ms"] >= 0
    assert inner_events[-1]["func"] == "test_span_emits_start_and_end_with_ids"
    assert outer_events[0]["level"] == "DEBUG"
    assert SPAN_CONTEXT.get() is None


def test_span_error_sets_status_and_reraises(records):
    logger = get_logger("trace")
    with pytest.raises(RuntimeError, match="boom"):
        with logger.span("job"):
            raise RuntimeError("boom")

    end = _events(records, "job")[-1]
    assert end["event"] == "span.end"
    assert end["status"] == "error"
    assert end["level"] == "ERROR"
    assert end["error_type"] == "RuntimeError"
    assert end["error"] == "boom"
    assert "RuntimeError: boom" in end["exception"]
    assert SPAN_CONTEXT.get() is None


def test_events_can_be_disabled_per_span_or_globally(records):
    logger = get_logger("trace")
    with logger.span("quiet", events=False):
        logger.info("inside")
    assert records[-1]["message"] == "inside"
    assert records[-1]["span"] == "quiet"
    assert _events(records, "quiet") == []

    found: list = []
    configure(
        level=logging.DEBUG,
        console=False,
        handlers=[Capture(found)],
        span_events=False,
    )
    with logger.span("off"):
        logger.info("no-events")
    with logger.span("forced", events=True):
        logger.info("yes-events")
    assert _events(found, "off") == []
    assert [row["event"] for row in _events(found, "forced")] == ["span.start", "span.end"]


def test_span_set_is_visible_on_later_records_and_end(records):
    logger = get_logger("trace")
    with logger.span("box") as span:
        span.set(user="ada")
        logger.info("after")
    after = next(row for row in records if row["message"] == "after")
    end = _events(records, "box")[-1]
    assert after["user"] == "ada"
    assert end["user"] == "ada"


def test_manual_start_and_end(records):
    logger = get_logger("trace")
    early = logger.span("early")
    early.end()
    early.start()
    logger.info("after early close")
    early.end()
    assert [row["event"] for row in _events(records, "early")] == ["span.start", "span.end"]
    assert records[-2]["span"] == "early"

    span = logger.span("manual", k=1)
    span.start()
    logger.info("inside")
    span.end()
    span.end()
    assert next(row for row in records if row["message"] == "inside")["k"] == 1
    assert [row["event"] for row in _events(records, "manual")] == ["span.start", "span.end"]
    assert _events(records, "manual")[0]["func"] == "test_manual_start_and_end"
    assert SPAN_CONTEXT.get() is None


def test_end_from_another_context_does_not_raise(records):
    logger = get_logger("trace")

    async def scenario():
        span = logger.span("crossed")

        async def enter():
            span.start()

        await asyncio.create_task(enter())
        span.end()

    asyncio.run(scenario())
    assert SPAN_CONTEXT.get() is None


def test_child_task_cannot_close_a_span_owned_by_its_parent(records):
    logger = get_logger("trace")

    async def scenario():
        with logger.span("parent-owned") as span:

            async def child():
                span.end()

            await asyncio.create_task(child())
            assert SPAN_CONTEXT.get() is span
            logger.info("still active")

    asyncio.run(scenario())
    assert SPAN_CONTEXT.get() is None
    assert [row["event"] for row in _events(records, "parent-owned")] == [
        "span.start",
        "span.end",
    ]
    active = next(row for row in records if row["message"] == "still active")
    assert active["span"] == "parent-owned"


def test_failed_start_event_rolls_back_the_context():
    class RaisingHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError("handler failed")

    configure(level=logging.DEBUG, console=False, handlers=[RaisingHandler()])
    span = get_logger("trace").span("broken")

    with pytest.raises(RuntimeError, match="handler failed"):
        span.start()

    assert SPAN_CONTEXT.get() is None
    assert span.context == {}


def test_context_propagates_into_tasks(records):
    logger = get_logger("trace")

    async def child():
        logger.info("child")

    async def main():
        with logger.span("task_outer", req="9"):
            await asyncio.create_task(child())

    asyncio.run(main())
    child_row = next(row for row in records if row["message"] == "child")
    assert child_row["req"] == "9"
    assert child_row["span"] == "task_outer"


def test_instrument_capture_validation_and_async(records):
    with pytest.raises(ValueError, match=r"\['a', 'b'\]"):

        @instrument(capture=["a", "b"])
        def _bad(numerator, denominator):
            return numerator / denominator

    @instrument(capture="x", tag="t")
    def sync_fn(x, y=2):
        get_logger().info("in sync")
        return x + y

    assert sync_fn(1) == 3
    row = next(item for item in records if item["message"] == "in sync")
    assert row["span"] == "sync_fn"
    assert row["x"] == 1 and row["tag"] == "t"
    assert "y" not in row
    end = _events(records, "sync_fn")[-1]
    assert end["func"] == "test_instrument_capture_validation_and_async"
    assert end["x"] == 1

    @instrument(name="ag", capture=["x"])
    async def async_fn(x):
        get_logger().info("in async")
        return x

    assert asyncio.run(async_fn(5)) == 5
    async_row = next(item for item in records if item["message"] == "in async")
    assert async_row["span"] == "ag" and async_row["x"] == 5
    assert [row["event"] for row in _events(records, "ag")] == ["span.start", "span.end"]
    # The coroutine is resumed by the event loop, so the event stays on the wrapper
    # instead of being attributed to asyncio.
    assert _events(records, "ag")[-1]["func"] == "async_wrapper"
    assert _events(records, "ag")[-1]["file"] == "instrument.py"


def test_instrument_uses_the_given_logger(records):
    logger = get_logger("mod").bind(service="api")

    @instrument(logger=logger, capture=["n"])
    def work(n):
        logger.info("ran")
        return n

    assert work(3) == 3
    row = next(item for item in records if item["message"] == "ran")
    assert row["logger"] == "mod"
    assert row["service"] == "api"
    assert row["n"] == 3


def test_stdlib_records_receive_the_active_span(records):
    third = logging.getLogger("third.party")
    third.setLevel(logging.DEBUG)
    with get_logger("trace").span("req", id=1):
        third.info("from third party")
    row = next(item for item in records if item["message"] == "from third party")
    assert row["logger"] == "third.party"
    assert row["span"] == "req"
    assert row["id"] == 1
    assert "span_id" in row
