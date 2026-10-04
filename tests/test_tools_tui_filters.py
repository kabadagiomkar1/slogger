"""Native Main filter interaction over real complete investigation inputs."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_enter_applies_complete_filter_with_distinct_position_and_identity(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector

    source = tmp_path / "records.jsonl"
    rows = [{"n": i, "message": f"record {i}"} for i in range(300)]
    source.write_text("invalid\n" + "\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 28)) as pilot:
                await pilot.press("f4")
                editor = app.query_one("#main-filter", Input)
                assert editor.has_focus
                editor.value = "n >= 290"
                await pilot.press("enter")
                deadline = time.monotonic() + 5
                while app.filtered_view is None and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None
                assert app.filtered_view.record_count == 10
                assert app.selected_position == 0 and app.selected_ordinal == 290
                assert app.selected_identity is not None
                assert app.selected_identity.ordinal == 290
                assert app.selected_origin is not None
                assert app.selected_origin.position == 292
                assert app.query_one(JSONInspector).document.find('"n": 290') >= 0
                await pilot.press("f3", "end")
                assert app.selected_position == 9 and app.selected_ordinal == 299
                assert app.query_one(ConsoleViewport).render_line(0).text.find("record 299") >= 0
                await pilot.press("f4")
                editor.value = "n > true"
                await pilot.press("enter")
                assert app.filtered_view.record_count == 10
                assert app.main_filter.applied_text == "n >= 290"
                assert "ordering operands" in app.main_filter.status_text

    asyncio.run(scenario())


def test_cancel_and_supersede_keep_applied_scope_and_pin_while_regex_runs(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "regex.jsonl"
    rows = [{"message": "safe", "n": i} for i in range(128)]
    rows.append({"message": "a" * 5000 + "!", "n": 128})
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def settle(pilot, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.01)
        assert condition()

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 28)) as pilot:
                await pilot.press("p", "f4")
                pinned = app.pinned_identity
                editor = app.query_one("#main-filter", Input)
                editor.value = 'message == "safe"'
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                previous = app.filtered_view
                editor.value = 'message matches "(a+)+$"'
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.pending_filter is not None
                        and app.pending_filter.status.processed_records == 128
                    ),
                )
                assert "Pending:" in app.main_filter.status_text
                assert app.main_filter.applied_text == 'message == "safe"'
                await pilot.press("f3", "down", "escape")
                await settle(pilot, lambda: app.pending_filter is None)
                assert app.filtered_view is previous
                assert app.selected_ordinal == 1 and app.inspected_identity == pinned
                assert "Canceled" in app.main_filter.status_text
                await pilot.press("f4")
                editor.value = 'message matches "(a+)+$"'
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.pending_filter is not None
                        and app.pending_filter.status.processed_records == 128
                    ),
                )
                editor.value = "n >= 125"
                await pilot.press("enter")
                editor.value = "n >= 999"
                await settle(
                    pilot,
                    lambda: (
                        app.pending_filter is None and app.main_filter.applied_text == "n >= 125"
                    ),
                )
                assert app.filtered_view is not None and app.filtered_view.record_count == 4
                assert app.main_filter.draft == "n >= 999"
                assert "draft changed" in app.main_filter.status_text
                assert app.selected_position == 0 and app.selected_ordinal == 125
                assert app.pinned_identity == pinned and app.inspected_identity == pinned
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.pending_filter is None and app.main_filter.applied_text == "n >= 999"
                    ),
                )
                assert app.filtered_view.record_count == 0
                assert app.selected_identity is None and app.inspected_identity == pinned
                assert session.resources.reserved_disk_bytes == 0

    asyncio.run(scenario())
