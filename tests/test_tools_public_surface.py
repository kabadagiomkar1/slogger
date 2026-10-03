"""The query library has one public tooling route."""

import slogger.tools as tools


def test_public_query_surface_withdraws_legacy_tools():
    retired = {
        "Filters",
        "Where",
        "query",
        "summary",
        "Page",
        "Reader",
        "CursorError",
        "trace",
        "tree",
        "context",
        "stats",
        "failures",
        "diff",
        "fields",
        "meta",
        "validate",
        "watch",
        "follow",
        "tail_once",
        "output_schemas",
    }
    assert retired.isdisjoint(tools.__all__)
    assert all(not hasattr(tools, name) for name in retired)
    result = tools.scan([{"level": "ERROR"}]).filter(tools.Field("level").eq("ERROR")).execute()
    assert [record["level"] for record in result.records] == ["ERROR"]
