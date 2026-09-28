from __future__ import annotations

from pathlib import Path

import pytest

from slogger.tools import (
    Filters,
    context,
    diff,
    failures,
    fields,
    meta,
    output_schemas,
    query,
    stats,
    summary,
    trace,
    tree,
    validate,
    validate_tool_output,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASIC = "tests/fixtures/logs/basic.log"
TRACE = "tests/fixtures/logs/trace.log"
ERRORS = "tests/fixtures/logs/errors.log"
INVALID = "tests/fixtures/logs/invalid.log"


@pytest.fixture(autouse=True)
def _chdir_repo(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_output_schemas_document():
    doc = output_schemas()
    assert doc["$schema"].endswith("2020-12/schema")
    assert "meta" in doc["$defs"]
    assert "explain" in doc["$defs"]
    assert "page_meta" in doc["$defs"]


def test_validate_fixture_outputs():
    validate_tool_output("meta", meta(BASIC))
    validate_tool_output("fields", fields(BASIC))
    validate_tool_output("fields_top", fields(BASIC, key="user"))
    validate_tool_output("summary", summary(BASIC, group_by="logger"))
    validate_tool_output("tree", tree(TRACE))
    validate_tool_output("stats", stats(TRACE, spans=True))
    validate_tool_output("errors", failures(ERRORS))
    validate_tool_output("validate", validate(INVALID))
    validate_tool_output("diff", diff(BASIC, ERRORS))
    validate_tool_output("trace", trace(TRACE, trace_id="aaaa").to_dict())
    validate_tool_output("explain", Filters(level_min=40).explain())

    page = query(BASIC, limit=2)
    validate_tool_output(
        "page_meta",
        {
            "schema_version": 1,
            "returned": len(page.records),
            "skipped_lines": page.skipped_lines,
            "next_cursor": page.next_cursor,
            "warnings": page.warnings,
        },
    )
    ctx = context(BASIC, record_id=f"{BASIC}:3", before=1, after=1)
    assert ctx.context_meta is not None
    validate_tool_output(
        "page_meta",
        {
            "schema_version": 1,
            "returned": len(ctx.records),
            "skipped_lines": ctx.skipped_lines,
            "next_cursor": None,
            "warnings": ctx.warnings,
            **ctx.context_meta,
        },
    )


def test_validate_tool_output_rejects_bad_payloads():
    with pytest.raises(ValueError, match="missing required"):
        validate_tool_output("meta", {"schema_version": 1})
    with pytest.raises(ValueError, match="schema_version"):
        validate_tool_output(
            "explain",
            {"schema_version": 2, "filters": {}, "notes": []},
        )
    with pytest.raises(ValueError, match="unknown tool output kind"):
        validate_tool_output("nope", {"schema_version": 1})  # type: ignore[arg-type]
