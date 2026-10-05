import cProfile
import json
from pathlib import Path
from types import CodeType

import pytest

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


def test_durable_discovery_amortizes_catalog_publication_with_complete_choices(tmp_path):
    source = tmp_path / "amortized.jsonl"
    records, fields = 16, 16
    with source.open("w") as stream:
        for row in range(records):
            stream.write(json.dumps({f"key_{field:02}": row % 2 for field in range(fields)}) + "\n")
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        profile = cProfile.Profile()
        profile.enable()
        job = session.discover(background=False)
        profile.disable()
        try:
            assert job.status.phase == "complete"
            result = job.result()
            choices = result.fields(limit=100).choices
            assert len(choices) == fields
            assert all(choice.occurrences == records for choice in choices)
            for choice in choices:
                values = result.values(choice.path, limit=100).choices
                assert sorted((value.value, value.occurrences) for value in values) == [
                    (0, 8),
                    (1, 8),
                ]
            updates = sum(
                entry.callcount
                for entry in profile.getstats()
                if isinstance(entry.code, CodeType)
                and entry.code.co_filename.endswith("/investigation/cache.py")
                and entry.code.co_name == "update"
            )
            # An algorithmic batching guard, not a wall-clock latency requirement.
            assert updates <= records * 4 + 16
        finally:
            job.close()
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(0, 1).records[0]["key_00"] == 0


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("headroom_mb", [1, 2])
def test_adaptive_discovery_admission_preserves_prior_owner_and_view(
    tmp_path, durable, headroom_mb
):
    from dataclasses import replace

    source = tmp_path / "refused.jsonl"
    source.write_text(
        "".join(
            json.dumps({f"key_{field:02}": row % 2 for field in range(16)}) + "\n"
            for row in range(16)
        )
    )
    options = {"cache_dir": tmp_path / "cache"} if durable else {"storage_dir": tmp_path}
    with Investigation.open([source], **options) as session:
        from slogger.tools import parse_filter

        view = session.filter(parse_filter("exists(key_00)")).wait()
        assert view is not None
        identity = view.page(0, 1).identities
        try:
            session.configure_resources(
                limits=replace(
                    session.limits,
                    disk_bytes=session.resources.managed_disk_bytes + headroom_mb * 1024**2,
                )
            )
            job = session.discover(background=False)
            try:
                if headroom_mb == 1:
                    assert job.status.phase == "failed"
                    assert job.status.processed_records > 0
                    assert job.status.diagnostic is not None
                    assert job.status.diagnostic.code == "resource_limit"
                else:
                    assert job.status.phase == "complete"
                    choices = job.result().fields(limit=100).choices
                    assert len(choices) == 16
                    assert all(choice.occurrences == 16 for choice in choices)
                    for choice in choices:
                        assert sorted(
                            (value.value, value.occurrences)
                            for value in job.result().values(choice.path, limit=100).choices
                        ) == [(0, 8), (1, 8)]
            finally:
                job.close()
            assert session.resources.reserved_disk_bytes == 0
            assert session.status.complete and view.record_count == 16
            assert view.page(0, 1).identities == identity
        finally:
            view.close()


@pytest.mark.parametrize("durable", [False, True])
def test_canceling_queued_discovery_cleans_unpublished_work_and_keeps_view(
    tmp_path, monkeypatch, durable
):
    import threading

    from slogger.tools import ToolError, parse_filter

    source = tmp_path / "cancel-queued.jsonl"
    source.write_text(
        "".join(
            json.dumps({f"key_{field:02}": row % 2 for field in range(16)}) + "\n"
            for row in range(16)
        )
    )
    options = {"cache_dir": tmp_path / "cache"} if durable else {"storage_dir": tmp_path}
    with Investigation.open([source], **options) as session:
        view = session.filter(parse_filter("exists(key_00)")).wait()
        assert view is not None
        identity = view.page(0, 1).identities
        original_page = session.page
        entered, release = threading.Event(), threading.Event()

        def held_page(offset=0, limit=100):
            page = original_page(offset, limit)
            if offset == 3 and threading.current_thread().name.startswith("slogger-discovery-"):
                entered.set()
                assert release.wait(5)
            return page

        monkeypatch.setattr(session, "page", held_page)
        job = session.discover()
        try:
            assert entered.wait(5)
            assert session.page(0, 1).records[0]["key_00"] == 0
            with pytest.raises(ToolError):
                job.result()
            job.cancel()
            release.set()
            assert job.wait(5).phase == "canceled"
            assert session.resources.reserved_disk_bytes == 0
            assert view.record_count == 16 and view.page(0, 1).identities == identity
        finally:
            release.set()
            job.close()
            view.close()


