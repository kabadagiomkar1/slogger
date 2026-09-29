from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from slogger.tools.mcp import call_tool, handle_request, list_tools, serve

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_list_tools_includes_core():
    names = {tool["name"] for tool in list_tools()}
    assert {"meta", "query", "explain", "fields", "trace"}.issubset(names)


def test_call_tool_meta_and_explain():
    payload = call_tool("meta", {"sources": BASIC})
    assert payload["schema_version"] == 1
    assert payload["records"] == 6

    explained = call_tool(
        "explain",
        {
            "filters": {
                "level_min": 40,
                "where": [],
                "has": [],
                "missing": [],
                "exclude_events": False,
            }
        },
    )
    assert explained["filters"]["level_min"] == 40


def test_handle_initialize_and_tools_call():
    init = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    )
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "slogger.tools"

    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    assert any(t["name"] == "query" for t in listed["result"]["tools"])

    called = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "query",
                "arguments": {
                    "sources": BASIC,
                    "filters": {"level_min": 40},
                    "limit": 10,
                },
            },
        }
    )
    assert called is not None
    structured = called["result"]["structuredContent"]
    assert len(structured["records"]) == 1
    assert structured["records"][0]["level"] == "ERROR"


def test_serve_newline_protocol():
    requests = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "meta", "arguments": {"sources": BASIC}},
            }
        ),
    ]
    stdin = io.StringIO("\n".join(requests) + "\n")
    stdout = io.StringIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    body = stdout.getvalue()
    replies = [json.loads(line) for line in body.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[1]["result"]["structuredContent"]["records"] == 6
    assert "slogger.tools" in body
    assert '"records": 6' in body or '"records":6' in body
