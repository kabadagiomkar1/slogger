"""Regressions for the outstanding September 2026 repository review findings."""

from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest

from slogger import capture_logs, get_logger, instrument
from slogger.tools import (
    Filters,
    context,
    failures,
    fields,
    stats,
    trace,
    tree,
    validate_tool_output,
)
from slogger.tools.mcp import call_tool, handle_request, list_tools, serve
from slogger.tools.reader import replay_sources
from slogger.tools.spans import SpanCollector
from slogger.tools.trace import build_trace


def event(sid, name, kind, *, time="2026-09-28T00:00:00Z", **extra):
    return {
        "trace_id": "aaaa", "span_id": sid, "span": name, "event": kind,
        "timestamp": time, "status": "ok", "duration_ms": 10,
        **extra,
    }


def test_reentrant_logging_and_callback_configuration_do_not_deadlock():
    script = textwrap.dedent('''
        import logging
        import threading
        from slogger import configure, get_logger
        from slogger.config import _EmissionGate, reset

        class Callback(logging.Handler):
            def emit(self, record):
                for change in (configure, reset):
                    try:
                        change()
                    except RuntimeError as error:
                        assert "during emission" in str(error)
                    else:
                        raise AssertionError("configuration must be rejected")
        configure(console=False, handlers=[Callback()])
        get_logger().info("callback")
        reset()
        gate = _EmissionGate()
        entered = threading.Event()
        def writer():
            with gate.write():
                entered.set()
        with gate.read():
            worker = threading.Thread(target=writer, daemon=True)
            worker.start()
            with gate._condition:
                assert gate._condition.wait_for(lambda: gate._waiting_writers == 1, timeout=1)
            with gate.read():
                assert not entered.is_set()
        worker.join(timeout=1)
        assert entered.is_set()
    ''')
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", script],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("error", [False, True])
def test_span_logging_control_fields_are_preserved(error):
    log = get_logger("review.controls")
    with capture_logs() as records:
        if error:
            with pytest.raises(RuntimeError, match="original"):
                with log.span("child", stacklevel="field", exc_info="field", stack_info="field"):
                    raise RuntimeError("original")
        else:
            with log.span("child", stacklevel="field", exc_info="field", stack_info="field"):
                pass
    end = dict(records[-1])
    assert end["status"] == ("error" if error else "ok")
    assert end["stacklevel"] == end["exc_info"] == end["stack_info"] == "field"
    assert ("exception" in end) == error
    assert "stack" not in end
    assert end["func"] == "test_span_logging_control_fields_are_preserved"


def test_instrument_can_capture_logging_control_parameter():
    @instrument(capture="stacklevel")
    def work(stacklevel):
        return stacklevel

    with capture_logs() as records:
        assert work("value") == "value"
    assert dict(records[-1])["stacklevel"] == "value"
    assert records[-1]["func"] == "test_instrument_can_capture_logging_control_parameter"


def test_span_filters_and_anchor_windows():
    rows = [
        event("a", "old", "span.start", time="2026-09-01T00:00:00Z"),
        event("a", "old", "span.end", status="error"),
        event("b", "new", "span.start"),
        event("b", "new", "span.end"),
    ]
    assert stats(rows, spans=True, filters=Filters(span="new"))["totals"]["spans"] == 1
    since = datetime(2026, 9, 27, tzinfo=timezone.utc)
    assert stats(rows, spans=True, filters=Filters(since=since))["totals"]["spans"] == 1
    assert failures(rows, filters=Filters(span="new"))["failed_spans"] == 0
    assert tree(rows, filters=Filters(span="absent"))["traces"] == []


