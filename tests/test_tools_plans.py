"""Caller-level contract for immutable record query plans."""

from slogger.tools import Field, scan


def test_python_plan_executes_without_modifying_its_parent():
    records = [{"level": "INFO", "message": "one"}, {"level": "ERROR", "message": "two"}]
    parent = scan(records)
    plan = parent.filter(Field("level").eq("ERROR")).select("message").limit(1)
    result = plan.execute()
    assert result.records == [{"message": "two", "_id": "mem:1"}]
    assert result.schema == ("message",)
    assert result.metadata["backend"] == "python"
    assert parent.execute().records == [
        dict(record, _id=f"mem:{i}") for i, record in enumerate(records)
    ]


def test_builder_order_is_semantic_and_zero_limit_reads_no_file(tmp_path):
    records = [{"level": "INFO"}, {"level": "ERROR"}, {"level": "ERROR"}]
    parent = scan(records)
    errors = Field("level").eq("ERROR")
    assert parent.filter(errors).limit(1).execute().records == [{"level": "ERROR", "_id": "mem:1"}]
    assert parent.limit(1).filter(errors).execute().records == []
    path = tmp_path / "bad.log"
    path.write_text('not-json\n{"message":"ok"}\n')
    result = scan(path).limit(0).execute()
    assert result.records == []
    assert result.metadata["input_rows"] == 0
    assert result.metadata["skipped_lines"] == 0


def test_closed_projection_schema_rejects_removed_fields():
    import pytest

    from slogger.tools import ToolError

    plan = scan([{"x": 1}]).select("message").filter(Field("x").eq(1))
    for action in (plan.execute, plan.explain):
        with pytest.raises(ToolError) as failure:
            action()
        assert failure.value.code == "plan_invalid"
        assert failure.value.extra["field"] == ["x"]
    assert scan([{}]).filter(Field("unknown").missing()).execute().records == [{"_id": "mem:0"}]
    assert scan([{"request": {"method": "POST"}}]).select("request").filter(
        Field("request", "method").eq("POST")
    ).execute().records == [{"request": {"method": "POST"}, "_id": "mem:0"}]


def test_explain_is_static_even_for_nonexistent_files_and_generators(tmp_path):
    consumed = []

    def records():
        consumed.append(True)
        yield {"x": 1}

    plan = scan(records()).filter(Field("x").eq(1)).select("message").limit(3)
    explanation = plan.explain()
    assert consumed == []
    assert explanation["required_fields"] == [["message"], ["x"]]
    assert explanation["properties"] == {
        "schema": ["message"],
        "schema_open": False,
        "ordering": "concat",
        "preserves_record_identity": True,
        "finite_source_required": True,
        "output_bound": 3,
        "source_cursor_eligible": True,
    }
    assert [node["op"] for node in explanation["operations"]] == [
        "scan",
        "filter",
        "project",
        "limit",
    ]
    assert explanation["pending_data_checks"]
    assert scan(tmp_path / "absent.log").explain()["properties"]["schema_open"]
    assert plan.execute().records == [{"_id": "mem:0"}]
    assert consumed == [True]


def test_projected_identity_cannot_satisfy_removed_user_field():
    import pytest

    from slogger.tools import ToolError

    with pytest.raises(ToolError, match="unavailable"):
        scan([{"message": "one"}]).select("message").filter(Field("_id").exists()).execute()


def test_file_filter_limit_preserves_shape_and_accounts_only_consumed_lines(tmp_path):
    path = tmp_path / "app.log"
    path.write_text('\nnot-json\n[]\n{"x":1}\n{"x":2,"nested":{"a":null}}\nnot-json\n')
    result = scan(path).filter(Field("x").eq(2)).select("nested", "absent").limit(1).execute()
    assert result.records == [{"nested": {"a": None}, "_id": f"{path}:5"}]
    assert result.schema == ("nested", "absent")
    assert result.metadata["input_rows"] == 2
    assert result.metadata["skipped_lines"] == 2
    assert result.warnings == []


def test_invalid_builder_arguments_and_backend_are_explicit():
    import pytest

    from slogger.tools import ToolError

    with pytest.raises(TypeError, match="source"):
        scan(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="order"):
        scan([], order="random")  # type: ignore[arg-type]
    plan = scan([])
    for names in ((), ("",), ("message", "message")):
        with pytest.raises(ValueError):
            plan.select(*names)
    for count in (-1, True, 1.5):
        with pytest.raises(ValueError):
            plan.limit(count)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Predicate"):
        plan.filter(True)  # type: ignore[arg-type]
    with pytest.raises(ToolError) as failure:
        plan.execute(backend="unknown")
    assert failure.value.code == "backend_unsupported"


def test_reader_conventions_match_existing_query_metadata(tmp_path):
    from slogger.tools import query

    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first.write_text('bad\n{"timestamp":"2026-01-02T00:00:00Z","message":"later"}\n')
    second.write_text(
        '{"timestamp":"2026-01-01T00:00:00Z","message":"first"}\n{"message":"no time"}\n'
    )
    sources = [first, second]
    legacy = query(sources, order="time")
    result = scan(sources, order="time").execute()
    assert result.records == legacy.records
    assert result.warnings == legacy.warnings
    assert result.metadata["skipped_lines"] == legacy.skipped_lines
    assert result.metadata["ordering"] == "time"


def test_execution_errors_preserve_causes_and_invalid_plans_do_not_read(tmp_path):
    import pytest

    from slogger.tools import ToolError

    with pytest.raises(ToolError) as failure:
        scan(tmp_path / "missing.log").execute()
    assert failure.value.code == "execution_failed"
    assert isinstance(failure.value.__cause__, FileNotFoundError)
    consumed = []

    def records():
        consumed.append(True)
        yield {"x": 1}

    with pytest.raises(ToolError, match="unavailable"):
        scan(records()).select("message").filter(Field("x").eq(1)).execute()
    assert consumed == []


def test_owned_file_handles_close_on_limit_and_execution_failure(tmp_path, monkeypatch):
    import builtins

    import pytest

    from slogger.tools import Predicate, ToolError

    path = tmp_path / "app.log"
    path.write_text('{"x":1}\n{"x":2}\n')
    opened = []
    real_open = builtins.open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", tracking_open)
    assert scan(path).limit(1).execute().records == [{"x": 1, "_id": f"{path}:1"}]
    assert opened and all(handle.closed for handle in opened)

    class Broken(Predicate):
        def to_ixr(self):
            return Field("x").eq(1).to_ixr()

        def compile(self):
            def matcher(record):
                raise RuntimeError("broken predicate")

            return matcher

        def explain(self):
            return {"broken": True}

    with pytest.raises(ToolError, match="broken predicate") as failure:
        scan(path).filter(Broken()).execute()
    assert failure.value.code == "execution_failed"
    assert isinstance(failure.value.__cause__, RuntimeError)
    assert all(handle.closed for handle in opened)


def test_limit_accepts_arbitrary_nonnegative_python_integers():
    assert scan([{"message": "one"}]).limit(10**50).execute().records == [
        {"message": "one", "_id": "mem:0"}
    ]
