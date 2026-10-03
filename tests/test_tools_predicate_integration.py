"""Rich filters retain existing tool selection and reconstruction behavior."""

import json
from pathlib import Path

from slogger.tools import (
    Field,
    Filters,
    context,
    diff,
    failures,
    fields,
    follow,
    meta,
    query,
    stats,
    summary,
    tail_once,
    trace,
    tree,
    watch,
)

FIXTURES = Path(__file__).parent / "fixtures" / "logs"


def test_jsonl_selection_and_field_cache(tmp_path):
    path = tmp_path / "app.log"
    path.write_text((FIXTURES / "basic.log").read_text())
    baseline = fields(path, cache=True)
    cache = Path(str(path) + ".slogger-fields.json")
    original = cache.read_bytes()
    filters = Filters(predicate=Field("level").in_(["ERROR"]))
    assert fields(path, filters=filters, cache=True)["scanned"] == 1
    assert cache.read_bytes() == original
    assert fields(path, cache=True) == baseline
    assert len(query(path, filters=filters).records) == 1
    assert len(tail_once(path, filters=filters).records) == 1
    assert len(list(follow(str(path), filters=filters, stop=lambda: True))) == 1
    watched = watch(str(path), filters=filters, existing=True)
    assert watched.matched is not None and watched.matched["level"] == "ERROR"
    assert not watched.timed_out
    # Aggregate paths must consume the same predicate as query().
    assert meta(path, filters=filters) == meta(path, filters=Filters(level_exact=40))
    assert summary(path, filters=filters) == summary(path, filters=Filters(level_exact=40))
    assert stats(path, filters=filters) == stats(path, filters=Filters(level_exact=40))
    assert failures(path, filters=filters) == failures(path, filters=Filters(level_exact=40))
    assert diff(path, path, filters=filters) == diff(path, path, filters=Filters(level_exact=40))


def test_trace_and_span_reconstruction():
    source = FIXTURES / "trace.log"
    # Only one ordinary log matches, but its full trace must be reconstructed.
    filters = Filters(predicate=Field("message").eq("charging"))
    selected = trace(source, filters=filters)
    assert selected.trace_id == "a" * 32
    assert selected.matched_records == 1
    root = selected.spans[0]
    assert root.duration_ms == 410.0
    assert root.children[0].duration_ms == 380.0
    result = tree(source, filters=filters)
    assert result["total"] == 1
    assert result["traces"][0]["completed"] == 2
    assert result["traces"][0]["duration_ms"] == 410.0
    # Both paths use dataclasses.replace(span=None); predicate must survive.
    assert tree(source, filters=Filters(span="charge", predicate=filters.predicate))["total"] == 1
    rich = stats(source, spans=True, filters=filters)
    legacy = stats(source, spans=True, filters=Filters(grep="^charging$"))
    assert rich == legacy


def test_context_preserves_anchor_and_trace():
    source = str(FIXTURES / "trace.log")
    filters = Filters(predicate=Field("message").eq("charging"))
    result = context(
        source, record_id=f"{source}:2", before=0, after=1, same_trace=False, filters=filters
    )
    assert result.records[0]["_anchor"]
    assert result.records[-1]["message"] == "charging"
    full = context(
        source, record_id=f"{source}:2", before=0, after=0, same_trace=True, filters=filters
    )
    assert len(full.records) == 7


def test_file_query_stops_reading_at_limit(tmp_path):
    source = tmp_path / "stream.log"
    source.write_text(json.dumps({"n": 1}) + "\nmalformed trailing line\n")
    page = query(source, filters=Filters(predicate=Field("n").eq(1)), limit=1)
    assert len(page.records) == 1
    assert page.skipped_lines == 0


def test_watch_matches_new_records_with_predicate(tmp_path):
    source = tmp_path / "growing.log"
    source.write_text("")
    current = [0.0]

    def tick(seconds: float) -> None:
        current[0] += seconds
        with source.open("a") as stream:
            stream.write(json.dumps({"tags": ["other"]}) + "\n")
            if current[0] >= 0.5:
                stream.write(json.dumps({"tags": ["payment", "retry"]}) + "\n")

    result = watch(
        str(source),
        filters=Filters(predicate=Field("tags").contains_all(["payment", "retry"])),
        timeout=2,
        interval=0.25,
        clock=lambda: current[0],
        sleep=tick,
    )
    assert not result.timed_out
    assert result.matched is not None
    assert result.matched["tags"] == ["payment", "retry"]
