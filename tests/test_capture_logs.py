import logging

from slogger import capture_logs, get_logger
from slogger.config import configure, is_configured, reset
from slogger.schema import validate_log_record


def test_capture_logs_serializes_values_like_json_output():
    reset()

    class Foo:
        def __repr__(self):
            return "Foo()"

    with capture_logs() as records:
        get_logger("shop").info("obj", obj=Foo())
    assert records[0]["obj"] == "Foo()"  # type: ignore[typeddict-item]


def test_capture_logs_collects_structured_fields():
    reset()
    log = get_logger("shop")
    with capture_logs() as records:
        log.info("charging", order_id="42")

    assert len(records) == 1
    validate_log_record(records[0])
    assert records[0]["message"] == "charging"
    assert records[0]["order_id"] == "42"  # type: ignore[typeddict-item]
    assert records[0]["logger"] == "shop"


def test_capture_logs_includes_span_context():
    reset()
    log = get_logger("shop")
    with capture_logs() as records:
        with log.span("checkout", cart_id="7"):
            log.info("inside")

    inside = next(row for row in records if row["message"] == "inside")
    assert inside["span"] == "checkout"
    assert inside["cart_id"] == "7"  # type: ignore[typeddict-item]
    assert "span_id" in inside


def test_capture_logs_sees_stdlib_records_on_root():
    reset()
    with capture_logs() as records:
        logging.getLogger("third.party").info("from dependency", extra={"n": 1})

    row = next(item for item in records if item["message"] == "from dependency")
    assert row["logger"] == "third.party"
    assert row["n"] == 1  # type: ignore[typeddict-item]


def test_capture_logs_can_target_one_logger_name():
    reset()
    configure(level=logging.DEBUG, console=False)
    with capture_logs(logger="shop.api") as records:
        get_logger("shop.api").info("api")
        get_logger("shop.db").info("db")
        get_logger("other").info("other")

    messages = [row["message"] for row in records]
    assert messages == ["api"]


def test_capture_logs_removes_handler_after_exit():
    reset()
    root = logging.getLogger()
    before = list(root.handlers)
    with capture_logs() as records:
        get_logger("shop").info("during")
        assert len(root.handlers) == len(before) + 1
    assert list(root.handlers) == before
    assert records[0]["message"] == "during"


def test_capture_logs_avoids_lazy_console_default():
    reset()
    assert is_configured() is False
    with capture_logs():
        get_logger("shop").info("quiet")
    assert is_configured() is True
    from slogger.formatters import ConsoleFormatter

    # Silent configure(console=False) — no console formatter left attached.
    assert not any(
        isinstance(getattr(handler, "formatter", None), ConsoleFormatter)
        for handler in logging.getLogger().handlers
    )


def test_capture_logs_respects_level():
    reset()
    with capture_logs(level=logging.WARNING) as records:
        get_logger("shop").info("hidden")
        get_logger("shop").warning("kept")
    assert [row["message"] for row in records] == ["kept"]
