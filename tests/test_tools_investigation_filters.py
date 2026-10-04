"""Complete captured filtering through the shared public session boundary."""

import json

from slogger.tools import Investigation, SourceOrigin, parse_filter


def test_filtered_pages_keep_typed_paths_order_origins_and_dataset_identity(tmp_path):
    source = tmp_path / "records.jsonl"
    records = [
        {"n": False, "a.b": 7, "a": {"b": 1}},
        {"n": 0, "a.b": 7, "a": {"b": 2}, "_id": "application"},
        {"n": 1, "a.b": 8, "a": {"b": 2}},
        {"n": 0, "a.b": 7, "a": {"b": 2}},
    ]
    source.write_text("invalid\n" + "\n".join(json.dumps(r) for r in records))
    with Investigation.open([source, source]) as session:
        expression = parse_filter('n == 0 AND a.b == 2 AND ["a.b"] == 7')
        job = session.filter(expression, request_generation=4)
        view = job.wait(10)
        assert view is not None and job.status.phase == "complete"
        assert view.scope.request_generation == 4
        assert view.record_count == 4
        first = view.page(0, 2)
        last = view.page(first.next_offset, 2)
        assert first.records + last.records == [records[1], records[3]] * 2
        assert [i.ordinal for i in first.identities + last.identities] == [1, 3, 5, 7]
        assert [i.input_occurrence for i in first.identities + last.identities] == [0, 0, 1, 1]
        assert first.origins == [
            SourceOrigin(str(source), 3, "file"),
            SourceOrigin(str(source), 5, "file"),
        ]
        assert first.offset == 0 and last.next_offset == 4


