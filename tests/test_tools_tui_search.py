"""Search controls and visible highlights in the native consumer."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


async def settle(pilot, condition):
    deadline = time.monotonic() + 8
    while not condition() and time.monotonic() < deadline:
        await pilot.pause(0.02)
    assert condition()


def test_live_search_does_not_move_cursor_and_enter_navigates_complete_matches(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    source = tmp_path / "records.jsonl"
    rows = [
        {"message": message}
        for message in ["ordinary", "needle needle", "ordinary", "NEEDLE", "needles"]
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 32)) as pilot:
                await pilot.press("f3", "down", "f7")
                editor = app.query_one("#record-search", Input)
                assert editor.has_focus
                editor.value = "needle"
                await pilot.pause()
                assert app.selected_ordinal == 1
                console = app.query_one(ConsoleViewport)
                strip = console.render_line(1)
                assert any(
                    segment.style
                    and segment.style.bgcolor
                    and segment.style.bgcolor.name == "yellow"
                    for segment in strip
                )
                await settle(pilot, lambda: app.search_result is not None)
                assert app.search_result is not None
                assert app.search_result.record_count == 3
                await pilot.press("enter")
                assert app.selected_ordinal == 3
                await pilot.press("enter")
                assert app.selected_ordinal == 4
                await pilot.press("enter")
                assert app.selected_ordinal == 1
                await pilot.press("shift+enter")
                assert app.selected_ordinal == 4
                await pilot.press("alt+w")
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 2,
                )
                await pilot.press("alt+c")
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 1,
                )
                assert app.selected_ordinal == 4
                editor.value = ""
                await pilot.pause()
                assert app.search_result is None and app.selected_ordinal == 4
                assert "Empty" in app.search_bar.status_text

    asyncio.run(scenario())


def test_decoded_highlights_options_mouse_and_filtered_scope_invalidation(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    source = tmp_path / "decoded.jsonl"
    rows = [
        {
            "id": 0,
            "message": "Straße\tneedle",
            "duration_ms": 456,
            "trace_id": "hidden",
            "payload": "line\nnext",
        },
        {"id": 1, "message": "needle", "duration_ms": 456},
        {"id": 2, "message": "needles"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))

    def highlighted(strip):
        return "".join(
            segment.text
            for segment in strip
            if segment.style and segment.style.bgcolor and segment.style.bgcolor.name == "yellow"
        )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(170, 34)) as pilot:
                await pilot.press("f7")
                editor = app.query_one("#record-search", Input)
                editor.value = "STRASSE"
                await pilot.pause()
                assert highlighted(app.query_one(ConsoleViewport).render_line(0)) == "Straße"
                editor.value = "needle"
                await pilot.pause()
                assert highlighted(app.query_one(ConsoleViewport).render_line(0)) == "needle"
                editor.value = "\\n"
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 0,
                )
                assert highlighted(app.query_one(ConsoleViewport).render_line(0)) == ""
                editor.value = "next"
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 1,
                )
                assert highlighted(app.query_one(ConsoleViewport).render_line(0)) == "next"
                editor.value = "hidden"
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 0,
                )
                await pilot.click("#search-scope")
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 1,
                )
                assert app.search_bar.full_record
                from slogger.tools.tui.inspector import JSONInspector

                inspector = app.query_one(JSONInspector)
                line = next(
                    index
                    for index, text in enumerate(inspector.document.splitlines())
                    if '"trace_id"' in text
                )
                assert highlighted(inspector.render_line(line)) == "hidden"
                await pilot.click("#search-scope")
                editor.value = "456"
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 0,
                )
                await pilot.press("f3", "d")
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 2,
                )
                await pilot.press("f7")
                editor.value = "needle"
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 3,
                )
                assert app.search_result is not None
                old_scope = app.search_result.scope.input_scope
                await pilot.press("f4")
                app.query_one("#main-filter", Input).value = "id <= 1"
                await pilot.press("enter")
                assert app.search_result is None
                assert "invalid" in app.search_bar.status_text
                await settle(
                    pilot, lambda: app.filtered_view is not None and app.search_result is not None
                )
                assert app.search_result is not None and app.filtered_view is not None
                assert app.search_result.record_count == 2
                assert app.search_result.scope.input_scope != old_scope
                assert app.search_result.scope.input_scope == app.filtered_view.view_scope
                await pilot.press("f7", "alt+w")
                await settle(
                    pilot,
                    lambda: app.search_result is not None and app.search_result.record_count == 2,
                )
                await pilot.press("f3", "b")
                assert not app.tree_mode and "Tree search unavailable" in app.tree_status

    asyncio.run(scenario())


def test_superseded_search_releases_old_work_and_shutdown_keeps_pin(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text('{"message":"old"}\n{"message":"new"}\n' * 200)
    opened = threading.Event()
    release = threading.Event()
    original_open = Path.open

    def delayed_capture_read(path, *args, **kwargs):
        if (
            path.name == "records.jsonl"
            and threading.current_thread() is not threading.main_thread()
            and not opened.is_set()
        ):
            opened.set()
            assert release.wait(5)
        return original_open(path, *args, **kwargs)

    async def scenario():
        with Investigation.open([source]) as session:
            monkeypatch.setattr(Path, "open", delayed_capture_read)
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 32)) as pilot:
                await pilot.press("p", "f7")
                pinned = app.pinned_identity
                editor = app.query_one("#record-search", Input)
                editor.value = "old"
                await settle(pilot, opened.is_set)
                previous = app.search.pending
                assert previous is not None
                editor.value = "new"
                await pilot.pause()
                assert app.search_result is None and app.selected_ordinal == 0
                release.set()
                await settle(pilot, lambda: app.search_result is not None)
                assert app.search_result is not None
                assert app.search_result.record_count == 200
                assert app.search_result.scope.options.text == "new"
                assert (
                    previous.done and previous.status.phase == "cancelled" and previous.view is None
                )
                assert app.inspected_identity == pinned
                await pilot.press("enter")
                assert app.selected_ordinal == 1 and app.inspected_identity == pinned
                editor.value = "old"
            release.set()
            monkeypatch.setattr(Path, "open", original_open)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
