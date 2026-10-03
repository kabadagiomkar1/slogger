import pytest

from slogger.tools import Field, count_rows, scan


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_source_origin_survives_filter_project_sort(backend):
    records = [{"_id": "user-b", "n": 2}, {"_id": "user-a", "n": 1}, {"n": 0}]
    result = (
        scan(records)
        .filter(Field("n").gt(0))
        .select("_id", "n")
        .sort_by("n")
        .execute(backend=backend)
    )
    assert result.records == [{"_id": "user-a", "n": 1}, {"_id": "user-b", "n": 2}]
    assert [
        (origin.source, origin.position, origin.kind)
        for origin in result.origins
        if origin is not None
    ] == [("mem", 1, "iterable"), ("mem", 0, "iterable")]
    assert records == [{"_id": "user-b", "n": 2}, {"_id": "user-a", "n": 1}, {"n": 0}]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_file_physical_origin_and_aggregate_absence(tmp_path, backend):
    path = tmp_path / "input.jsonl"
    path.write_text('{"n": 2}\ninvalid\n\n[]\n{"n": 1}')
    result = scan(path).sort_by("n").execute(backend=backend)
    assert result.records == [{"n": 1}, {"n": 2}]
    assert [(o.source, o.position, o.kind) for o in result.origins if o is not None] == [
        (str(path), 5, "file"),
        (str(path), 1, "file"),
    ]
    assert result.metadata["skipped_lines"] == 2
    assert scan(path).aggregate(total=count_rows()).execute(backend=backend).origins == [None]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_generator_lazy_zero_limit_and_one_shot(backend):
    consumed = []

    def records():
        for n in range(4):
            consumed.append(n)
            yield {"n": n}

    iterator = records()
    plan = scan(iterator)
    plan.explain(backend=backend)
    assert consumed == []
    assert plan.limit(0).execute(backend=backend).records == []
    assert consumed == []
    assert plan.limit(1).execute(backend=backend).records == [{"n": 0}]
    assert consumed == [0]
    assert plan.execute(backend=backend).records == [{"n": 1}, {"n": 2}, {"n": 3}]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_reusable_and_user_id_grouping(backend):
    plan = scan([{"_id": "app", "n": 1}])
    assert (
        plan.execute(backend=backend).records
        == plan.execute(backend=backend).records
        == [{"_id": "app", "n": 1}]
    )
    grouped = plan.group_by("_id").aggregate(total=count_rows()).execute(backend=backend)
    assert grouped.records == [{"_id": "app", "total": 1}]
    assert grouped.origins == [None]
    assert plan.aggregate(_id=count_rows()).execute(backend=backend).records == [{"_id": 1}]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_stdin_and_iterator_are_caller_owned(monkeypatch, backend):
    import io

    stream = io.StringIO('bad\n{"n": 1}\n{"n": 2}')
    monkeypatch.setattr("sys.stdin", stream)
    result = scan("-").limit(1).execute(backend=backend)
    assert result.records == [{"n": 1}]
    assert [(o.source, o.position, o.kind) for o in result.origins if o is not None] == [
        ("-", 2, "stdin")
    ]
    assert not stream.closed
    assert scan("-").execute(backend=backend).records == [{"n": 2}]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_mixed_source_time_merge_stable_origins(tmp_path, backend):
    path = tmp_path / "app.jsonl"
    path.write_text(
        '{"timestamp":"2026-01-01T00:00:00Z", "n": 1}\n'
        '{"timestamp":"2026-01-01T00:00:02Z", "n": 3}\n'
    )
    memory = [{"timestamp": "2026-01-01T00:00:00Z", "n": 2}]
    result = scan([path, memory], order="time").select("n").execute(backend=backend)
    assert result.records == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert [(o.source, o.position) for o in result.origins if o is not None] == [
        (str(path), 1),
        ("mem", 0),
        (str(path), 2),
    ]


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_merged_owned_files_close_on_limit_and_error(tmp_path, monkeypatch, backend):
    import builtins

    from slogger.tools import ToolError, sum_of

    paths = [tmp_path / "a", tmp_path / "b"]
    for path in paths:
        path.write_text('{"timestamp":"2026-01-01T00:00:00Z", "n": "bad"}\n')
    opened = []
    real_open = builtins.open

    def tracking(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", tracking)
    scan(paths, order="time").limit(1).execute(backend=backend)
    assert len(opened) == 2 and all(handle.closed for handle in opened)
    with pytest.raises(ToolError):
        scan(paths, order="time").aggregate(total=sum_of(Field("n"))).execute(backend=backend)
    assert all(handle.closed for handle in opened)


@pytest.mark.parametrize("backend", ["python", "polars"])
def test_zero_limit_avoids_input_even_after_blocking_operations(backend):
    consumed = []

    def records():
        consumed.append(True)
        yield {"n": 1}

    plan = scan(records()).sort_by("n").limit(0)
    assert plan.execute(backend=backend).records == []
    assert consumed == []
    assert scan(records()).limit(0).aggregate(total=count_rows()).execute(
        backend=backend
    ).records == [{"total": 0}]
    assert consumed == []