def test_full_infix_language_agrees_with_materialized_reference(tmp_path):
    import pytest

    from slogger.tools import Field, all_of, any_of, logger_prefix, not_, scan

    source = tmp_path / "domain.jsonl"
    rows = [
        {
            "n": 1,
            "flag": True,
            "x": None,
            "arr": [1, False],
            "obj": {"v": [1, True]},
            "message": "prefix a.b tail",
            "logger": "app.child",
        },
        {
            "n": 2.5,
            "flag": False,
            "arr": [],
            "obj": {"v": [1, 1]},
            "message": "axb",
            "logger": "application",
        },
        {"n": False, "flag": 1, "arr": [True, None], "obj": {}, "message": 7, "logger": "app"},
        {},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    cases = [
        ("n >= 1 AND n < 3", all_of(Field("n").ge(1), Field("n").lt(3))),
        ("n <= 1 OR n > 2", any_of(Field("n").le(1), Field("n").gt(2))),
        ("flag != false", Field("flag").ne(False)),
        ('obj == {"v":[1,true]}', Field("obj").eq({"v": [1, True]})),
        ("arr == [1,false]", Field("arr").eq([1, False])),
        ("n IN [false,1,null]", Field("n").in_([False, 1, None])),
        ("n NOT IN [1]", Field("n").not_in([1])),
        ("arr contains_any [false,null]", Field("arr").contains_any([False, None])),
        ("contains_all(arr, [1,false])", Field("arr").contains_all([1, False])),
        ('message contains "a.b"', Field("message").regex(r"a\.b")),
        ('message matches "a.b"', Field("message").regex("a.b")),
        ('starts_with(message, "prefix")', Field("message").starts_with("prefix")),
        ("exists(x)", Field("x").exists()),
        ("x missing", Field("x").missing()),
        ('logger_prefix("app")', logger_prefix("app")),
        (
            "NOT flag == true AND n == 2.5 OR x == null",
            any_of(all_of(not_(Field("flag").eq(True)), Field("n").eq(2.5)), Field("x").eq(None)),
        ),
        (
            "NOT (flag == true OR n == 2.5)",
            not_(any_of(Field("flag").eq(True), Field("n").eq(2.5))),
        ),
        ("", all_of()),
    ]
    with Investigation.open([source]) as session:
        for text, expected in cases:
            try:
                actual = parse_filter(text)
            except Exception as error:
                pytest.fail(f"{text}: {error}")
            reference = scan(source).filter(expected).execute()
            view = session.filter(actual).wait(10)
            assert view is not None
            assert view.page().records == reference.records, text
            assert view.page().origins == reference.origins, text
            view.close()


def test_quoted_paths_round_trip_and_invalid_drafts_have_locations(tmp_path):
    import pytest

    from slogger.tools import FilterSyntaxError, format_field_path, parse_field_path

    paths = [("a.b",), ("a", "with space", 'quote"slash\\', "café"), ("NOT",)]
    source = tmp_path / "keys.jsonl"
    source.write_text(
        json.dumps({"a.b": 1, "a": {"with space": {'quote"slash\\': {"café": 2}}}, "NOT": 3})
    )
    with Investigation.open([source]) as session:
        for path, value in zip(paths, (1, 2, 3), strict=True):
            spelling = format_field_path(path)
            assert parse_field_path(spelling) == path
            view = session.filter(parse_filter(f"{spelling} == {value}")).wait(10)
            assert view is not None and view.record_count == 1
        for text in (
            "n ==",
            "n > true",
            "n IN [[1]]",
            'message matches "["',
            '[""] == 1',
            "a[0] == 1",
        ):
            with pytest.raises(FilterSyntaxError) as caught:
                parse_filter(text)
            assert caught.value.column > 0
            assert caught.value.offset <= len(text)
            assert caught.value.code in ("filter_syntax", "filter_type")


def test_cancel_terminates_pathological_regex_and_preserves_successful_view(tmp_path):
    import time

    source = tmp_path / "regex.jsonl"
    source.write_text('{"message":"safe"}\n' * 128 + json.dumps({"message": "a" * 5000 + "!"}))
    with Investigation.open([source]) as session:
        successful = session.filter(parse_filter('message == "safe"'), request_generation=1).wait(
            10
        )
        assert successful is not None and successful.record_count == 128
        pending = session.filter(parse_filter('message matches "(a+)+$"'), request_generation=2)
        deadline = time.monotonic() + 5
        while pending.status.processed_records < 128 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pending.status.processed_records == 128
        pending.cancel()
        assert pending.wait(2) is None
        assert pending.status.phase == "cancelled"
        assert successful.page(127, 1).records == [{"message": "safe"}]
        assert successful.scope.request_generation == 1
        assert session.resources.reserved_disk_bytes == 0


def test_explicit_input_view_leases_empty_scopes_and_close_cleanup(tmp_path):
    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "scope.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n{"n":3}\n')
    storage = tmp_path / "storage"
    with Investigation.open([source], storage_dir=storage) as session:
        parent = session.filter(parse_filter("n >= 2")).wait(10)
        assert parent is not None
        job = session.filter(parse_filter("n < 3"), input_view=parent, request_generation=8)
        parent.close()
        child = job.wait(10)
        assert child is not None
        assert child.page().records == [{"n": 2}]
        assert child.page().identities[0].ordinal == 1
        assert child.scope.input_scope == parent.view_scope
        empty = session.filter(parse_filter("n < 0"), input_view=child).wait(10)
        assert empty is not None and empty.record_count == 0 and empty.page().complete
        with Investigation.open([source]) as other:
            with pytest.raises(ToolError) as error:
                other.filter(parse_filter(""), input_view=child)
            assert error.value.code == "scope_mismatch"
    assert list(storage.iterdir()) == []
    with pytest.raises(ToolError):
        child.page()


def test_failed_result_admission_retains_previous_handle_and_releases_staging(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "budget.jsonl"
    source.write_text('{"n":1}\n' * 1200)
    with Investigation.open([source], limits=ResourceLimits(disk_bytes=64 * 1024)) as session:
        assert session.status.complete
        previous = session.filter(parse_filter("n == 0")).wait(10)
        assert previous is not None and previous.record_count == 0
        usage = session.resources.managed_disk_bytes
        pending = session.filter(parse_filter("n == 1"))
        assert pending.wait(10) is None
        assert pending.status.phase == "failed"
        assert pending.diagnostics[0].code == "resource_limit"
        assert previous.page().records == []
        assert session.resources.managed_disk_bytes == usage
        assert session.resources.reserved_disk_bytes == 0


def test_filter_jobs_work_from_an_ordinary_installed_python_script(tmp_path):
    import subprocess
    import sys

    source = tmp_path / "script.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')
    script = tmp_path / "query.py"
    script.write_text(
        "from slogger.tools import Investigation, parse_filter\n"
        f"with Investigation.open([{str(source)!r}]) as session:\n"
        "    view = session.filter(parse_filter('n == 2')).wait(10)\n"
        "    assert view is not None\n"
        "    assert view.page().records == [{'n': 2}]\n"
        "print('complete')\n"
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "complete\n"


def test_complete_results_reach_late_records_with_bounded_pages(tmp_path):
    from slogger.tools import ResourceLimits

    source = tmp_path / "late.jsonl"
    source.write_text('{"n":0}\n' * 12056 + '{"n":1,"late":true}')
    with Investigation.open(
        [source], limits=ResourceLimits(page_memory_bytes=1200, ram_cache_bytes=512)
    ) as session:
        view = session.filter(parse_filter("")).wait(10)
        assert view is not None and view.record_count == 12057
        page = view.page(12050, 100)
        assert 12050 < page.next_offset < 12057
        last = view.page(12056, 1)
        assert last.records == [{"n": 1, "late": True}]
        assert last.identities[0].ordinal == 12056
        assert view.position_of(12056) == 12056
        late = session.filter(parse_filter("late exists")).wait(10)
        assert late is not None and late.record_count == 1
        assert late.page().identities[0].ordinal == 12056
        assert session.resources.ram_cache_bytes <= 512


def test_closed_input_and_failed_capture_are_rejected_without_result_growth(tmp_path):
    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "ready.jsonl"
    source.write_text('{"n":1}')
    with Investigation.open([source]) as session:
        view = session.filter(parse_filter("")).wait(10)
        assert view is not None
        view.close()
        usage = session.resources.managed_disk_bytes
        with pytest.raises(ToolError) as error:
            session.filter(parse_filter(""), input_view=view)
        assert error.value.code == "view_closed"
        assert session.resources.managed_disk_bytes == usage
    with Investigation.open([tmp_path / "missing"]) as session:
        with pytest.raises(ToolError) as error:
            session.filter(parse_filter(""))
        assert error.value.code == "dataset_incomplete"


def test_worker_start_failure_is_structured_and_keeps_successful_view(tmp_path, monkeypatch):
    import subprocess

    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "start.jsonl"
    source.write_text('{"n":1}')
    with Investigation.open([source]) as session:
        previous = session.filter(parse_filter("")).wait(10)
        assert previous is not None
        usage = session.resources.managed_disk_bytes

        def unavailable_process(*args, **kwargs):
            raise OSError("process admission denied")

        monkeypatch.setattr(subprocess, "Popen", unavailable_process)
        with pytest.raises(ToolError) as error:
            session.filter(parse_filter("n == 1"))
        assert error.value.code == "execution_failed"
        assert previous.page().records == [{"n": 1}]
        assert session.resources.managed_disk_bytes == usage


def test_session_close_joins_a_regex_job_before_releasing_storage(tmp_path):
    import time

    source = tmp_path / "close.jsonl"
    source.write_text('{"message":"safe"}\n' * 128 + json.dumps({"message": "a" * 5000 + "!"}))
    storage = tmp_path / "storage"
    session = Investigation.open([source], storage_dir=storage)
    job = session.filter(parse_filter('message matches "(a+)+$"'))
    deadline = time.monotonic() + 5
    while job.status.processed_records < 128 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.status.processed_records == 128
    session.close()
    assert job.done and job.wait(0) is None
    assert job.status.phase == "cancelled"
    assert session.status.phase == "closed" and list(storage.iterdir()) == []
    session.close()