@pytest.mark.parametrize("order", ["concat", "time"])
def test_stdin_trace_and_context_preserve_ids(monkeypatch, order):
    rows = [event("a", "work", "span.start")]
    rows.extend({"trace_id": "aaaa", "span_id": "a", "message": str(i)} for i in range(4))
    rows.append(event("a", "work", "span.end"))
    source = "".join(json.dumps(row) + "\n" for row in rows)
    monkeypatch.setattr(sys, "stdin", io.StringIO(source))
    result = trace("-", trace_id="aaaa", order=order)
    assert len(result.spans) == 1
    assert [log["_id"] for log in result.spans[0].logs] == ["-:2", "-:3", "-:4", "-:5"]
    monkeypatch.setattr(sys, "stdin", io.StringIO(source))
    page = context("-", record_id="-:3", before=0, after=0, order=order)
    assert [row["_id"] for row in page.records] == [f"-:{i}" for i in range(1, 7)]
    assert [row["_id"] for row in page.records if row.get("_anchor")] == ["-:3"]


def test_stdin_spool_is_removed_on_error(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{}\n'))
    with pytest.raises(RuntimeError):
        with replay_sources("-") as resolved:
            spool = Path(str(resolved[0]))
            assert spool.is_file()
            raise RuntimeError("aborted")
    assert not spool.exists()


@pytest.mark.parametrize("parents", [["a"], ["b", "a"], ["b", "c", "a"]])
def test_parent_cycles_do_not_lose_spans(parents):
    rows = [event(chr(97+i), "work", "span.start", parent_span_id=parent)
            for i, parent in enumerate(parents)]
    result = build_trace(rows, "aaaa")
    assert len(result.spans) == 1
    assert result.spans[0].orphan
    assert result.warnings == ["parent_cycle:a"]
    assert len(json.dumps(result.to_dict())) > 0
    assert tree(rows)["traces"][0]["spans"] == len(parents)


def test_trace_sorts_offsets_and_fractional_precision():
    rows = [
        {"timestamp": "2026-09-28T01:00:00+01:00", "message": "first"},
        {"timestamp": "2026-09-28T00:00:00.000500Z", "message": "second"},
    ]
    assert [r["message"] for r in build_trace(rows, None).logs] == ["first", "second"]


def test_collector_retains_selection_without_retaining_logs():
    collector = SpanCollector(keep_logs=False, predicate=Filters(grep="selected").matches)
    collector.add(event("a", "work", "span.start"), "aaaa")
    for i in range(20_000):
        collector.add({"span_id": "a", "message": "selected" if i == 4 else "other"}, "aaaa")
    collector.add(event("a", "work", "span.end"), "aaaa")
    assert len(collector._buffers["aaaa"]) == 2
    result = list(collector.finish())
    assert result[0][1].spans[0].status == "ok"
    assert result[0][1].spans[0].logs == []


def test_collector_caps_group_tracking():
    collector = SpanCollector(keep_logs=False, max_groups=2)
    for i in range(20_000):
        collector.add(event(str(i), "work", "span.start"), str(i))
    assert len(collector._buffers) == len(collector._seen_spans) == 2
    assert len(collector._selected) == 2
    assert collector.groups_seen == 3
    assert collector.groups_capped


def test_grouped_span_uses_start_value_and_trace_identity():
    rows = [
        event("a", "work", "span.start", user="old"),
        event("a", "work", "span.end", user="new"),
        event("a", "work", "span.end", trace_id="bbbb", user="other"),
    ]
    result = stats(rows, spans=True, group_by="user")
    assert result["totals"]["spans"] == 2
    groups = {row["value"]: row for row in result["groups"]}
    assert set(groups) == {"old", "other"}
    assert groups["old"]["completed"] == 1
    assert groups["other"]["missing_start"] == 1


def test_field_identity_preserves_json_types():
    rows = [{"v": value} for value in (True, 1, 1.0, "[]", [])]
    overview = fields(rows)
    assert overview["keys"]["v"]["distinct"] == 5
    ranked = fields(rows, key="v")
    assert len(ranked["top"]) == 5
    assert all(row["count"] == 1 for row in ranked["top"])


def test_fields_does_not_cache_a_file_changed_during_scan(tmp_path, monkeypatch):
    mod = importlib.import_module("slogger.tools.fields")
    original = mod._scan_fields
    path = tmp_path / "live.log"
    path.write_text('{"message":"before"}\n')

    def append_after_scan(*args, **kwargs):
        result = original(*args, **kwargs)
        with path.open("a") as handle:
            handle.write('{"message":"after"}\n')
        return result

    monkeypatch.setattr(mod, "_scan_fields", append_after_scan)
    assert fields(str(path), cache=True)["scanned"] == 1
    assert not Path(str(path) + ".slogger-fields.json").exists()
    monkeypatch.setattr(mod, "_scan_fields", original)
    assert fields(str(path), cache=True)["scanned"] == 2
    assert list(tmp_path.glob("*.tmp")) == []


def test_mcp_unicode_and_invalid_messages_do_not_break_stream():
    requests = [[], 1, {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []},
                {"jsonrpc": "2.0", "method": "ping"},
                {"jsonrpc": "2.0", "id": "नमस्ते", "method": "ping"}]
    stdin = io.StringIO('invalid\n' + ''.join(json.dumps(r, ensure_ascii=False)+'\n'
                                            for r in requests))
    stdout = io.StringIO()
    assert serve(stdin, stdout) == 0
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [r["error"]["code"] for r in replies[:-1]] == [-32700, -32600, -32600, -32602]
    assert replies[-1] == {"jsonrpc": "2.0", "id": "नमस्ते", "result": {}}


def test_mcp_descriptors_and_stdin_rejection():
    schemas = {tool["name"]: tool["inputSchema"] for tool in list_tools()}
    assert schemas["watch"]["required"] == ["path"]
    assert schemas["diff"]["required"] == ["before", "after"]
    assert "record_id" in schemas["context"]["required"]
    for name, arguments in [("query", {"sources": "-"}), ("watch", {"path": "-"}),
                            ("diff", {"before": ["-"], "after": "file"})]:
        with pytest.raises(ValueError, match="stdin"):
            call_tool(name, arguments)
    with pytest.raises(ValueError, match="missing required"):
        call_tool("watch", {})
    with pytest.raises(ValueError):
        call_tool("watch", {"path": "file", "timeout": True})
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "watch", "arguments": {"path": "-"}}})
    assert response is not None and response["result"]["isError"]


