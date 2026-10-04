"""Native folds, record identity, and pins through real Investigation captures."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_tree_switching_folds_mouse_and_navigation_preserve_record_and_pin(tmp_path):
    from slogger.tools.tui.app import InvestigationApp, JSONInspector
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "tree.jsonl"
    source.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in [
                {
                    "trace_id": "t",
                    "span_id": "root",
                    "event": "span.start",
                    "span": "parent",
                    "n": 0,
                },
                {
                    "trace_id": "t",
                    "span_id": "child",
                    "parent_span_id": "root",
                    "span": "child",
                    "n": 1,
                },
                {
                    "trace_id": "t",
                    "span_id": "child",
                    "parent_span_id": "root",
                    "span": "child",
                    "n": 2,
                },
            ]
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                await pilot.press("p", "down", "b")
                for _ in range(30):
                    await pilot.pause(0.02)
                    if app.tree_mode:
                        break
                assert app.tree_mode is True
                assert app.selected_ordinal == 1
                assert app.selected_identity is not None
                assert app.selected_identity.ordinal == 1
                assert app.pinned_identity is not None
                assert app.pinned_identity.ordinal == 0
                assert '"n": 0' in app.query_one(JSONInspector).document
                await pilot.press("down")
                assert app.selected_ordinal == 2
                await pilot.press("left", "space", "right")
                assert app.selected_ordinal == 2
                await pilot.press("shift+space", "shift+space", "b")
                assert app.tree_mode is False
                assert app.query_one(ConsoleViewport).selected == 2
                assert app.pinned_identity.ordinal == 0
                await pilot.press("b")
                await pilot.pause(0.2)
                assert app.tree_mode is True
                tree = app.query_one(TreeViewport)
                await pilot.click("#tree", offset=(1, 0))
                assert tree.focused_key is not None
                await pilot.press("f2", "f3")
                assert app.focused is tree

    asyncio.run(scenario())


def test_canceled_tree_cannot_replace_a_newer_tree_request(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "tree.jsonl"
    source.write_text('{"trace_id":"t","span_id":"s"}\n')
    connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()
    blocked = False

    def scheduled_connect(*args, **kwargs):
        nonlocal blocked
        if threading.current_thread().name.startswith("slogger-tree-") and not blocked:
            blocked = True
            entered.set()
            assert release.wait(5)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", scheduled_connect)

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                try:
                    await pilot.press("b")
                    assert entered.wait(5)
                    await pilot.press("escape")
                    assert app.tree_mode is False
                    assert "canceled" in app.tree_status
                    await pilot.press("b")
                    release.set()
                    for _ in range(30):
                        await pilot.pause(0.02)
                        if app.tree_mode:
                            break
                    assert app.tree_mode is True
                    viewport = app.query_one(TreeViewport)
                    assert viewport.trace_tree is not None
                    current_scope = viewport.trace_tree.scope
                    release.set()
                    await pilot.pause(0.2)
                    assert viewport.trace_tree.scope == current_scope
                    assert app.tree_mode is True
                finally:
                    release.set()

    asyncio.run(scenario())


def test_tree_gate_reports_incomplete_capture_and_keeps_console(blocked_source):
    from slogger.tools.tui.app import InvestigationApp

    source, entered, release = blocked_source

    async def scenario():
        with Investigation.open([source], background=True) as session:
            try:
                assert entered.wait(5)
                app = InvestigationApp(session)
                async with app.run_test(size=(70, 24)) as pilot:
                    await pilot.press("b")
                    assert app.tree_mode is False
                    assert "complete dataset" in app.tree_status
                    assert app.selected_identity is not None
                    assert any(
                        command.title == "Flat / tree"
                        for command in app.get_system_commands(app.screen)
                    )
            finally:
                release.set()

    asyncio.run(scenario())


def test_applying_main_filter_rebuilds_tree_with_the_new_membership(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "tree.jsonl"
    source.write_text('{"trace_id":"t","span_id":"s","n":0}\n{"n":1}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                await pilot.press("b")
                for _ in range(30):
                    await pilot.pause(0.02)
                    if app.tree_mode:
                        break
                assert app.tree_mode is True
                await pilot.press("f4", "n", "space", "=", "=", "space", "1", "enter")
                deadline = time.monotonic() + 5
                while (
                    app.filtered_view is None or app.selected_ordinal != 1
                ) and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None, str(
                    app.main_filter.query_one(".filter-status").render()
                )
                assert app.filtered_view.page().records == [{"n": 1}]
                assert app.selected_ordinal == 1
                assert app.selected_position == 0
                deadline = time.monotonic() + 5
                while not app.tree_mode and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.tree_mode
                assert "filtered" in app.tree_status
                assert app.selected_ordinal == 1

    asyncio.run(scenario())


def test_filtered_tree_search_reveals_folded_matches_and_preserves_flat_position(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "context.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "trace_id": "t",
                    "span_id": "root",
                    "event": "span.start",
                    "span": "excluded needle",
                    "n": 0,
                },
                {
                    "trace_id": "t",
                    "span_id": "child",
                    "parent_span_id": "root",
                    "message": "needle",
                    "n": 1,
                },
                {"message": "ordinary", "n": 2},
                {
                    "trace_id": "t",
                    "span_id": "child",
                    "parent_span_id": "root",
                    "message": "NEEDLE",
                    "n": 3,
                },
            ]
        )
    )

    async def settle(pilot, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.02)
        assert condition()

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f4")
                app.main_filter.query_one(Input).value = "n in [1, 3]"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f3", "b")
                await settle(pilot, lambda: app.tree_mode)
                tree = app.query_one(TreeViewport)
                await pilot.press("home")
                assert "Ancestor context" in tree.render_line(0).text or any(
                    "Ancestor context" in tree.render_line(y).text for y in range(tree.size.height)
                )
                await pilot.press("p", "shift+space", "f7")
                app.query_one("#record-search", Input).value = "needle"
                await settle(pilot, lambda: app.search_result is not None)
                assert app.search_result is not None and app.search_result.record_count == 2
                assert app.selected_ordinal == 1
                await pilot.press("enter")
                assert app.selected_ordinal == 3 and app.selected_position == 1
                assert tree.focused_key == -4
                assert any(
                    "yellow" == segment.style.bgcolor.name
                    for y in range(tree.size.height)
                    for segment in tree.render_line(y)
                    if segment.style and segment.style.bgcolor
                )
                await pilot.press("shift+enter")
                assert app.selected_ordinal == 1 and app.selected_position == 0
                assert app.pinned_identity is not None and app.pinned_identity.ordinal == 1
                await pilot.press("f3", "b")
                assert app.query_one(ConsoleViewport).selected == 0
                await pilot.press("b")
                await settle(pilot, lambda: app.tree_mode)
                assert app.selected_ordinal == 1

    asyncio.run(scenario())


def test_pending_tree_cannot_publish_previous_main_scope(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "stale.jsonl"
    source.write_text('{"trace_id":"t","span_id":"s","n":0}\n{"n":1}\n{"n":2}\n')
    connect = sqlite3.connect
    entered, release = threading.Event(), threading.Event()
    blocked = False

    def scheduled_connect(*args, **kwargs):
        nonlocal blocked
        if threading.current_thread().name.startswith("slogger-tree-") and not blocked:
            blocked = True
            entered.set()
            assert release.wait(8)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", scheduled_connect)

    async def settle(pilot, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.02)
        assert condition()

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                try:
                    await pilot.press("b")
                    assert entered.wait(5)
                    await pilot.press("f4")
                    app.main_filter.query_one(Input).value = "n == 1"
                    await pilot.press("enter")
                    await settle(pilot, lambda: app.filtered_view is not None)
                    app.main_filter.query_one(Input).value = "n == 2"
                    await pilot.press("enter")
                    await settle(pilot, lambda: app.main_filter.applied_text == "n == 2")
                    assert not app.tree_mode
                    assert app.selected_ordinal == 2
                    release.set()
                    await settle(pilot, lambda: app.tree_mode)
                    tree = app.query_one(TreeViewport).trace_tree
                    assert tree is not None and app.filtered_view is not None
                    assert tree.scope.input_scope == app.filtered_view.view_scope
                    assert [row.ordinal for row in tree.children().rows] == [2]
                    assert app.selected_ordinal == 2 and app.selected_position == 0
                finally:
                    release.set()

    asyncio.run(scenario())


def test_search_reveals_a_deep_path_beyond_sparse_fold_capacity(tmp_path):
    from textual.widgets import Input

    from slogger.tools import ResourceLimits
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "deep-reveal.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "trace_id": "t",
                    "span_id": str(n),
                    "parent_span_id": str(n + 1),
                    "n": n,
                    "message": "target" if n == 0 else "ordinary",
                }
                if n < 599
                else {"trace_id": "t", "span_id": str(n), "event": "span.start", "n": n}
            )
            for n in range(600)
        )
    )

    async def settle(pilot, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.02)
        assert condition()

    async def scenario():
        with Investigation.open(
            [source], limits=ResourceLimits(working_memory_bytes=128 * 1024)
        ) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.press("f4")
                app.main_filter.query_one(Input).value = "n == 0"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f3", "b")
                await settle(pilot, lambda: app.tree_mode)
                await pilot.press("shift+space", "f7")
                app.query_one("#record-search", Input).value = "target"
                await settle(pilot, lambda: app.search_result is not None)
                await pilot.press("enter", "f3")
                tree = app.query_one(TreeViewport)
                assert tree.focused_key == -1
                await pilot.press("left", "right")
                assert tree.focused_key == -1
                assert app.selected_ordinal == 0
                assert any("[601]" in tree.render_line(y).text for y in range(tree.size.height))

    asyncio.run(scenario())
