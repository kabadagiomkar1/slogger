"""Field counts and retained scope labels in the native investigation consumer."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


async def settle(pilot, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        await pilot.pause(0.02)
    assert condition()


def test_keyboard_field_editor_and_json_selection_open_exact_lower_counts(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "fields.jsonl"
    rows = [
        {"message": "first", "a.b": "literal", "a": {"b": "nested"}},
        {"message": "second", "a": {"b": None}},
        {"message": "last"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 36)) as pilot:
                await pilot.press("f5")
                editor = app.query_one("#aggregate-field", Input)
                assert editor.has_focus
                editor.value = '["a.b"]'
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                assert app.requested_field == ("a.b",)
                assert app.aggregate_result.page().records == [{"value": "literal", "count": 1}]
                assert app.query_one("#aggregate-pane").display
                await pilot.press("f2")
                inspector = app.query_one(JSONInspector)
                while inspector.selected_path != ("a", "b"):
                    await pilot.press("j")
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.aggregate_result is not None
                        and app.aggregate_result.scope.selected_field.path == ("a", "b")
                    ),
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"value": "nested", "count": 1},
                    {"value": None, "count": 1},
                ]
                assert app.requested_field == ("a", "b")
                assert app.selected_ordinal == 0

    asyncio.run(scenario())


def test_console_span_click_resolves_canonical_field_and_keyboard_target(tmp_path):
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    source = tmp_path / "span.jsonl"
    source.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-04T01:02:03Z",
                "level": "INFO",
                "logger": "app",
                "message": "done",
                "span": "canonical",
                "span_name": "fallback",
                "tenant": "north",
            }
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(160, 36)) as pilot:
                console = app.query_one(ConsoleViewport)
                text = console.render_line(0).text
                x = text.index("canonical") + 2
                await pilot.click("#console", offset=(x, 0))
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                assert app.requested_field == ("span",)
                assert app.aggregate_result.page().records == [{"value": "canonical", "count": 1}]
                await pilot.press("f3", "alt+right", "enter")
                await settle(pilot, lambda: app.requested_field == ("tenant",))
                assert app.selected_ordinal == 0

    asyncio.run(scenario())


def test_main_changes_follow_counts_and_failed_or_stale_requests_keep_honest_scope(
    tmp_path, monkeypatch
):
    import threading
    from pathlib import Path

    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    release = threading.Event()
    original_open = Path.open

    def delayed_open(path, *args, **kwargs):
        if (
            path.name == "records.jsonl"
            and threading.current_thread() is not threading.main_thread()
        ):
            release.wait(5)
        return original_open(path, *args, **kwargs)

    source = tmp_path / "follow.jsonl"
    rows = [{"n": i, "v": f"value-{i}", "bad": [], "message": "same"} for i in range(3000)]
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 38)) as pilot:
                await pilot.press("f5")
                field = app.query_one("#aggregate-field", Input)
                field.value = "message"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                previous = app.aggregate_result
                pane = app.query_one(AggregatePane)
                old_scope = pane.displayed_scope
                monkeypatch.setattr(Path, "open", delayed_open)
                field.value = "v"
                await pilot.press("enter")
                assert app.aggregate_result is previous
                assert pane.displayed_scope == old_scope and "Pending:" in pane.status_text
                field.value = "bad"
                await pilot.press("enter")
                release.set()
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert app.aggregate_result is previous
                assert pane.displayed_scope == old_scope and "scalar" in pane.status_text
                assert previous.page().records == [{"value": "same", "count": 3000}]
                field.value = "message"
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                await pilot.press("f4")
                app.query_one("#main-filter", Input).value = "n < 3"
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.filtered_view is not None
                        and app.pending_aggregate is None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.filtered_view.view_scope
                    ),
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": "same", "count": 3}]
                assert "n < 3" in pane.displayed_scope
                assert app.selected_ordinal == 0
                await pilot.press("f5")
                field.value = '["bad"]'
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert "message" in pane.displayed_scope and "n < 3" in pane.displayed_scope
                assert "scalar" in pane.status_text
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": "same", "count": 3}]

    asyncio.run(scenario())
