import json
from pathlib import Path

from slogger.tools import Investigation, complete_filter


def test_discovery_covers_late_paths_and_preserves_scalar_types(tmp_path: Path):
    source = tmp_path / "records.jsonl"
    with source.open("w") as output:
        for index in range(300):
            output.write(
                json.dumps({"trace_id": f"trace-{index}", "payload": {"user": index}}) + "\n"
            )
        for value in [1, 1.0, True, None, 'a "quoted" value']:
            output.write(
                json.dumps({"late.key": {"spaced key": value}, "span": "rare-span"}) + "\n"
            )
    with Investigation.open([source], storage_dir=tmp_path) as session:
        job = session.discover(background=False)
        assert job.wait().phase == "complete"
        index = job.result()
        assert index.scope.dataset_id == session.dataset_id
        assert job.status.processed_records == 305
        fields = index.fields(prefix='["late.key"]', limit=2)
        assert [choice.path for choice in fields.choices] == [
            ("late.key",),
            ("late.key", "spaced key"),
        ]
        assert fields.has_more is False
        values = []
        offset = 0
        while True:
            page = index.values(("late.key", "spaced key"), offset=offset, limit=2)
            values.extend(choice.insertion for choice in page.choices)
            if not page.has_more:
                break
            offset = page.next_offset
        assert set(values) == {"1", "1.0", "true", "null", '"a \\"quoted\\" value"'}
        late = index.values(("trace_id",), prefix='"trace-299', limit=1)
        assert [choice.value for choice in late.choices] == ["trace-299"]
        completion = index.complete(complete_filter('span == "rare', generation=7), limit=2)
        assert completion.completion.generation == 7
        choice = completion.completion.choices[0]
        assert completion.completion.apply(
            choice, text='span == "rare', cursor=13, generation=7
        ) == ('span == "rare-span" ', 20)


def test_discovery_literal_prefixes_common_ranking_and_nested_component_edits(tmp_path):
    source = tmp_path / "prefixes.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"path": {"a.b": "rare", "alpha": "common"}, "a%b": "a_b", "a_b": "a%b"},
                {"path": {"alpha": "common"}},
                {"path": {"alpha": "uncommon"}},
            ]
        )
    )
    with Investigation.open([source], storage_dir=tmp_path) as session:
        index = session.discover(background=False).result()
        assert [c.path for c in index.fields(prefix="a_", limit=2).choices] == [("a_b",)]
        assert [c.value for c in index.values(("a_b",), prefix='"a%', limit=2).choices] == ["a%b"]
        assert [
            (c.value, c.occurrences) for c in index.values(("path", "alpha"), limit=1).choices
        ] == [("common", 2)]
        request = complete_filter('path["a')
        page = index.complete(request, limit=2)
        assert request.field_path == ("path",)
        assert [c.label for c in page.completion.choices] == ["path.alpha", 'path["a.b"]']
        choice = page.completion.choices[1]
        assert page.completion.apply(
            choice, text=request.text, cursor=request.cursor, generation=0
        ) == ('path["a.b"]', 11)
        request = complete_filter("path.a")
        page = index.complete(request, limit=2)
        assert page.completion.apply(
            page.completion.choices[1], text=request.text, cursor=request.cursor, generation=0
        ) == ('path["a.b"] ', 12)


def test_discovery_has_no_line_key_value_depth_or_text_sampling_caps(tmp_path):
    source = tmp_path / "large-discovery.jsonl"
    nested = {"final": "deep value"}
    for _ in range(40):
        nested = {"child": nested}
    wide: dict[str, object] = {f"custom_{i:04}": i for i in range(1200)}
    wide.update({"nested": nested, "long": "v" * 12000, "trace_id": "late-trace"})
    with source.open("w") as output:
        for number in range(20010):
            output.write(json.dumps({"span_id": f"id-{number}"}) + "\n")
        output.write(json.dumps(wide))
    with Investigation.open([source], storage_dir=tmp_path) as session:
        job = session.discover(background=False)
        assert job.wait().phase == "complete"
        index = job.result()
        assert (
            index.values(("span_id",), prefix='"id-20009', limit=1).choices[0].value == "id-20009"
        )
        assert index.fields(prefix="custom_1199", limit=1).choices[0].path == ("custom_1199",)
        path = ("nested",) + ("child",) * 40 + ("final",)
        assert index.values(path, limit=1).choices[0].value == "deep value"
        assert index.values(("long",), limit=1).choices[0].value == "v" * 12000
        offset = 0
        count = 0
        while True:
            page = index.values(("span_id",), offset=offset, limit=127)
            count += len(page.choices)
            if not page.has_more:
                break
            assert page.next_offset > offset
            offset = page.next_offset
        assert count == 20010


