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
                assert console.selected_field == ("span",)
                await pilot.press("enter")
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
                field.value = "unapplied_field_draft"
                await pilot.press("f3", "ctrl+a", "f4")
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
                assert field.value == "unapplied_field_draft"
                assert pane.display is False
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


def test_count_paging_reaches_last_group_without_changing_record_selection(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregateViewport
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "pages.jsonl"
    source.write_text(
        "\n".join(json.dumps({"v": f"group-{i:03d}", "message": "row"}) for i in range(137))
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.press("p", "f5")
                app.query_one("#aggregate-field", Input).value = "v"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None and app.aggregate_result.record_count == 137
                original = app.selected_identity
                pinned = app.pinned_identity
                await pilot.press("f2", "tab")
                assert app.query_one(AggregateViewport).has_focus
                await pilot.press("tab")
                assert app.query_one("#console").has_focus
                await pilot.press("f6", "pagedown", "end")
                viewport = app.query_one(AggregateViewport)
                assert viewport.selected == 136
                assert "group-136" in viewport.render_line(0).text
                await pilot.press("home")
                assert "group-000" in viewport.render_line(0).text
                await pilot.resize_terminal(65, 35)
                assert app.selected_identity == original and app.pinned_identity == pinned
                await pilot.press("f3")
                assert app.selected_identity == original

    asyncio.run(scenario())


def test_numeric_selection_defaults_and_editable_metrics_preserve_main_following(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "numeric-ui.jsonl"
    source.write_text('{"cost":2,"keep":true}\n{"cost":4,"keep":false}\n{"cost":null,"keep":true}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(125, 36)) as pilot:
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).value = "cost"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"count": 3, "sum": 6, "mean": 3.0, "min": 2, "max": 4}
                ]
                await pilot.press("f9")
                metrics = app.query_one("#aggregate-metrics", Input)
                assert metrics.has_focus
                metrics.value = "count, sum"
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"count": 3, "sum": 6}]
                await pilot.press("f4")
                app.query_one("#main-filter", Input).value = "keep == true"
                await pilot.press("enter")
                await settle(
                    pilot, lambda: app.filtered_view is not None and app.pending_aggregate is None
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"count": 2, "sum": 2}]
                assert "count, sum" in app.query_one(AggregatePane).displayed_scope
                await pilot.press("f9")
                metrics.value = "median"
                await pilot.press("enter")
                assert "metrics" in app.query_one(AggregatePane).status_text.lower()
                assert app.aggregate_result.page().records == [{"count": 2, "sum": 2}]

    asyncio.run(scenario())


def test_superseded_numeric_replay_keeps_prior_metrics_scope_and_newer_draft(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "numeric-stale.jsonl"
    source.write_text('{"v":2}\n{"v":4}')
    entered, release = threading.Event(), threading.Event()
    original_open = Path.open
    delayed = False

    def pause_first_replay(path, mode="r", *args, **kwargs):
        nonlocal delayed
        if path.name.startswith("numeric-") and mode == "rb" and not delayed:
            delayed = True
            entered.set()
            assert release.wait(10)
        return original_open(path, mode, *args, **kwargs)

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).value = "v"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                previous = app.aggregate_result
                assert previous is not None
                pane = app.query_one(AggregatePane)
                previous_scope = pane.displayed_scope
                monkeypatch.setattr(Path, "open", pause_first_replay)
                await pilot.press("f9")
                metrics = app.query_one("#aggregate-metrics", Input)
                metrics.value = "mean"
                await pilot.press("enter")
                try:
                    await settle(pilot, entered.is_set)
                    assert app.aggregate_result is previous
                    assert pane.displayed_scope == previous_scope
                    assert "Pending" in pane.status_text
                    metrics.value = "min"
                    await pilot.press("enter")
                    metrics.value = "unsubmitted metric draft"
                finally:
                    release.set()
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert app.aggregate_result is not None and app.aggregate_result is not previous
                assert app.aggregate_result.page().records == [{"min": 2}]
                assert "v · min ·" in pane.displayed_scope
                assert metrics.value == "unsubmitted metric draft"
                # Search and metrics retain their independently assigned keyboard routes.
                await pilot.press("f7")
                assert app.query_one("#record-search", Input).has_focus
                await pilot.press("f9")
                assert metrics.has_focus
                assert session.resources.reserved_disk_bytes == 0

    asyncio.run(scenario())
