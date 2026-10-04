"""Complete trace evidence through real captured Investigation operations."""

import json

import pytest

from slogger.tools import Investigation


def write_records(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_trace_tree_joins_cross_file_identity_and_retains_source_order(tmp_path):
    first = write_records(
        tmp_path / "first.jsonl",
        [
            {"trace_id": "t", "span_id": "child", "parent_span_id": "root", "span": "same", "n": 0},
            {"trace_id": "other", "span_id": "root", "span": "same", "n": 1},
        ],
    )
    second = write_records(
        tmp_path / "second.jsonl",
        [
            {"trace_id": "t", "span_id": "root", "span": "same", "event": "span.start", "n": 2},
            {"trace_id": "t", "span_id": "child", "parent_span_id": "root", "span": "same", "n": 3},
            {"n": 4},
        ],
    )
    with Investigation.open([first, second]) as session:
        job = session.build_tree(background=False)
        assert job.status.phase == "complete"
        tree = job.result()
        roots = tree.children().rows
        assert [(row.kind, row.trace_id, row.ordinal) for row in roots] == [
            ("trace", "t", None),
            ("trace", "other", None),
            ("record", None, 4),
        ]
        span = tree.children(roots[0].key).rows[0]
        assert (span.span_id, span.relationship, span.label) == ("root", "root", "same")
        children = tree.children(span.key).rows
        assert [(row.kind, row.span_id, row.ordinal) for row in children] == [
            ("span", "child", None),
            ("record", None, 2),
        ]
        leaves = tree.children(children[0].key).rows
        assert [row.ordinal for row in leaves] == [0, 3]
        assert tree.record_page(children[0].key).origins[1].source == str(second)
        selected = tree.node_for_record(0)
        assert selected is not None and selected.span_id == "child"
        assert tree.record_count == 5


def test_tree_lifecycle_uses_unique_canonical_events_and_retains_conflicting_evidence(tmp_path):
    source = write_records(
        tmp_path / "lifecycle.jsonl",
        [
            {
                "trace_id": "t",
                "span_id": "ok",
                "span": "canonical",
                "span_name": "external",
                "event": "span.start",
            },
            {
                "trace_id": "t",
                "span_id": "ok",
                "span": "canonical",
                "event": "span.end",
                "status": "ok",
                "duration_ms": 12.5,
            },
            {
                "trace_id": "t",
                "span_id": "no-events",
                "message": "span.end",
                "status": "error",
                "duration_ms": 100,
            },
            {"trace_id": "t", "span_id": "duplicate", "event": "span.start"},
            {
                "trace_id": "t",
                "span_id": "duplicate",
                "event": "span.end",
                "status": "error",
                "duration_ms": 2,
            },
            {
                "trace_id": "t",
                "span_id": "duplicate",
                "event": "span.end",
                "status": "error",
                "duration_ms": 2,
            },
            {"trace_id": "t", "span_id": "bad-duration", "event": "span.start"},
            {
                "trace_id": "t",
                "span_id": "bad-duration",
                "event": "span.end",
                "status": "ok",
                "duration_ms": True,
            },
        ],
    )
    with Investigation.open([source]) as session:
        tree = session.build_tree(background=False).result()
        spans = {row.span_id: row for row in tree.children(tree.children().rows[0].key).rows}
        good = spans["ok"]
        assert (
            good.label,
            good.lifecycle,
            good.start_count,
            good.end_count,
            good.status,
            good.duration_ms,
        ) == (
            "canonical",
            "complete",
            1,
            1,
            "ok",
            12.5,
        )
        assert (spans["no-events"].lifecycle, spans["no-events"].duration_ms) == (
            "unavailable",
            None,
        )
        assert (
            spans["duplicate"].lifecycle,
            spans["duplicate"].end_count,
            spans["duplicate"].duration_ms,
        ) == (
            "conflicting",
            2,
            None,
        )
        assert (spans["bad-duration"].lifecycle, spans["bad-duration"].duration_ms) == (
            "conflicting",
            None,
        )
        assert len(tree.record_page(spans["duplicate"].key).records) == 3


def test_uncertain_parents_missing_placeholders_and_cycles_keep_every_record_once(tmp_path):
    source = write_records(
        tmp_path / "parents.jsonl",
        [
            {"trace_id": "t", "span_id": "missing-child", "parent_span_id": "absent"},
            {"trace_id": "t", "span_id": "self", "parent_span_id": "self"},
            {"trace_id": "t", "span_id": "a", "parent_span_id": "b"},
            {"trace_id": "t", "span_id": "b", "parent_span_id": "a"},
            {"trace_id": "t", "span_id": "descendant", "parent_span_id": "a"},
            {"trace_id": "t", "span_id": "conflict", "parent_span_id": "a", "span": "first"},
            {"trace_id": "t", "span_id": "conflict", "parent_span_id": "b", "span": "second"},
            {"trace_id": "t", "span_id": "unknown"},
            {"trace_id": "t", "span_id": "null", "parent_span_id": None},
            {"trace_id": "t", "span_id": "empty", "parent_span_id": ""},
            {"trace_id": "t", "span_id": "invalid", "parent_span_id": ["a"]},
            {"trace_id": True, "span_id": "unknown"},
            {"trace_id": "t", "span_id": 1},
        ],
    )
    with Investigation.open([source]) as session:
        tree = session.build_tree(background=False).result()
        pending = list(tree.children().rows)
        leaves, spans = [], {}
        while pending:
            row = pending.pop(0)
            if row.kind == "record":
                leaves.append(row.ordinal)
            else:
                spans[row.span_id] = row
                pending.extend(tree.children(row.key).rows)
        assert sorted(leaves) == list(range(13))
        assert spans["absent"].kind == "placeholder"
        assert spans["absent"].record_count == 0
        assert spans["absent"].first_ordinal == 0
        assert [spans[name].relationship for name in ("self", "a", "b")] == ["cycle"] * 3
        assert spans["descendant"].relationship == "parent observed"
        assert spans["conflict"].relationship == "conflicting parents"
        assert spans["conflict"].name_conflict is True
        assert spans["unknown"].relationship == "parent not observed"
        assert spans["null"].relationship == "null parent"
        assert spans["empty"].relationship == "empty parent"
        assert spans["invalid"].relationship == "invalid parent"


@pytest.mark.parametrize("filtered", [False, True])
def test_complete_large_tree_pages_every_occurrence_beyond_old_preview_caps(tmp_path, filtered):
    from slogger.tools import parse_filter

    source = write_records(
        tmp_path / "large.jsonl", ({"trace_id": "t", "span_id": "s", "n": n} for n in range(10005))
    )
    with Investigation.open([source, source]) as session:
        view = session.filter(parse_filter("n >= 0")).wait(10) if filtered else None
        if filtered:
            assert view is not None
        tree = session.build_tree(input_view=view, background=False).result()
        span = tree.node_for_record(20009)
        assert span is not None
        assert span.record_count == 20010
        offset, count = 0, 0
        while True:
            page = tree.children(span.key, offset, 127)
            count += len(page.rows)
            if not page.has_more:
                break
            offset = page.next_offset
        assert count == 20010
        assert tree.record_page(span.key, 20009, 1).records == [
            {"trace_id": "t", "span_id": "s", "n": 10004}
        ]
        assert tree.record_page(span.key, 20009, 1).identities[0].input_occurrence == 1


def test_tree_job_is_scoped_cancel_safe_and_close_joins_before_cleanup(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from slogger.tools import ToolError

    source = write_records(tmp_path / "source.jsonl", [{"trace_id": "t", "span_id": "s"}])
    original_connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()
    blocked = False

    def connect(*args, **kwargs):
        nonlocal blocked
        if threading.current_thread().name.startswith("slogger-tree-") and not blocked:
            blocked = True
            entered.set()
            assert release.wait(5)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    managed = tmp_path / "managed"
    session = Investigation.open([source], storage_dir=managed)
    first = session.build_tree()
    try:
        assert entered.wait(5)
        first.cancel()
        second = session.build_tree(background=False)
        assert second.status.phase == "complete"
        release.set()
        assert first.wait(5).phase == "canceled"
        assert first.scope.dataset_id == second.scope.dataset_id == session.dataset_id
        assert first.scope.request_id != second.scope.request_id
        with pytest.raises(ToolError):
            first.result()
        assert second.result().record_count == 1
        assert session.page().records == [{"trace_id": "t", "span_id": "s"}]
    finally:
        release.set()
        session.close()
    assert list(managed.iterdir()) == []
    with pytest.raises(ToolError):
        second.result().children()


def test_tree_resource_failure_leaves_captured_dataset_usable(tmp_path):
    from slogger.tools import ResourceLimits

    source = write_records(tmp_path / "source.jsonl", [{"trace_id": "t", "span_id": "s"}])
    with Investigation.open([source], limits=ResourceLimits(disk_bytes=128 * 1024)) as session:
        assert session.status.complete
        before = session.resources.disk_bytes
        job = session.build_tree(background=False)
        assert job.status.phase == "failed"
        assert job.status.diagnostic is not None
        assert job.status.diagnostic.code == "resource_limit"
        assert session.resources.reserved_disk_bytes == 0
        assert session.resources.disk_bytes <= before + 4096
        assert session.page().records == [{"trace_id": "t", "span_id": "s"}]


@pytest.mark.parametrize("value", [True, 1, 1.0, "", None, ["t"], {"id": "t"}])
def test_invalid_trace_identifiers_are_not_coerced_or_merged(tmp_path, value):
    source = write_records(
        tmp_path / "identifiers.jsonl",
        [
            {"trace_id": "t", "span_id": "s", "n": 0},
            {"trace_id": value, "span_id": "s", "n": 1},
        ],
    )
    with Investigation.open([source]) as session:
        tree = session.build_tree(background=False).result()
        roots = tree.children().rows
        assert roots[1].ordinal == 1
        assert roots[1].relationship == "invalid trace identifier"
        assert tree.node_for_record(1) is None
        assert session.page(1, 1).records[0]["trace_id"] == value


def test_deep_span_chain_is_paged_without_recursion_or_path_preview_limit(tmp_path):
    source = write_records(
        tmp_path / "deep.jsonl",
        (
            {"trace_id": "t", "span_id": str(n), "parent_span_id": str(n + 1)}
            if n < 1299
            else {"trace_id": "t", "span_id": str(n), "event": "span.start"}
            for n in range(1300)
        ),
    )
    with Investigation.open([source]) as session:
        tree = session.build_tree(background=False).result()
        row = tree.node_for_record(0)
        assert row is not None
        depth = 0
        while row.parent_key is not None:
            row = tree.row(row.parent_key)
            depth += 1
        assert depth == 1300
        assert row.kind == "trace"
        assert tree.record_count == 1300


def test_oversized_tree_metadata_fails_before_result_publication(tmp_path):
    from slogger.tools import ResourceLimits

    source = write_records(tmp_path / "metadata.jsonl", [{"trace_id": "t" * 700}])
    with Investigation.open([source], limits=ResourceLimits(page_memory_bytes=2048)) as session:
        assert session.status.complete
        job = session.build_tree(background=False)
        assert job.status.phase == "failed"
        assert job.status.diagnostic is not None
        assert job.status.diagnostic.code == "resource_limit"
        assert session.page().records == [{"trace_id": "t" * 700}]


def test_filtered_tree_retains_marked_ancestors_without_widening_membership(tmp_path):
    from slogger.tools import SearchOptions, parse_filter

    records = [
        {
            "trace_id": "t",
            "span_id": "root",
            "span": "needle parent",
            "event": "span.start",
            "n": 0,
        },
        {
            "trace_id": "t",
            "span_id": "child",
            "parent_span_id": "root",
            "message": "needle",
            "n": 1,
        },
        {
            "trace_id": "t",
            "span_id": "root",
            "event": "span.end",
            "status": "ok",
            "duration_ms": 4,
            "n": 2,
        },
        {"trace_id": "other", "span_id": "s", "n": 3},
        {"message": "needle", "n": 4},
    ]
    source = write_records(tmp_path / "context.jsonl", records)
    with Investigation.open([source, source]) as session:
        view = session.filter(parse_filter("n in [1, 4]")).wait(5)
        assert view is not None
        tree = session.build_tree(input_view=view, request_generation=7, background=False).result()
        assert tree.scope.input_scope == view.view_scope
        assert tree.scope.request_generation == 7
        assert tree.scope.population == "filtered"
        assert tree.record_count == 4
        roots = tree.children().rows
        assert [(row.kind, row.ordinal) for row in roots] == [
            ("trace", None),
            ("record", 4),
            ("record", 9),
        ]
        trace = roots[0]
        parent = tree.children(trace.key).rows[0]
        assert trace.context_only and parent.context_only
        assert (parent.record_count, parent.match_count, parent.lifecycle, parent.duration_ms) == (
            4,
            0,
            "conflicting",
            None,
        )
        child = tree.children(parent.key).rows[0]
        assert not child.context_only and child.match_count == 2
        assert [row.ordinal for row in tree.children(child.key).rows] == [1, 6]
        assert tree.record_page(parent.key).records == [
            records[0],
            records[2],
            records[0],
            records[2],
        ]
        assert tree.record_page(child.key).origins[1].position == 2
        search = session.search(SearchOptions("needle parent"), input_view=view).wait(5)
        assert search is not None and search.record_count == 0
        counts = session.count_values(("n",), input_view=view).wait(5)
        assert counts is not None and counts.page().records == [
            {"value": 1, "count": 2},
            {"value": 4, "count": 2},
        ]
        assert view.page().records == [records[1], records[4], records[1], records[4]]


def test_filtered_tree_leases_membership_until_construction_settles(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from slogger.tools import ToolError, parse_filter

    source = write_records(tmp_path / "lease.jsonl", [{"trace_id": "t", "span_id": "s", "n": 1}])
    connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()

    def scheduled_connect(*args, **kwargs):
        if threading.current_thread().name.startswith("slogger-tree-"):
            entered.set()
            assert release.wait(5)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", scheduled_connect)
    with Investigation.open([source]) as session:
        view = session.filter(parse_filter("n == 1")).wait(5)
        assert view is not None
        job = session.build_tree(input_view=view, request_generation=1)
        try:
            assert entered.wait(5)
            before = session.resources.disk_bytes
            view.close()
            assert session.resources.disk_bytes == before
        finally:
            release.set()
        assert job.wait(5).phase == "complete"
        tree = job.result()
        node = tree.node_for_record(0)
        assert node is not None and tree.record_count == 1 and node.span_id == "s"
        assert session.resources.reserved_disk_bytes == 0
        tree.close()
        with pytest.raises(ToolError):
            tree.children()
        with pytest.raises(ToolError):
            session.build_tree(input_view=view)


def test_filtered_tree_deep_closure_empty_scope_and_foreign_owner(tmp_path):
    from slogger.tools import ResourceLimits, ToolError, parse_filter

    source = write_records(
        tmp_path / "deep-context.jsonl",
        (
            {"trace_id": "t", "span_id": str(n), "parent_span_id": str(n + 1), "n": n}
            if n < 1299
            else {"trace_id": "t", "span_id": str(n), "event": "span.start", "n": n}
            for n in range(1300)
        ),
    )
    with Investigation.open(
        [source], limits=ResourceLimits(working_memory_bytes=128 * 1024)
    ) as session:
        view = session.filter(parse_filter("n == 0")).wait(5)
        assert view is not None
        tree = session.build_tree(input_view=view, background=False).result()
        row = tree.node_for_record(0)
        assert row is not None
        depth = 0
        while row.parent_key is not None:
            row = tree.row(row.parent_key)
            assert row.context_only
            depth += 1
        assert depth == 1300 and tree.is_ancestor(row.key, 0)
        assert tree.children().rows[0].child_count == 1
        empty = session.filter(parse_filter("n == -1")).wait(5)
        assert empty is not None
        empty_tree = session.build_tree(input_view=empty, background=False).result()
        assert empty_tree.record_count == 0 and empty_tree.children().rows == []
        with Investigation.open([source]) as other:
            with pytest.raises(ToolError) as error:
                other.build_tree(input_view=view)
            assert error.value.code == "scope_mismatch"


def test_filtered_tree_cancellation_cleanup_failure_is_settled_and_capture_survives(
    tmp_path, monkeypatch
):
    import sqlite3
    import threading
    from pathlib import Path

    from slogger.tools import parse_filter

    source = write_records(tmp_path / "failure.jsonl", [{"trace_id": "t", "span_id": "s"}])
    connect, unlink = sqlite3.connect, Path.unlink
    entered, release = threading.Event(), threading.Event()

    def scheduled_connect(*args, **kwargs):
        if threading.current_thread().name.startswith("slogger-tree-"):
            entered.set()
            assert release.wait(5)
        return connect(*args, **kwargs)

    def failed_unlink(path, *args, **kwargs):
        if path.name.startswith("tree-"):
            raise OSError("injected staging unlink failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", scheduled_connect)
    with Investigation.open([source]) as session:
        view = session.filter(parse_filter('trace_id == "t"')).wait(5)
        assert view is not None
        job = session.build_tree(input_view=view)
        try:
            assert entered.wait(5)
            view.close()
            monkeypatch.setattr(Path, "unlink", failed_unlink)
            job.cancel()
        finally:
            release.set()
        assert job.wait(5).phase == "failed" and job.done
        assert job.status.diagnostic is not None
        assert job.status.diagnostic.code == "cleanup_failed"
        assert session.resources.reserved_disk_bytes == 0
        assert session.page().records == [{"trace_id": "t", "span_id": "s"}]
        monkeypatch.setattr(Path, "unlink", unlink)
