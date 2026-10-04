"""Native folds, record identity, and pins through real Investigation captures."""

import asyncio
import json

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


def test_applying_main_filter_leaves_tree_and_honestly_gates_filtered_tree(tmp_path):
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
                assert app.tree_mode is False
                for _ in range(50):
                    await pilot.pause(0.02)
                    if app.filtered_view is not None:
                        break
                assert app.selected_ordinal == 1
                assert app.selected_position == 0
                await pilot.press("f3", "b")
                assert app.tree_mode is False
                assert "applied filter" in app.tree_status
                assert app.selected_ordinal == 1

    asyncio.run(scenario())