def test_prefix_lookup_work_tracks_matching_values_not_the_field_population(tmp_path, monkeypatch):
    import sqlite3

    source = tmp_path / "prefix-range.jsonl"
    with source.open("w") as stream:
        for ordinal in range(2048):
            stream.write(json.dumps({"value": f"id-{ordinal:05d}"}) + "\n")
        for value in (
            "a%b",
            "a_b",
            'quote"tail',
            "a\0z",
            "é-tail",
            "😀-tail",
            "\ud7ffa",
            "\U0010ffffa",
            "\U0010ffffb",
        ):
            stream.write(json.dumps({"value": value}, ensure_ascii=False) + "\n")
        for value in ("common", "common", "common", False, 1, 1.0, None):
            stream.write(json.dumps({"value": value}) + "\n")
    real_connect = sqlite3.connect
    observing, ticks = [False], [0]

    def progress():
        if observing[0]:
            ticks[0] += 1
        return 0

    def observed_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        if Path(database).name.startswith("discovery-"):
            connection.set_progress_handler(progress, 100)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        job = session.discover(background=False)
        try:
            assert job.status.phase == "complete"
            index = job.result()
            for prefix, expected in (
                ('"a%', ["a%b"]),
                ('"a_', ["a_b"]),
                ('"quote\\"', ['quote"tail']),
                ('"a\\u0000', ["a\0z"]),
                ('"é', ["é-tail"]),
                ('"😀', ["😀-tail"]),
                ('"\ud7ff', ["\ud7ffa"]),
                ('"\U0010ffff', ["\U0010ffffa", "\U0010ffffb"]),
            ):
                page = index.values(("value",), prefix=prefix, limit=20)
                assert [choice.value for choice in page.choices] == expected
                assert page.has_more is False
            ranked = index.values(("value",), limit=1)
            assert [(choice.value, choice.occurrences) for choice in ranked.choices] == [
                ("common", 3)
            ]
            typed = index.values(("value",), prefix="1", limit=20)
            assert [choice.insertion for choice in typed.choices] == ["1", "1.0"]
            observing[0] = True
            page = index.values(("value",), prefix='"id-02047', limit=1)
            observing[0] = False
            assert [choice.value for choice in page.choices] == ["id-02047"]
            assert page.next_offset == 1 and not page.has_more
            # SQLite VM work guard: one matched value must not scan 2,048 others.
            # Counter instrumentation and this algorithmic bound are not a latency SLA.
            assert ticks[0] <= 32
        finally:
            observing[0] = False
            job.close()
        assert session.resources.reserved_disk_bytes == 0


def test_discovery_coalesces_occurrences_and_retains_every_unique_and_array_value(
    tmp_path, monkeypatch
):
    import sqlite3

    records, fields = 256, 16
    source = tmp_path / "weighted-observations.jsonl"
    with source.open("w") as stream:
        for ordinal in range(records):
            row: dict[str, object] = {f"key_{field:02}": ordinal % 2 for field in range(fields)}
            row.update(
                request_id=f"request-{ordinal:05d}",
                nested={"leaf": None if ordinal % 2 else False},
                items=[ordinal % 2, ordinal % 2, False, None],
            )
            row["nested.leaf"] = ordinal % 2
            stream.write(json.dumps(row) + "\n")
    writes = {"fields": 0}
    real_connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO fields"):
                writes["fields"] += 1
            return super().execute(sql, parameters)

    def observed_connect(database, *args, **kwargs):
        if Path(database).name.startswith("discovery-"):
            kwargs["factory"] = ObservedConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        job = session.discover(background=False)
        try:
            assert job.status.phase == "complete" and job.status.processed_records == records
            index = job.result()
            choices = index.fields(limit=100).choices
            assert len(choices) == fields + 5
            assert all(choice.occurrences == records for choice in choices)
            for field in range(fields):
                observed = index.values((f"key_{field:02}",), limit=10).choices
                assert [(choice.insertion, choice.occurrences) for choice in observed] == [
                    ("0", 128),
                    ("1", 128),
                ]
            arrays = index.values(("items",), source="array_element", limit=10).choices
            assert [(choice.insertion, choice.occurrences) for choice in arrays] == [
                ("0", 256),
                ("1", 256),
                ("false", 256),
                ("null", 256),
            ]
            assert [
                (choice.insertion, choice.occurrences)
                for choice in index.values(("nested", "leaf"), limit=10).choices
            ] == [("false", 128), ("null", 128)]
            assert [
                (choice.insertion, choice.occurrences)
                for choice in index.values(("nested.leaf",), limit=10).choices
            ] == [("0", 128), ("1", 128)]
            checked = offset = 0
            while checked < records:
                page = index.values(("request_id",), prefix='"request-', offset=offset, limit=31)
                for choice in page.choices:
                    assert choice.value == f"request-{checked:05d}" and choice.occurrences == 1
                    checked += 1
                assert page.next_offset == checked
                assert page.has_more == (checked < records)
                offset = page.next_offset
            # A deterministic work guard for repeated contributions; unique values
            # above are all retained. This bound does not constrain result size/time.
            assert writes["fields"] <= (fields + 5) * 4
        finally:
            job.close()
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(0, 1).records[0]["request_id"] == "request-00000"


