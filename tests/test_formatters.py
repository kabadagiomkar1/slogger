import io
import json
import logging
import re

import pytest

from slogger import get_logger
from slogger.config import configure
from slogger.formators import CONTEXT_ATTR as LEGACY_CONTEXT_ATTR
from slogger.formators import JSONFormatter as LegacyJSONFormatter
from slogger.formatters import CONTEXT_ATTR, ConsoleFormatter, JSONFormatter


class Raw(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_misspelled_formatter_module_remains_compatible():
    assert LegacyJSONFormatter is JSONFormatter
    assert LEGACY_CONTEXT_ATTR == CONTEXT_ATTR


@pytest.fixture
def raw_record():
    raw = Raw()
    configure(level=logging.DEBUG, console=False, handlers=[raw])
    get_logger("demo").info("hello", user="ada lovelace", n=2)
    return raw.records[-1]


def test_json_timestamp_is_utc_iso8601(raw_record):
    payload = json.loads(JSONFormatter().format(raw_record))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", payload["timestamp"])
    assert payload["logger"] == "demo"
    assert payload["user"] == "ada lovelace"
    assert "taskName" not in payload


def test_datefmt_overrides_timestamp(raw_record):
    formatter = JSONFormatter(datefmt="%Y")
    payload = json.loads(formatter.format(raw_record))
    assert re.fullmatch(r"\d{4}", payload["timestamp"])


def test_formatter_tolerates_a_record_without_slogger_context():
    record = logging.LogRecord("plain", logging.INFO, __file__, 1, "hi", (), None)
    payload = json.loads(JSONFormatter().format(record))
    assert payload["message"] == "hi"
    assert payload["logger"] == "plain"
    assert "taskName" not in payload


def test_optional_schema_keys_are_reserved_even_when_not_populated():
    raw = Raw()
    configure(level=logging.DEBUG, console=False, handlers=[raw])
    get_logger("demo").info("plain", exception="user value", stack="user stack")
    payload = json.loads(JSONFormatter().format(raw.records[-1]))
    assert "exception" not in payload
    assert "stack" not in payload
    assert payload["ctx_exception"] == "user value"
    assert payload["ctx_stack"] == "user stack"


def test_escaped_schema_keys_cannot_overwrite_each_other():
    raw = Raw()
    configure(level=logging.DEBUG, console=False, handlers=[raw])
    get_logger("demo").info("plain", message="reserved", ctx_message="explicit")
    payload = json.loads(JSONFormatter().format(raw.records[-1]))
    assert payload["message"] == "plain"
    assert payload["ctx_message"] == "reserved"
    assert payload["ctx_ctx_message"] == "explicit"


def test_console_line_without_color(raw_record):
    text = ConsoleFormatter(color=False).format(raw_record)
    assert text.startswith(json.loads(JSONFormatter().format(raw_record))["timestamp"])
    assert "INFO     demo  hello" in text
    assert "n=2" in text
    assert "user='ada lovelace'" in text
    assert "\033" not in text


def test_console_dims_span_fields_when_color_is_forced():
    raw = Raw()
    configure(level=logging.DEBUG, console=False, handlers=[raw])
    with get_logger("demo").span("box"):
        get_logger("demo").info("hello", user="ada")
    record = next(item for item in raw.records if item.getMessage() == "hello")
    text = ConsoleFormatter(color=True).format(record)
    assert "user=ada" in text
    assert "span=box" in text
    assert "\033[2m" in text
    plain = ConsoleFormatter(color=False).format(record)
    assert "\033" not in plain
    assert "span=box" in plain


def test_color_auto_respects_tty_and_env(raw_record, monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert "\033" in ConsoleFormatter(color=None, stream=TTY()).format(raw_record)
    assert "\033" not in ConsoleFormatter(color=None, stream=io.StringIO()).format(raw_record)

    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033" not in ConsoleFormatter(color=None, stream=TTY()).format(raw_record)

    monkeypatch.setenv("FORCE_COLOR", "1")
    assert "\033" in ConsoleFormatter(color=None, stream=io.StringIO()).format(raw_record)

    assert "\033" not in ConsoleFormatter(color=False, stream=TTY()).format(raw_record)


def test_console_appends_traceback():
    raw = Raw()
    configure(level=logging.DEBUG, console=False, handlers=[raw])
    try:
        raise RuntimeError("nope")
    except RuntimeError:
        get_logger("demo").exception("failed")
    text = ConsoleFormatter(color=False).format(raw.records[-1])
    assert "failed" in text
    assert "RuntimeError: nope" in text
    assert "\033" not in text


@pytest.mark.parametrize("formatter", [JSONFormatter(), ConsoleFormatter(color=False)])
def test_payload_serialization_survives_cycles_and_broken_repr(formatter):
    class Broken:
        def __repr__(self):
            raise RuntimeError("repr broke")

    cycle = []
    cycle.append(cycle)
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "kept", (), None)
    setattr(record, CONTEXT_ATTR, {"cycle": cycle, "broken": Broken(), "ok": 42})
    rendered = formatter.format(record)
    assert "kept" in rendered
    if isinstance(formatter, JSONFormatter):
        payload = json.loads(rendered)
        assert payload["ok"] == 42
        assert isinstance(payload["cycle"], str)
        assert isinstance(payload["broken"], str)
    else:
        assert "ok=42" in rendered


def test_payload_serialization_survives_unsupported_mapping_keys():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "kept", (), None)
    setattr(record, CONTEXT_ATTR, {"mapping": {(1, 2): "value"}, "ok": [1, 2]})
    payload = json.loads(JSONFormatter().format(record))
    assert payload["ok"] == [1, 2]
    assert isinstance(payload["mapping"], str)
