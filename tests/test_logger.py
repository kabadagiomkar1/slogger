import datetime
import decimal
import logging
import pathlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from slogger import builtin_logger, get_logger
from slogger.slogger import builtin_logger as shim_logger
from slogger.slogger import instrument as shim_instrument


def test_public_shim_matches_package():
    assert shim_logger is builtin_logger
    assert shim_instrument is __import__("slogger").instrument


def test_get_logger_is_cached_and_named(records):
    assert get_logger() is builtin_logger
    assert get_logger("app.db") is get_logger("app.db")
    assert get_logger("app.db").name == "app.db"
    assert get_logger("app.db") is not get_logger("app.db").bind(a=1)


def test_concurrent_first_lookup_returns_one_instance(records):
    barrier = threading.Barrier(8)

    def lookup():
        barrier.wait()
        return get_logger("concurrent.new")

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(lambda _: lookup(), range(8)))

    assert all(logger is found[0] for logger in found)


def test_level_is_inherited_from_parent(records):
    get_logger("app").set_level(logging.ERROR)
    child = get_logger("app.db")
    child.info("hidden")
    child.error("visible")
    assert [row["message"] for row in records] == ["visible"]
    assert records[0]["logger"] == "app.db"


def test_bind_precedence_and_immutability(records):
    base = get_logger("bound")
    first = base.bind(a=1, b=1)
    second = first.bind(a=2)
    with first.span("box", b=2, c=3):
        first.info("inside", c=4, d=5)
    row = next(item for item in records if item["message"] == "inside")
    assert row["a"] == 1 and row["b"] == 2 and row["c"] == 4 and row["d"] == 5
    assert row["span"] == "box"

    first.info("first")
    second.info("second")
    base.info("base")
    by_message = {row["message"]: row for row in records}
    assert by_message["first"]["a"] == 1
    assert by_message["second"]["a"] == 2
    assert "a" not in by_message["base"]


def test_unbind_drops_only_named_keys(records):
    logger = get_logger("unbind").bind(a=1, b=2).unbind("a")
    logger.info("left")
    assert records[-1]["b"] == 2
    assert "a" not in records[-1]


def test_reserved_logrecord_keys_become_context(records):
    get_logger("slogger").info(
        "collide",
        name="omkar",
        module="m",
        message="shadow",
        level="X",
        logger="nope",
    )
    row = records[-1]
    assert row["name"] == "omkar"
    assert row["module"] == "m"
    assert row["message"] == "collide"
    assert row["ctx_message"] == "shadow"
    assert row["level"] == "INFO"
    assert row["ctx_level"] == "X"
    assert row["logger"] == "slogger"
    assert row["ctx_logger"] == "nope"
    assert "taskName" not in row


def test_exc_info_stack_info_and_stacklevel(records):
    logger = get_logger("err")

    def _divide_by_zero():
        return 1 / 0

    try:
        _divide_by_zero()
    except ZeroDivisionError:
        logger.error("boom", exc_info=True, k=1)
    assert "ZeroDivisionError" in records[-1]["exception"]
    assert records[-1]["k"] == 1

    try:
        raise ValueError("v")
    except ValueError as exc:
        logger.exception("via exception")
        assert "ValueError: v" in records[-1]["exception"]
        logger.error("instance", exc_info=exc)
        assert "ValueError: v" in records[-1]["exception"]

    logger.info("stack", stack_info=True)
    assert records[-1]["stack"].startswith("Stack (most recent call last)")

    def helper():
        logger.info("from helper", stacklevel=2)

    def caller_of_helper():
        helper()

    caller_of_helper()
    assert records[-1]["func"] == "caller_of_helper"

    logger.info("default stacklevel")
    assert records[-1]["func"] == "test_exc_info_stack_info_and_stacklevel"
    assert records[-1]["file"] == "test_logger.py"


def test_non_json_values_are_serialized(records):
    class Foo:
        def __repr__(self):
            return "Foo()"

    get_logger("ser").info(
        "obj",
        obj=Foo(),
        when=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        dec=decimal.Decimal("1.50"),
        uid=uuid.UUID(int=1),
        path=pathlib.Path("/tmp"),
        items={1, 2},
        err=RuntimeError("x"),
    )
    row = records[-1]
    assert row["obj"] == "Foo()"
    assert row["when"] == "2026-01-01T00:00:00+00:00"
    assert row["dec"] == "1.50"
    assert row["path"] == "/tmp"
    assert sorted(row["items"]) == [1, 2]
    assert row["err"] == "RuntimeError('x')"


def test_disabled_level_emits_nothing(records):
    logger = get_logger("quiet")
    logger.set_level(logging.WARNING)
    logger.debug("skip")
    logger.info("skip too")
    logger.warning("kept")
    assert [row["message"] for row in records] == ["kept"]


def test_stdlib_extra_is_flattened(records):
    third = logging.getLogger("third.extra")
    third.setLevel(logging.DEBUG)
    third.info("stdlib", extra={"custom": 1})
    assert records[-1]["custom"] == 1
    assert records[-1]["logger"] == "third.extra"
    assert "taskName" not in records[-1]


def test_instrument_exported_from_shim():
    assert callable(shim_instrument)
    with pytest.raises(ValueError, match="no parameter"):

        @shim_instrument(capture=["missing"])
        def _fn(present):
            return present
