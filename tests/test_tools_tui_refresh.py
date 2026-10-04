"""Atomic owner replacement through the real native and headless seams."""

import asyncio
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


async def settled(pilot, condition, timeout=12):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "native operation did not settle"
        await pilot.pause(0.05)


def test_refresh_reapplies_main_search_and_preserves_newer_draft(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport

    source = tmp_path / "records.jsonl"
    source.write_text('{"level":"ERROR","message":"needle"}\n{"level":"INFO"}\n')

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                entry = app.main_filter.query_one(Input)
                entry.value = 'level == "ERROR"'
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.filtered_view is not None)
                search_entry = app.search_bar.query_one(Input)
                search_entry.value = "needle"
                await settled(pilot, lambda: app.search_result is not None)
                entry.value = 'level == "INFO"'  # newer unapplied draft
                source.write_text(source.read_text() + '{"level":"ERROR","message":"needle 2"}\n')
                await pilot.press("ctrl+r")
                await settled(pilot, lambda: app.session is not old)
                assert app.filtered_view is not None
                assert app.filtered_view.session is app.session
                assert app.filtered_view is not None
                assert app.filtered_view.record_count == 2
                assert app.query_one(ConsoleViewport).record_count == 2
                assert app.main_filter.applied_text == 'level == "ERROR"'
                assert entry.value == 'level == "INFO"'
                assert app.search_result is not None
                assert app.search_result.record_count == 2
                assert app.selected_record == {"level": "ERROR", "message": "needle"}
                assert app.selected_identity is not None
                assert app.selected_identity.owner_id == app.session.owner_id
        finally:
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_refresh_adopts_latest_scopes_pin_tree_and_preferences_during_capture(
    tmp_path, monkeypatch
):
    import builtins
    import threading
    from dataclasses import replace

    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "latest.jsonl"
    source.write_text('{"n":0,"region":"a"}\n{"n":1,"region":"a"}\n{"n":2,"region":"b"}\n')
    real_open = builtins.open
    entered, release = threading.Event(), threading.Event()

    class ScheduledRead:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, *args):
            entered.set()
            assert release.wait(15)
            return self.handle.read(*args)

    def scheduled_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        return (
            ScheduledRead(handle)
            if str(path) == str(source)
            and threading.current_thread().name.startswith("slogger-capture-")
            else handle
        )

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(140, 45)) as pilot:
                app.main_filter.query_one(Input).value = "n >= 1"
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.filtered_view is not None)
                app.action_pin()
                app.action_focus_aggregate_filter()
                await settled(pilot, lambda: app.detached_view is not None)
                app.aggregate_filter.query_one(Input).value = "n == 0"
                await pilot.press("ctrl+d", "enter")
                await settled(pilot, lambda: app.aggregate_filter.applied_text == "n == 0")
                app.request_aggregate(("n",), infer_metrics=False)
                await settled(pilot, lambda: app.aggregate_result is not None)
                app.action_tree()
                await settled(pilot, lambda: app.tree_mode)
                monkeypatch.setattr(builtins, "open", scheduled_open)
                source.write_text(
                    source.read_text() + '{"n":0,"region":"b"}\n{"n":2,"region":"c"}\n'
                )
                app.action_refresh()
                await settled(pilot, entered.is_set)
                assert app.aggregate_result is not None
                assert app.session is old and app.aggregate_result.page().records == [
                    {"value": 0, "count": 1}
                ]
                app.main_filter.query_one(Input).value = "n == 2"
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.main_filter.applied_text == "n == 2")
                grouping = app.query_one(AggregatePane).query_one("#aggregate-grouping", Input)
                grouping.value = "region"
                grouping.focus()
                await pilot.press("enter")
                await settled(
                    pilot,
                    lambda: (
                        app.aggregate_result is not None
                        and bool(app.aggregate_result.scope.grouping)
                    ),
                )
                app.aggregate_filter.query_one(
                    Input
                ).value = "n == 99"  # unsubmitted independent draft
                await settled(pilot, lambda: app.tree_mode)
                app.query_one(TreeViewport).action_fold_all()
                app.apply_preferences(
                    replace(
                        app.preferences,
                        theme="light",
                        console=replace(app.preferences.console, wrap=True),
                        inspector_percent=45,
                    )
                )
                release.set()
                await settled(pilot, lambda: app.session is not old)
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [
                    {"n": 2, "region": "b"},
                    {"n": 2, "region": "c"},
                ]
                assert app.detached_view is not None
                assert app.detached_view.page().records == [
                    {"n": 0, "region": "a"},
                    {"n": 0, "region": "b"},
                ]
                assert app.aggregate_filter.draft == "n == 99"
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"region": "a", "value": 0, "count": 1},
                    {"region": "b", "value": 0, "count": 1},
                ]
                assert app.pinned_identity is not None
                assert app.pinned_identity.owner_id == app.session.owner_id
                assert app.inspected_record == {"n": 1, "region": "a"}
                assert app.tree_mode and not app.query_one(TreeViewport).expanded_default
                assert app.query_one(ConsoleViewport).options.wrap
                assert not app.current_theme.dark and app.inspector_percent == 45
        finally:
            release.set()
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_required_aggregate_stage_failure_keeps_old_owner_and_complete_results(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "stage-error.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                app.request_aggregate(("n",))
                await settled(pilot, lambda: app.aggregate_result is not None)
                result = app.aggregate_result
                assert result is not None
                expected = result.page().records
                source.write_text(source.read_text() + '{"n":"incompatible"}\n')
                app.action_refresh()
                await settled(pilot, lambda: not app.refresh_controller.busy)
                assert "staging failed" in app.refresh_controller.status
                assert app.session is old and old.status.complete
                assert app.aggregate_result is result
                assert result is not None
                assert result.page().records == expected
                assert app.selected_record == {"n": 1}
                assert old.page().records == [{"n": 1}, {"n": 2}]
        finally:
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_pending_main_is_requeued_after_atomic_swap_and_old_ipc_cannot_publish(
    tmp_path, monkeypatch
):
    import threading
    from multiprocessing.connection import Connection

    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "ipc.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n{"n":3}\n')
    real_recv = Connection.recv
    entered, release = threading.Event(), threading.Event()

    def scheduled_recv(connection, *args):
        message = real_recv(connection, *args)
        if not entered.is_set():
            entered.set()
            assert release.wait(15)
        return message

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                entry = app.main_filter.query_one(Input)
                entry.value = "n == 1"
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.main_filter.applied_text == "n == 1")
                monkeypatch.setattr(Connection, "recv", scheduled_recv)
                entry.value = "n == 2"
                await pilot.press("f4", "enter")
                await settled(pilot, entered.is_set)
                entry.value = "n == 3"
                app.action_refresh()
                await settled(pilot, lambda: app.session is not old)
                await settled(pilot, lambda: app.main_filter.applied_text == "n == 2")
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [{"n": 2}]
                assert entry.value == "n == 3"
                assert app.filtered_view is not None
                assert app.filtered_view.session is app.session
                release.set()
                await settled(pilot, lambda: not app.refresh_controller.busy)
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [{"n": 2}]
                assert app.main_filter.applied_text == "n == 2"
                assert entry.value == "n == 3"
        finally:
            release.set()
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_refresh_preserves_semantic_node_focus_and_sparse_folds_after_id_shift(tmp_path):
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text('{"trace_id":"a","span_id":"a","message":"first"}\n')
    second.write_text('{"trace_id":"b","span_id":"b","message":"second"}\n')

    async def scenario():
        old = Investigation.open([first, second])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                app.action_tree()
                await settled(pilot, lambda: app.tree_mode)
                viewport = app.query_one(TreeViewport)
                tree = viewport.trace_tree
                assert tree is not None
                trace = next(row for row in tree.children().rows if row.trace_id == "b")
                span = next(row for row in tree.children(trace.key).rows if row.kind == "span")
                viewport.select(tree.children(span.key).rows[0])
                await pilot.pause()
                viewport.select(span)
                viewport.action_fold()
                identity = tree.node_identity(span.key)
                with first.open("a") as handle:
                    handle.write('{"trace_id":"new","span_id":"new"}\n')
                app.action_refresh()
                await settled(pilot, lambda: app.session is not old)
                current = viewport.trace_tree
                assert current is not None and viewport.focused_key is not None
                assert current.node_identity(viewport.focused_key) == identity
                assert (
                    viewport.focused_key != span.key
                )  # unrelated earlier node changed local SQLite ID
                assert "second" not in "".join(
                    viewport.render_line(line).text for line in range(viewport.size.height)
                )
        finally:
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_cancel_during_real_sqlite_staging_keeps_prior_dataset_usable(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "cancel.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')
    real_connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()

    def scheduled_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        if threading.current_thread().name.startswith("slogger-discovery-"):
            entered.set()
            assert release.wait(15)
        return connection

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                await settled(
                    pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                )
                before = old.resources.managed_disk_bytes
                monkeypatch.setattr(sqlite3, "connect", scheduled_connect)
                app.action_refresh()
                await settled(pilot, entered.is_set)
                assert app.session is old and old.page().records == [{"n": 1}, {"n": 2}]
                app.action_cancel_capture()
                release.set()
                await settled(pilot, lambda: not app.refresh_controller.busy)
                assert app.session is old and old.status.complete
                assert "retained" in app.refresh_controller.status
                assert old.resources.managed_disk_bytes == before
                await pilot.press("f3", "down")
                assert app.selected_record == {"n": 2}
        finally:
            release.set()
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_queued_native_events_from_reused_dataset_owner_are_rejected(tmp_path):
    from slogger.tools import parse_filter
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.filter_editor import FilterEditor
    from slogger.tools.tui.inspector import JSONInspector

    source = tmp_path / "reused.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')

    async def scenario():
        old = Investigation.open([source], cache_dir=tmp_path / "cache")
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                console = app.query_one(ConsoleViewport)
                old_scope, binding = console.view_scope, console.binding
                selected = ConsoleViewport.Selected(1, old.identity_at(1), old_scope)
                apply = FilterEditor.ApplyRequested(
                    app.main_filter, "n == 2", parse_filter("n == 2"), 1
                )
                fields = (
                    ConsoleViewport.FieldRequested(("stale",), old_scope, binding),
                    JSONInspector.FieldRequested(("stale",), binding),
                )
                completion = FilterEditor.DiscoveryReady(
                    100000, None, "stale completion error", binding=binding
                )
                app.action_refresh()
                await settled(pilot, lambda: app.session is not old)
                assert app.session.dataset_id == old.dataset_id
                assert console.view_scope == old_scope
                assert app.session.owner_id != old.owner_id
                app.post_message(selected)
                app.post_message(apply)
                for field in fields:
                    app.post_message(field)
                app.main_filter.post_message(completion)
                await pilot.pause(0.2)
                assert app.selected_ordinal == 0 and app.selected_record == {"n": 1}
                assert app.filtered_view is None and app.main_filter.applied_text == ""
                assert app.requested_field is None
                assert "stale completion error" not in app.main_filter.discovery_status
        finally:
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_latest_main_and_search_options_changed_during_sqlite_stage_are_restaged(
    tmp_path, monkeypatch
):
    import sqlite3
    import threading

    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "restage.jsonl"
    source.write_text('{"n":1,"message":"Needle"}\n{"n":2,"message":"Needle"}\n')
    real_connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()

    def scheduled_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        if (
            threading.current_thread().name.startswith("slogger-discovery-")
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(15)
        return connection

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                await settled(
                    pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                )
                entry = app.main_filter.query_one(Input)
                entry.value = "n == 1"
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.main_filter.applied_text == "n == 1")
                app.search_bar.query_one(Input).value = "Needle"
                monkeypatch.setattr(sqlite3, "connect", scheduled_connect)
                app.action_refresh()
                await settled(pilot, entered.is_set)
                assert app.session is old
                entry.value = "n == 2"
                await pilot.press("f4", "enter")
                await settled(pilot, lambda: app.main_filter.applied_text == "n == 2")
                app.search_bar.toggle("scope")
                app.search_bar.toggle("case")
                entry.value = "n == 99"
                release.set()
                await settled(pilot, lambda: app.session is not old)
                assert app.filtered_view is not None and app.search_result is not None
                assert app.filtered_view.page().records == [{"n": 2, "message": "Needle"}]
                assert app.search_result.page().records == [{"n": 2, "message": "Needle"}]
                assert app.search_result.scope.options.scope == "full"
                assert app.search_result.scope.options.case_sensitive
                assert entry.value == "n == 99"
        finally:
            release.set()
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_retired_owner_cleanup_failure_is_accounted_and_retry_keeps_new_browsing(
    tmp_path, monkeypatch
):
    import shutil

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "retired.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')
    real_rmtree = shutil.rmtree

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:

                def deny_retired(path, *args, **kwargs):
                    if path == old.storage.root:
                        raise OSError("controlled retired-owner deletion failure")
                    return real_rmtree(path, *args, **kwargs)

                monkeypatch.setattr(shutil, "rmtree", deny_retired)
                app.action_refresh()
                await settled(pilot, lambda: app.session is not old)
                await settled(pilot, lambda: "cleanup_failed" in app.refresh_controller.status)
                allocated = app.session.resources.managed_disk_bytes
                assert old.storage.root.exists()
                await pilot.press("f3", "down")
                assert app.selected_record == {"n": 2}
                monkeypatch.setattr(shutil, "rmtree", real_rmtree)
                app.action_refresh()  # retry accounted leftovers before a new capture
                await settled(pilot, lambda: not app.refresh_controller.busy)
                assert not old.storage.root.exists()
                assert app.session.resources.managed_disk_bytes < allocated
                assert app.session.page().records == [{"n": 1}, {"n": 2}]
                assert app.selected_record == {"n": 2}
        finally:
            monkeypatch.setattr(shutil, "rmtree", real_rmtree)
            app.session.close()
            old.close()

    asyncio.run(scenario())


def test_required_initial_record_read_failure_does_not_publish_replacement(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "empty-then-record.jsonl"
    source.write_text("")
    real_open = Path.open
    injected = threading.Event()

    def reject_initial_record(path, *args, **kwargs):
        if (
            threading.current_thread().name == "slogger-refresh-scopes"
            and Path(path).name == "records.jsonl"
        ):
            injected.set()
            raise OSError("controlled initial record read failure")
        return real_open(path, *args, **kwargs)

    async def scenario():
        old = Investigation.open([source])
        app = InvestigationApp(old)
        try:
            async with app.run_test(size=(130, 35)) as pilot:
                await settled(
                    pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                )
                source.write_text('{"n":1}\n')
                monkeypatch.setattr(Path, "open", reject_initial_record)
                app.action_refresh()
                await settled(pilot, lambda: not app.refresh_controller.busy)
                assert app.session is old
                assert injected.is_set()
                assert "controlled initial record read failure" in app.refresh_controller.status
                assert app.selected_identity is None and old.page().records == []
        finally:
            app.session.close()
            old.close()

    asyncio.run(scenario())
