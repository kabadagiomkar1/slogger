"""Complete literal searches through the headless investigation interface."""

import json

from slogger.tools import Investigation, parse_filter


def test_search_decodes_names_and_leaves_without_escape_or_cross_leaf_matches(tmp_path):
    from slogger.tools import SearchOptions

    source = tmp_path / "records.jsonl"
    rows = [
        {"message": "ordinary", "hidden": {'quoted"key': "line\nnext\\end"}},
        {"message": "left", "other": "right"},
        {"message": "null true 12", "value": False},
        {"message": "needle needle", "nested": ["needle", {"needle": "needle"}]},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source]) as session:
        for needle, expected in [
            ("line\nnext", [0]),
            ('quoted"key', [0]),
            ("\\n", []),
            ("left right", []),
            ("false", [2]),
            ("needle", [3]),
        ]:
            result = session.search(SearchOptions(needle, scope="full")).wait(10)
            assert result is not None
            assert result.record_count == len(expected)
            assert [identity.ordinal for identity in result.page().identities] == expected
        narrowed = session.filter(parse_filter('message == "ordinary"')).wait(10)
        result = session.search(SearchOptions("needle", scope="full"), input_view=narrowed).wait(10)
        assert result is not None and result.record_count == 0


def test_console_projection_is_explicit_complete_and_visibility_sensitive(tmp_path):
    import pytest

    from slogger.tools import SearchOptions, SearchProjection

    source = tmp_path / "console.jsonl"
    rows = [
        {
            "message": "x" * 20000 + "late",
            "logger": "long.logger.name.tail",
            "duration_ms": 345,
            "trace_id": "hidden",
        },
        {"message": "span", "span": "canonical", "span_name": "fallback"},
        {"message": "span", "span_name": "fallback"},
        {"trace_id": "generic"},
        {"message": "custom", "payload": {"deep key": "nested value"}},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    policy = SearchProjection(
        ("message", "logger", "span"),
        ("trace_id", "duration_ms", "span_name"),
        fallback_fields=(("span", "span_name"),),
    )
    with pytest.raises(ValueError, match="explicit"):
        SearchOptions("late", scope="console")
    with Investigation.open([source]) as session:
        for needle, expected in [
            ("late", [0]),
            ("tail", [0]),
            ("hidden", []),
            ("345", []),
            ("fallback", [2]),
            ("generic", [3]),
            ("deep key", [4]),
        ]:
            result = session.search(SearchOptions(needle, scope="console", projection=policy)).wait(
                10
            )
            assert result is not None
            assert [identity.ordinal for identity in result.page().identities] == expected
        duration = SearchProjection(
            policy.primary_fields,
            policy.hidden_fields,
            include_fields=("duration_ms",),
            fallback_fields=policy.fallback_fields,
        )
        result = session.search(SearchOptions("345", scope="console", projection=duration)).wait(10)
        assert result is not None and result.page().identities[0].ordinal == 0


def test_unicode_words_casefold_scalars_and_decoded_newlines_agree(tmp_path):
    from slogger.tools import SearchOptions

    source = tmp_path / "unicode.jsonl"
    rows = [
        {"text": message}
        for message in [
            "Straße",
            "strasse",
            "prefix_strasse",
            "STRASSE!",
            "café",
            "cafe\u0301",
            "A\nB",
        ]
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source]) as session:
        cases = [
            (SearchOptions("STRASSE", whole_word=True), [0, 1, 3]),
            (SearchOptions("STRASSE", case_sensitive=True, whole_word=True), [3]),
            (SearchOptions("cafe", whole_word=True), []),
            (SearchOptions("café", whole_word=True), [4]),
            (SearchOptions("ss"), [0, 1, 2, 3]),
            (SearchOptions("s", whole_word=True), []),
            (SearchOptions("A\nB"), [6]),
        ]
        for options, expected in cases:
            result = session.search(options).wait(10)
            assert result is not None
            assert [identity.ordinal for identity in result.page().identities] == expected


def test_complete_paged_matches_count_records_and_navigate_relative_to_cursor(tmp_path):
    from slogger.tools import ResourceLimits, SearchOptions

    source = tmp_path / "complete.jsonl"
    source.write_text(
        '{"message":"needle needle","id":0}\n' * 12056 + '{"message":"last needle","id":1}'
    )
    with Investigation.open(
        [source, source], limits=ResourceLimits(page_memory_bytes=1300, ram_cache_bytes=512)
    ) as session:
        result = session.search(SearchOptions("needle"), request_generation=8).wait(20)
        assert result is not None and result.record_count == 24114
        assert result.scope.request_generation == 8
        page = result.page(24110, 100)
        assert 24110 < page.next_offset < 24114
        assert result.page(24113, 1).records == [{"message": "last needle", "id": 1}]
        assert result.page(24113, 1).identities[0].input_occurrence == 1
        assert result.neighbor(24113) == 0
        assert result.neighbor(0, previous=True) == 24113
        assert result.neighbor(12056) == 12057
        assert result.neighbor(12056, previous=True) == 12055
        assert session.resources.ram_cache_bytes <= 512
        empty = session.search(SearchOptions("")).wait(20)
        assert empty is not None and empty.record_count == 0 and empty.neighbor(0) is None


def test_search_input_leases_cancellation_failure_and_close_preserve_capture(tmp_path):
    import pytest

    from slogger.tools import ResourceLimits, SearchOptions, ToolError

    source = tmp_path / "cancel.jsonl"
    source.write_text('{"message":"evidence"}\n' * 24000)
    with Investigation.open([source]) as session:
        narrowed = session.filter(parse_filter("")).wait(10)
        assert narrowed is not None
        job = session.search(SearchOptions("evidence"), input_view=narrowed)
        narrowed.close()
        result = job.wait(20)
        assert result is not None and result.record_count == 24000
        canceled = session.search(SearchOptions("evidence"))
        canceled.cancel()
        assert canceled.wait(20) is None and canceled.status.phase == "cancelled"
        assert result.page(23999, 1).records == [{"message": "evidence"}]
        assert session.page(0, 1).records == [{"message": "evidence"}]
        with pytest.raises(ToolError) as error:
            session.search(SearchOptions("evidence"), input_view=narrowed)
        assert error.value.code == "view_closed"
        captured_cost = session.resources.disk_bytes - 24000 * 8
        session.close()
        with pytest.raises(ToolError):
            result.page()
        assert not session.storage.root.exists()
    with Investigation.open(
        [source], limits=ResourceLimits(disk_bytes=captured_cost + 65536)
    ) as session:
        job = session.search(SearchOptions("evidence"))
        assert job.wait(10) is None and job.status.phase == "failed"
        assert job.diagnostics[0].code == "resource_limit"
        assert session.page(0, 1).records == [{"message": "evidence"}]
    with Investigation.open([tmp_path / "absent"]) as session:
        with pytest.raises(ToolError) as error:
            session.search(SearchOptions("evidence"))
        assert error.value.code == "dataset_incomplete"