def test_identical_discovery_observations_settle_at_progress_and_cancel_safely(
    tmp_path, monkeypatch
):
    import sqlite3
    import threading

    from slogger.tools import ToolError

    source = tmp_path / "identical-progress.jsonl"
    with source.open("w") as stream:
        for _ in range(512):
            stream.write('{"status":"same"}\n')
    entered, release = threading.Event(), threading.Event()
    writes = [0]
    real_connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO fields"):
                writes[0] += 1
            return super().execute(sql, parameters)

    def observed_connect(database, *args, **kwargs):
        if Path(database).name.startswith("discovery-"):
            kwargs["factory"] = ObservedConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        previous = session.page(0, 1).identities
        original_page = session.page

        def held_page(offset=0, limit=100):
            if offset == 128 and threading.current_thread().name.startswith("slogger-discovery-"):
                entered.set()
                assert release.wait(5)
            return original_page(offset, limit)

        monkeypatch.setattr(session, "page", held_page)
        job = session.discover()
        try:
            assert entered.wait(5)
            assert job.status.processed_records == 128 and job.status.phase == "building"
            # Even identical input settles weighted writes at bounded progress;
            # the complete dataset index is still unavailable until publication.
            assert writes[0] > 0
            with pytest.raises(ToolError):
                job.result()
            assert session.page(0, 1).identities == previous
            job.cancel()
            release.set()
            assert job.wait(5).phase == "canceled"
            assert session.resources.reserved_disk_bytes == 0
            assert session.status.complete and session.page(0, 1).identities == previous
        finally:
            job.cancel()
            release.set()
            job.close()


@pytest.mark.parametrize("durable", [False, True])
def test_discovery_small_working_budget_flushes_unique_values_and_admits_one_large_value(
    tmp_path, durable
):
    from slogger.tools import ResourceLimits

    source = tmp_path / "small-observations.jsonl"
    with source.open("w") as stream:
        for ordinal in range(384):
            row: dict[str, object] = {"request_id": f"request-{ordinal:06d}"}
            if ordinal % 4 < 3:
                row["sparse"] = (0, False, None)[ordinal % 4]
            if ordinal == 383:
                row["long"] = "L" * 12000
            stream.write(json.dumps(row) + "\n")
    options = {"cache_dir": tmp_path / "cache"} if durable else {"storage_dir": tmp_path}
    with Investigation.open(
        [source], limits=ResourceLimits(working_memory_bytes=128 * 1024), **options
    ) as session:
        assert session.status.complete
        job = session.discover(background=False)
        try:
            assert job.status.phase == "complete"
            index = job.result()
            assert {
                choice.path: choice.occurrences for choice in index.fields(limit=10).choices
            } == {("long",): 1, ("request_id",): 384, ("sparse",): 288}
            assert [
                (choice.insertion, choice.occurrences)
                for choice in index.values(("sparse",), limit=10).choices
            ] == [("0", 96), ("false", 96), ("null", 96)]
            assert index.values(("long",), limit=1).choices[0].value == "L" * 12000
            checked = 0
            while checked < 384:
                page = index.values(("request_id",), prefix='"request-', offset=checked, limit=31)
                for choice in page.choices:
                    assert choice.value == f"request-{checked:06d}" and choice.occurrences == 1
                    checked += 1
                assert page.next_offset == checked and page.has_more == (checked < 384)
        finally:
            job.close()
        assert session.resources.reserved_disk_bytes == 0
        assert session.page(0, 1).records == [{"request_id": "request-000000", "sparse": 0}]


def test_unsupported_array_elements_also_bound_discovery_write_progress(tmp_path, monkeypatch):
    import sqlite3
    import threading

    source = tmp_path / "unsupported-progress.jsonl"
    source.write_text('{"keep":"one","items":[' + ",".join("{}" for _ in range(8192)) + "]}\n")
    entered, release = threading.Event(), threading.Event()
    holder, first_write = [], []
    real_connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO fields") and not first_write:
                first_write.append(
                    (holder[0].status.processed_records, holder[0].status.unsupported_elements)
                )
            return super().execute(sql, parameters)

    def observed_connect(database, *args, **kwargs):
        if Path(database).name.startswith("discovery-"):
            kwargs["factory"] = ObservedConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
        original_page = session.page

        def held_page(offset=0, limit=100):
            if threading.current_thread().name.startswith("slogger-discovery-"):
                entered.set()
                assert release.wait(5)
            return original_page(offset, limit)

        monkeypatch.setattr(session, "page", held_page)
        job = session.discover()
        holder.append(job)
        try:
            assert entered.wait(5)
            release.set()
            assert job.wait(5).phase == "complete"
            index = job.result()
            assert job.status.unsupported_elements == 8192
            assert [
                (choice.path, choice.occurrences) for choice in index.fields(limit=10).choices
            ] == [(("items",), 1), (("keep",), 1)]
            assert index.values(("keep",), limit=1).choices[0].value == "one"
            assert index.values(("items",), source="array_element", limit=10).choices == []
            assert first_write and first_write[0][0] == 0 and first_write[0][1] < 8192
        finally:
            release.set()
            job.close()
        assert session.resources.reserved_disk_bytes == 0
