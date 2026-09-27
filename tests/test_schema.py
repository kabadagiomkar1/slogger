import json

import pytest

from slogger import (
    LogRecord,
    get_logger,
    log_record_json_schema,
    validate_log_record,
)
from slogger.formatters import JSONFormatter, record_to_dict
from slogger.schema import REQUIRED_KEYS, SCHEMA_KEYS, SPAN_KEYS


def test_json_schema_matches_typed_contract():
    schema = log_record_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(schema["required"]) == REQUIRED_KEYS
    assert set(schema["properties"]) == SCHEMA_KEYS | SPAN_KEYS
    assert schema["additionalProperties"] is True


def test_record_to_dict_validates_as_log_record(records):
    get_logger("schema").info("hello", user="ada")
    parsed = validate_log_record(records[-1])
    assert parsed["message"] == "hello"
    assert parsed["user"] == "ada"  # type: ignore[typeddict-item]
    assert isinstance(parsed, dict)


def test_span_end_record_matches_schema(records):
    with get_logger("schema").span("job", n=1):
        pass
    end = next(row for row in records if row.get("event") == "span.end")
    parsed = validate_log_record(end)
    assert parsed["event"] == "span.end"
    assert parsed["status"] == "ok"
    assert isinstance(parsed["duration_ms"], float)
    assert parsed["span"] == "job"
    assert parsed["n"] == 1  # type: ignore[typeddict-item]


def test_validate_log_record_rejects_bad_payloads():
    with pytest.raises(ValueError, match="mapping"):
        validate_log_record("nope")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="missing required"):
        validate_log_record({"message": "x"})
    with pytest.raises(ValueError, match="'line' must be an int"):
        validate_log_record(
            {
                "timestamp": "t",
                "level": "INFO",
                "logger": "x",
                "message": "m",
                "file": "f",
                "func": "g",
                "line": "1",
            }
        )
    with pytest.raises(ValueError, match="event"):
        validate_log_record(
            {
                "timestamp": "t",
                "level": "INFO",
                "logger": "x",
                "message": "m",
                "file": "f",
                "func": "g",
                "line": 1,
                "event": "other",
            }
        )


def test_logrecord_typeddict_is_exported():
    annotations = LogRecord.__annotations__
    assert "timestamp" in annotations
    assert "span_id" in annotations


def test_json_line_round_trips_through_schema(records):
    get_logger("schema").error("boom", code=500)
    again = validate_log_record(json.loads(json.dumps(records[-1])))
    assert again["code"] == 500  # type: ignore[typeddict-item]


def test_record_to_dict_from_stdlib_record_validates():
    import logging

    record = logging.LogRecord("plain", logging.INFO, __file__, 10, "hi", (), None)
    data = record_to_dict(record)
    validate_log_record(data)
    assert data["logger"] == "plain"
    assert JSONFormatter().format(record)