@pytest.mark.parametrize("kind, payload", [
    ("explain", {"schema_version": True, "filters": {}, "notes": []}),
    ("explain", {"schema_version": 1, "filters": {}, "notes": []}),
    ("page_meta", {"schema_version": 1, "returned": 1, "skipped_lines": 0,
                   "next_cursor": None, "warnings": [42]}),
])
def test_output_contract_rejects_invalid_nested_values(kind, payload):
    with pytest.raises(ValueError):
        validate_tool_output(kind, payload)


def test_tree_orders_by_timestamp_instant():
    rows = [
        event("a", "later", "span.start", time="2026-09-28T00:30:00Z"),
        event("b", "earlier", "span.start", trace_id="bbbb",
              time="2026-09-28T01:00:00+01:00"),
    ]
    assert [row["root_span"] for row in tree(rows)["traces"]] == ["earlier", "later"]


def test_concurrent_cache_writes_publish_complete_document(tmp_path, monkeypatch):
    mod = importlib.import_module("slogger.tools.fields")
    original_replace = Path.replace
    barrier = Barrier(2)
    temporary_names = []
    cache = tmp_path / "cache.json"

    def replace_together(path, target):
        temporary_names.append(path.name)
        barrier.wait(timeout=5)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_together)

    def write(value):
        mod._write_cache(cache, file_path="log", size=1, mtime_ns=1, scan=10,
                         payload={"value": value})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, [1, 2]))
    assert len(set(temporary_names)) == 2
    assert json.loads(cache.read_text())["payload"]["value"] in (1, 2)
    assert list(tmp_path.glob("*.tmp")) == []
