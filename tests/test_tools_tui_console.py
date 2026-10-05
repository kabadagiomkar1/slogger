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


def test_arrow_navigation_keeps_margin_and_scrolls_one_row_at_a_time(tmp_path):
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    source = tmp_path / "scroll.jsonl"
    source.write_text("\n".join(json.dumps({"message": f"row {i}"}) for i in range(100)))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 20)) as pilot:
                console = app.query_one(ConsoleViewport)
                height = console.size.height
                await pilot.press(*(["down"] * (height - 2)))
                console._window()
                assert console._top == (1, 0)
                assert (
                    next(i for i, row in enumerate(console._rows) if row[0] == console.selected)
                    == height - 3
                )
                previous_top = console._top
                await pilot.press("down")
                console._window()
                assert console._top == (previous_top[0] + 1, 0)
                assert (
                    next(i for i, row in enumerate(console._rows) if row[0] == console.selected)
                    == height - 3
                )
                await pilot.press(*(["up"] * (height - 4)))
                previous_top = console._top
                await pilot.press("up")
                assert console._top == (previous_top[0] - 1, 0)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["tree", "tree-before-layout", "aggregate"])
def test_other_results_scroll_with_cursor_context(tmp_path, mode):
    from slogger.tools.tui.aggregates import AggregateViewport
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    source = tmp_path / "results.jsonl"
    source.write_text(
        "\n".join(
            json.dumps({"message": f"row {i}", "category": str(i), "trace_id": "trace"})
            for i in range(100)
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 40)) as pilot:
                if mode.startswith("tree"):
                    if mode == "tree-before-layout":
                        # Publish a real tree before Textual's next layout frame.
                        # This deterministically exercises the state in which
                        # tree_mode is true but the viewport is still zero-sized.
                        app.show_record(0)
                        job = session.build_tree()
                        job.wait()
                        app._tree_result = job.result()
                        app._show_tree()
                        viewport = app.query_one(TreeViewport)
                        viewport._window()
                        assert viewport.size.height == 0 and not viewport._rows
                    else:
                        await pilot.press("b")
                        for _ in range(200):
                            if app.tree_mode:
                                break
                            await pilot.pause(0.02)
                    assert app.tree_mode
                    viewport = app.query_one(TreeViewport)
                else:
                    await pilot.press("a", *"category", "enter")
                    for _ in range(200):
                        if app.aggregate_result is not None:
                            break
                        await pilot.pause(0.02)
                    assert app.aggregate_result is not None
                    viewport = app.query_one(AggregateViewport)
                # Operation publication precedes Textual's layout/focus frame.
                # Rendering can trigger another layout pass for scrollbars.
                # Navigate after dimensions stay stable across a completed frame.
                for _ in range(200):
                    if viewport.size.width > 0 and viewport.size.height >= 4 and viewport.has_focus:
                        size = viewport.size
                        ready = False
                        if isinstance(viewport, TreeViewport):
                            viewport._window()
                            ready = bool(viewport._rows)
                        elif viewport.result is not None and viewport.result.record_count:
                            ready = True
                        if ready:
                            await pilot.pause()
                            if viewport.size == size and viewport.has_focus:
                                break
                    await pilot.pause(0.02)
                else:
                    pytest.fail(
                        f"Result viewport did not become ready: {mode}, "
                        f"size={viewport.size}, focus={viewport.has_focus}"
                    )
                height = viewport.size.height
                await pilot.press(*(["down"] * (height - 2)))
                if mode.startswith("tree"):
                    assert isinstance(viewport, TreeViewport)
                    viewport._window()
                    assert viewport._rows[0].ordinal == 1
                    assert (
                        next(
                            i
                            for i, row in enumerate(viewport._rows)
                            if row.key == viewport.focused_key
                        )
                        == height - 3
                    )
                    await pilot.press("down")
                    viewport._window()
                    assert viewport._rows[0].ordinal == 2
                else:
                    assert isinstance(viewport, AggregateViewport)
                    assert viewport.top == 1
                    assert viewport.selected - viewport.top == height - 3
                    await pilot.press("down")
                    assert viewport.top == 2
                    assert viewport.selected - viewport.top == height - 3

    asyncio.run(scenario())