def test_discovery_collection_guidance_and_missing_scalars_are_honest(tmp_path):
    source = tmp_path / "collections.jsonl"
    source.write_text(
        '{"items":[{"hidden":"inside array"}],"object":{"leaf":null},'
        '"":{"hidden":"empty path"},"not_finite":NaN}'
    )
    with Investigation.open([source], storage_dir=tmp_path) as session:
        job = session.discover(background=False)
        index = job.result()
        assert job.status.unsupported_paths == 1
        assert job.status.unsupported_values == 1
        assert [c.path for c in index.fields(limit=20).choices] == [
            ("items",),
            ("not_finite",),
            ("object",),
            ("object", "leaf"),
        ]
        assert "array traversal" in index.fields(prefix="items", limit=1).choices[0].guidance
        assert index.values(("items",), limit=1).choices == []
        assert index.values(("object", "leaf"), limit=1).choices[0].insertion == "null"
        assert "empty field" in index.guidance


def test_discovery_cancellation_never_publishes_partial_choices(tmp_path, monkeypatch):
    import threading

    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "cancel.jsonl"
    source.write_text('{"rare":"complete only"}')
    session = Investigation.open([source], storage_dir=tmp_path)
    real_open = Path.open
    entered, release = threading.Event(), threading.Event()

    class HeldRead:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, count):
            entered.set()
            assert release.wait(5)
            return self.stream.read(count)

    def held_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if path.name == "records.jsonl" and threading.current_thread().name.startswith(
            "slogger-discovery-"
        ):
            return HeldRead(stream)
        return stream

    try:
        monkeypatch.setattr(Path, "open", held_open)
        job = session.discover()
        assert entered.wait(5)
        assert job.status.phase == "building"
        assert job.status.processed_records == 0
        with pytest.raises(ToolError) as error:
            job.result()
        assert error.value.code == "discovery_not_ready"
        job.cancel()
        release.set()
        assert job.wait(5).phase == "canceled"
        assert job.diagnostics[0].code == "operation_canceled"
        assert session.resources.reserved_disk_bytes == 0
        assert session.page().records == [{"rare": "complete only"}]
        assert session.discover(background=False).result().fields(limit=1).choices[0].path == (
            "rare",
        )
    finally:
        release.set()
        session.close()


def test_failed_discovery_preserves_capture_and_reclaims_admission(tmp_path):
    import pytest

    from slogger.tools import ResourceLimits, ToolError

    source = tmp_path / "budget.jsonl"
    source.write_text('{"message":"still usable"}')
    with Investigation.open(
        [source], storage_dir=tmp_path, limits=ResourceLimits(disk_bytes=512 * 1024)
    ) as session:
        job = session.discover(background=False)
        assert job.status.phase == "failed"
        assert job.diagnostics[0].code == "resource_limit"
        assert session.resources.reserved_disk_bytes == 0
        assert session.page().records == [{"message": "still usable"}]
        with pytest.raises(ToolError):
            job.result()


def test_discovery_is_explicitly_complete_dataset_scoped_and_closed_with_owner(tmp_path):
    import threading

    import pytest

    from slogger.tools import ToolError

    source = tmp_path / "scoped.jsonl"
    source.write_text('{"key":"observed"}')
    session = Investigation.open([source], storage_dir=tmp_path)
    job = session.discover(background=False)
    index = job.result()
    canceled = threading.Event()
    canceled.set()
    with pytest.raises(ToolError) as error:
        index.complete(complete_filter("key == "), cancel_event=canceled)
    assert error.value.code == "operation_canceled"
    first = index.complete(complete_filter('key == "ob', generation=1))
    second = index.complete(complete_filter('key == "nothing', generation=2))
    assert first.scope == second.scope == job.scope
    assert (
        first.completion.apply(
            first.completion.choices[0],
            text=second.completion.text,
            cursor=second.completion.cursor,
            generation=2,
        )
        is None
    )
    assert second.completion.choices == ()
    session.close()
    with pytest.raises(ToolError) as error:
        index.fields(limit=1)
    assert error.value.code == "result_closed"
    with pytest.raises(ToolError) as error:
        session.discover()
    assert error.value.code == "session_closed"
    source.unlink()
    with Investigation.open([source], storage_dir=tmp_path) as incomplete:
        assert incomplete.status.phase == "failed"
        with pytest.raises(ToolError):
            incomplete.discover()
