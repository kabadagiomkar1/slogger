"""Complete console navigation through real captured input and native controls."""

import asyncio
import json

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_wrapped_lines_keep_record_selection_and_page_to_the_complete_tail(tmp_path):
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    records = [
        {"message": "START " + "continuation " * 120 + "TAIL"},
        {"message": "SECOND"},
    ]
    source = tmp_path / "wrapped.jsonl"
    source.write_text("\n".join(json.dumps(record) for record in records))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(90, 20)) as pilot:
                console = app.query_one("#console", ConsoleViewport)
                await pilot.press("w")
                assert "SECOND" not in console.render_line(1).text
                await pilot.click("#console", offset=(3, 5))
                assert app.selected_ordinal == 0
                assert app.inspected_record == records[0]
                visible = ""
                for _ in range(12):
                    visible += "".join(
                        console.render_line(y).text for y in range(console.size.height)
                    )
                    if "TAIL" in visible:
                        break
                    await pilot.press("pagedown")
                assert "TAIL" in visible
                assert app.selected_ordinal == 0
                await pilot.press("down")
                assert app.selected_ordinal == 1
                identity = app.selected_identity
                await pilot.resize_terminal(60, 20)
                assert app.selected_identity == identity
                assert app.inspected_record == records[1]
                assert session.page(0, 1).records == [records[0]]

    asyncio.run(scenario())


def test_timestamp_and_duration_controls_preserve_full_fields_and_column_alignment(tmp_path):
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp
    from slogger.tools.tui.presentation import console_fields

    records = [
        {
            "timestamp": "2026-10-04T12:34:56.789+05:30",
            "level": "INFO",
            "logger": "short",
            "message": "FIRST",
            "duration_ms": 0,
            "custom": "complete",
        },
        {
            "timestamp": "2026-10-05T01:02:03.456+05:30",
            "level": "WARNING",
            "logger": "a.logger.longer.than.the.column",
            "message": "SECOND",
            "duration_ms": 12.5,
        },
    ]
    source = tmp_path / "options.jsonl"
    source.write_text("\n".join(json.dumps(record) for record in records))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(220, 20)) as pilot:
                console = app.query_one("#console", ConsoleViewport)
                first = console.render_line(0).text
                assert "07:04:56.789" in first
                assert "duration_ms" not in first and "2026-10-04" not in first
                identity = app.selected_identity
                await pilot.press("t")
                assert "2026-10-04 07:04:56.789" in console.render_line(0).text
                await pilot.press("t", "d")
                first = console.render_line(0).text
                second = console.render_line(1).text
                assert "2026-10-04T12:34:56.789+05:30" in first
                assert "duration_ms=0" in first
                assert first.index("FIRST") == second.index("SECOND")
                assert app.selected_identity == identity
                assert (
                    dict(console_fields(records[0], console.options))["timestamp"]
                    == records[0]["timestamp"]
                )
                assert (
                    dict(console_fields(records[1], console.options))["logger"]
                    == records[1]["logger"]
                )
                assert session.page(0, 2).records == records

    asyncio.run(scenario())


def test_keyboard_pan_reaches_wide_custom_field_and_mouse_scroll_maps_wrapped_lines(tmp_path):
    from textual import events

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    records = [{"message": "FIRST", "custom": "🙂" * 200 + "FIELD-TAIL"}, {"message": "SECOND"}]
    source = tmp_path / "wide.jsonl"
    source.write_text("\n".join(json.dumps(record) for record in records))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(90, 20)) as pilot:
                console = app.query_one("#console", ConsoleViewport)
                identity = app.selected_identity
                await pilot.press(*(["shift+right"] * 12))
                assert "FIELD-TAIL" in console.render_line(0).text
                assert app.selected_identity == identity
                await pilot.press("ctrl+left")
                assert "FIRST" in console.render_line(0).text
                await pilot.press("w")
                before = console.render_line(0).text
                console.post_message(
                    events.MouseScrollDown(console, 3, 2, 0, 0, 0, False, False, False)
                )
                await pilot.pause()
                assert console.render_line(0).text != before
                assert app.selected_identity == identity
                await pilot.click("#console", offset=(3, 2))
                assert app.selected_ordinal == 0
                assert app.inspected_record == records[0]

    asyncio.run(scenario())
