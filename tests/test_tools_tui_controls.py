"""Source controls stay visible data at native display and interaction boundaries."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


async def settle(pilot, condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        await pilot.pause(0.02)
        if condition():
            return
    assert condition(), "Requested native result was not published"


def highlighted(strip):
    return "".join(
        segment.text
        for segment in strip
        if segment.style and segment.style.bgcolor and segment.style.bgcolor.name == "yellow"
    )


def test_source_controls_are_visible_without_commands_or_shifted_search(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.inspector import JSONInspector

    row = {
        "level": "INFO",
        "logger": "demo",
        "message": "before\x1b[2J\x07\x08\r\x7f\x9bafter Straße\tneedle\nnext",
    }
    source = tmp_path / "controls.jsonl"
    source.write_text(json.dumps(row) + "\n")
    copied = []

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session, clipboard_writer=copied.append)
            async with app.run_test(size=(180, 34)) as pilot:
                console = app.query_one(ConsoleViewport)
                strip = console.render_line(0)
                assert "\x1b[2J" not in strip.render(app.console)
                assert "before\\u001b[2J\\u0007\\u0008\\u000d\\u007f\\u009bafter" in strip.text
                await pilot.press("f7")
                search = app.query_one("#record-search", Input)
                search.value = "after"
                await pilot.pause()
                assert highlighted(console.render_line(0)) == "after"
                search.value = "STRASSE"
                await pilot.pause()
                assert highlighted(console.render_line(0)) == "Straße"
                search.value = "needle"
                await pilot.pause()
                assert highlighted(console.render_line(0)) == "needle"
                assert app.inspected_record == row
                assert json.loads(app.query_one(JSONInspector).document) == row
                await pilot.press("f2", "c")
                assert json.loads(copied[-1]) == row
                assert session.page().records == [row]

    asyncio.run(scenario())


def test_control_keys_values_tree_and_group_labels_keep_exact_original_data(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregateViewport
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport
    from slogger.tools.tui.inspector import JSONInspector
    from slogger.tools.tui.tree import TreeViewport

    key = "custom\x1b[2J\x85"
    value = "start\x9bTAIL"
    alias = "area\x1b[2J"
    row = {
        "message": "original",
        "trace_id": "trace\x1b[2J",
        "span_id": "s",
        "span": "span\x1b[2J",
        key: value,
    }
    source = tmp_path / "labels.jsonl"
    source.write_text(json.dumps(row, ensure_ascii=False) + "\n")

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(200, 40)) as pilot:
                console = app.query_one(ConsoleViewport)
                strip = console.render_line(0)
                assert "\x9b" not in strip.render(app.console)
                assert '"start\\u009bTAIL"' in strip.text
                x = strip.text.index("custom") + 2
                await pilot.click("#console", offset=(x, 0))
                assert console.selected_field == (key,)
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": value, "count": 1}]
                results = app.query_one(AggregateViewport)
                assert "\x9b" not in results.render_line(0).render(app.console)
                app.query_one("#aggregate-grouping", Input).value = "span as " + json.dumps(alias)
                await pilot.press("f9", "tab", "enter")
                await settle(
                    pilot,
                    lambda: (
                        app.aggregate_result is not None
                        and app.aggregate_result.scope.grouping != ()
                    ),
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result is not None
                assert alias in app.aggregate_result.page().records[0]
                assert "\x1b[2J" not in results.render_line(0).render(app.console)
                assert "area\\u001b[2J" in results.render_line(0).text
                inspector = app.query_one(JSONInspector)
                assert json.loads(inspector.document) == row
                target = next(target for target in inspector.key_targets if target.path == (key,))
                assert "\\u0085" in inspector.render_line(target.line).text
                await pilot.press("f7")
                app.query_one("#record-search", Input).value = "TAIL"
                await pilot.pause()
                assert highlighted(console.render_line(0)) == "TAIL"
                await pilot.press("f3", "b")
                await settle(pilot, lambda: app.tree_mode)
                tree = app.query_one(TreeViewport)
                for y in range(tree.size.height):
                    assert "\x1b[2J" not in tree.render_line(y).render(app.console)
                assert session.page().records == [row]
                assert app.inspected_record == row

    asyncio.run(scenario())


def test_dataset_insertions_escape_controls_and_keep_unicode_and_exact_predicates(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    key, value = "literal\x85", "Straße\x9bTAIL"
    row = {key: value}
    source = tmp_path / "insertions.jsonl"
    source.write_text(json.dumps(row, ensure_ascii=False) + "\n")

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(140, 34)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = '["literal'
                entry.cursor_position = len(entry.value)
                await settle(
                    pilot,
                    lambda: any(
                        choice.label.startswith('["literal')
                        for choice in app.main_filter.completion.choices
                    ),
                )
                await pilot.press("tab")
                assert entry.value == '["literal\\u0085"]'
                entry.value += ' == "Straße'
                entry.cursor_position = len(entry.value)
                await settle(
                    pilot,
                    lambda: any(
                        "TAIL" in choice.label for choice in app.main_filter.completion.choices
                    ),
                )
                await pilot.press("tab")
                assert "Straße\\u009bTAIL" in entry.value
                assert "\x9b" not in entry.render_line(0).render(app.console)
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [row]
                await pilot.press("ctrl+d")
                await settle(pilot, lambda: app.detached_view is not None)
                assert app.aggregate_filter.query_one(Input).value == entry.value
                assert app.detached_view is not None
                assert app.detached_view.page().records == [row]
                assert session.page().records == [row]

    asyncio.run(scenario())


def test_literal_control_draft_renders_safely_without_changing_cursor_or_click_indices(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "input.jsonl"
    source.write_text('{"message":"original"}\n')
    draft = "a\x1b[2J\x9bZ"

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = draft
                entry.cursor_position = len(draft)
                await pilot.pause()
                assert "\x1b[2J" not in entry.render_line(0).render(app.console)
                assert "\x9b" not in entry.render_line(0).render(app.console)
                assert "a␛[2J�Z" in entry.render_line(0).text
                assert entry.value == draft
                await pilot.press("home", "right", "right")
                assert entry.cursor_position == 2
                assert entry.cursor_screen_offset.x - entry.content_region.x == 2
                await pilot.click(
                    "#main-filter",
                    offset=(
                        entry.content_region.x - entry.region.x + 2,
                        entry.content_region.y - entry.region.y,
                    ),
                )
                assert entry.cursor_position == 2
                await pilot.press("delete")
                assert entry.value == "a\x1b2J\x9bZ"
                assert app.selected_record == {"message": "original"}

    asyncio.run(scenario())


def test_modified_wheel_pans_tree_and_groups_without_vertical_navigation(tmp_path):
    from textual import events
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregateViewport
    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.tree import TreeViewport

    row = {"message": "wide " * 80, "trace_id": "t", "span_id": "s", "span": "label " * 80}
    source = tmp_path / "wheel.jsonl"
    source.write_text(json.dumps(row) + "\n" + json.dumps({"message": "second"}) + "\n")

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(90, 30)) as pilot:
                await pilot.press("b")
                await settle(pilot, lambda: app.tree_mode)
                tree = app.query_one(TreeViewport)
                before = tree.render_line(0).text
                key = tree.focused_key
                tree.post_message(events.MouseScrollDown(tree, 3, 2, 0, 0, 0, True, False, False))
                await pilot.pause()
                assert tree.scroll_offset.x > 0
                assert tree.focused_key == key
                assert tree.render_line(0).text != before
                tree.post_message(events.MouseScrollUp(tree, 3, 2, 0, 0, 0, False, False, True))
                await pilot.pause()
                assert tree.scroll_offset.x == 0
                assert tree.focused_key == key
                assert tree.render_line(0).text == before
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).value = "message"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                await pilot.press("f6")
                groups = app.query_one(AggregateViewport)
                before = groups.render_line(0).text
                groups.post_message(
                    events.MouseScrollDown(groups, 3, 0, 0, 0, 0, True, False, False)
                )
                await pilot.pause()
                assert groups.scroll_offset.x > 0
                assert groups.selected == 0
                assert groups.render_line(0).text != before
                groups.post_message(
                    events.MouseScrollDown(groups, 3, 0, 0, 0, 0, False, False, False)
                )
                await pilot.pause()
                assert groups.selected == 1

    asyncio.run(scenario())


def test_equals_completion_and_typed_values_work_in_main_and_independent_editors(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    rows = [{"flag": False, "nullable": None}, {"flag": 0, "nullable": False}]
    source = tmp_path / "equals-editors.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 32)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = "flag "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert "=" in {choice.label for choice in app.main_filter.completion.choices}
                await pilot.press("down", "tab")
                assert entry.value == "flag = "
                entry.value += "f"
                entry.cursor_position = len(entry.value)
                await settle(
                    pilot,
                    lambda: any(
                        choice.label == "false" for choice in app.main_filter.completion.choices
                    ),
                )
                await pilot.press("tab", "enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [rows[0]]
                applied = app.main_filter.applied_text
                await pilot.press("ctrl+d")
                await settle(pilot, lambda: app.detached_view is not None)
                scope = app.query_one("#aggregate-filter", Input)
                scope.value = "nullable = n"
                scope.cursor_position = len(scope.value)
                await settle(
                    pilot,
                    lambda: any(
                        choice.label == "null" for choice in app.aggregate_filter.completion.choices
                    ),
                )
                await pilot.press("tab", "enter")
                await settle(
                    pilot, lambda: app.aggregate_filter.applied_text.strip() == "nullable = null"
                )
                assert app.detached_view is not None
                assert app.detached_view.page().records == [rows[0]]
                assert app.main_filter.applied_text == applied

    asyncio.run(scenario())


def test_origin_and_applied_scope_labels_escape_controls_without_rewriting_state(tmp_path):
    from textual.widgets import Input, Static

    from slogger.tools.tui.app import InvestigationApp

    row = {"field": "start\x9bTAIL"}
    source = tmp_path / "named\x1b[2J.jsonl"
    source.write_text(json.dumps(row) + "\n")
    expression = 'field == "start\x9bTAIL"'

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(150, 34)) as pilot:
                origin = app.query_one("#origin", Static)
                assert "\x1b[2J" not in origin.render_line(0).render(app.console)
                assert "named\\u001b[2J.jsonl" in origin.render_line(0).text
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = expression
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                status = app.main_filter.query_one(".filter-status", Static)
                assert "\x9b" not in status.render_line(0).render(app.console)
                assert app.main_filter.applied_text == expression
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).value = "field"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                label = app.query_one("#aggregate-label", Static)
                assert "\x9b" not in label.render_line(0).render(app.console)
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [row]
                assert app.selected_origin is not None
                assert app.selected_origin.source == str(source)

    asyncio.run(scenario())


def test_control_expansion_keeps_search_highlights_after_panning_and_wrapping(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.console import ConsoleViewport

    row = {"message": "prefix\x1b[2J" + " X" * 100 + "needle"}
    source = tmp_path / "pan-search.jsonl"
    source.write_text(json.dumps(row) + "\n")

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(90, 28)) as pilot:
                await pilot.press("f7")
                app.query_one("#record-search", Input).value = "needle"
                await settle(pilot, lambda: app.search_result is not None)
                console = app.query_one(ConsoleViewport)
                await pilot.press("f3", "shift+right", "shift+right", "shift+right", "shift+right")
                assert "needle" in console.render_line(0).text
                assert highlighted(console.render_line(0)) == "needle"
                await pilot.press("ctrl+left", "w")
                assert "needle" == "".join(
                    highlighted(console.render_line(y)) for y in range(console.size.height)
                )
                app.query_one("#record-search", Input).value = "\\u001b"
                await settle(
                    pilot,
                    lambda: (
                        app.search_result is not None
                        and (app.search_result.scope.options.text == "\\u001b")
                    ),
                )
                assert app.search_result is not None
                assert app.search_result.record_count == 0
                assert app.selected_record == row

    asyncio.run(scenario())


def test_launch_diagnostic_controls_are_visible_and_dependency_safe(tmp_path, capsys):
    from slogger.tools.tui import main

    preferences = tmp_path / "bad\x1b[2J\x9b.json"
    preferences.write_text("{invalid}")
    assert main(["--preferences-file", str(preferences), str(tmp_path / "input.jsonl")]) == 2
    error = capsys.readouterr().err
    assert "preferences_invalid" in error
    assert "\x1b[2J" not in error
    assert "\x9b" not in error
    assert "bad\\u001b[2J\\u009b.json" in error
