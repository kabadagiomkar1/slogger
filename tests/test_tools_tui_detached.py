"""Independent native aggregate scopes over complete captured data."""

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
    from slogger.tools.tui.aggregates import AggregatePane

    app = pilot.app
    assert condition(), {
        "main": app.main_filter.status_text,
        "independent": app.aggregate_filter.status_text,
        "aggregate": app.query_one(AggregatePane).status_text,
        "filter": app.pending_detached_filter.status if app.pending_detached_filter else None,
        "aggregate_job": app.pending_aggregate.status if app.pending_aggregate else None,
        "view": app.detached_view.view_scope if app.detached_view else None,
        "result": app.aggregate_result.scope if app.aggregate_result else None,
    }


def test_detaching_copies_applied_main_and_reattaching_uses_latest_main(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "detached.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"keep": True, "v": "a", "cost": 2},
                {"keep": True, "v": None, "cost": None},
                {"keep": True},
                {"keep": False, "v": "b", "cost": 7},
            ]
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(135, 40)) as pilot:
                await pilot.press("f4")
                main = app.query_one("#main-filter", Input)
                main.focus()
                main.value = "keep == true"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).focus()
                app.query_one("#aggregate-field", Input).value = "v"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"value": "a", "count": 1},
                    {"value": None, "count": 1},
                ]
                main.value = 'v == "unapplied draft"'
                await pilot.click("#aggregate-detach")
                independent = app.query_one("#aggregate-filter", Input)
                assert independent.value == "keep == true"
                await settle(
                    pilot,
                    lambda: (
                        app.detached_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.detached_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                detached = app.aggregate_result
                assert detached is not None
                pane = app.query_one(AggregatePane)
                assert "independent: keep == true" in pane.displayed_scope
                await pilot.press("f4")
                main.focus()
                main.value = "keep == false"
                await pilot.press("enter")
                await settle(pilot, lambda: app.main_filter.applied_text == "keep == false")
                assert app.aggregate_result is detached
                assert independent.value == "keep == true"
                assert app.filtered_view is not None
                assert app.filtered_view.page().records == [{"keep": False, "v": "b", "cost": 7}]
                independent.focus()
                independent.focus()
                independent.value = 'v == "b"'
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not detached)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": "b", "count": 1}]
                assert app.main_filter.applied_text == "keep == false"
                await pilot.click("#aggregate-reattach")
                await settle(pilot, lambda: "follows Main: keep == false" in pane.displayed_scope)
                assert not app.query_one("#aggregate-editor").display
                # Metric changes and selected-field presence use the same explicit population.
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).focus()
                app.query_one("#aggregate-field", Input).value = "cost"
                await pilot.press("enter")
                await settle(
                    pilot, lambda: app.aggregate_result.scope.selected_field.path == ("cost",)
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"count": 1, "sum": 7, "mean": 7.0, "min": 7, "max": 7}
                ]

    asyncio.run(scenario())


def test_independent_editor_shares_complete_typed_discovery_and_keeps_drafts_local(tmp_path):
    from textual.widgets import Input, OptionList

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "choices.jsonl"
    source.write_text(
        "\n".join(json.dumps({"literal.key": f"v-{i:03d}", "v": i}) for i in range(65))
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 40)) as pilot:
                await settle(pilot, lambda: app.main_filter.discovery_index is not None)
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).value = "literal.key"
                await pilot.press("ctrl+d")
                entry = app.query_one("#aggregate-filter", Input)
                assert entry.has_focus
                editor = app.aggregate_filter
                assert editor.discovery_index is app.main_filter.discovery_index
                main = app.query_one("#main-filter", Input)
                main.value = "v == 62"
                entry.value = '["literal.key"] == "v-'
                entry.cursor_position = len(entry.value)
                await settle(pilot, lambda: editor.completion_has_more)
                assert editor.completion.choices[0].label == '"v-000"'
                await pilot.press("pagedown")
                await settle(pilot, lambda: editor.completion.choices[0].label == '"v-020"')
                await pilot.press("tab")
                assert entry.value == '["literal.key"] == "v-020" '
                assert main.value == "v == 62"
                entry.value = '["literal.key"] == "v-064'
                entry.cursor_position = len(entry.value)
                await settle(
                    pilot,
                    lambda: (
                        editor.completion.text == entry.value
                        and editor.completion.choices[0].label == '"v-064"'
                    ),
                )
                menu = editor.query_one(OptionList)
                await pilot.click(menu, offset=(2, 1))
                assert entry.value == '["literal.key"] == "v-064" '
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: app.detached_view is not None and app.detached_view.record_count == 1,
                )
                assert app.detached_view is not None
                assert app.detached_view.page().records == [{"literal.key": "v-064", "v": 64}]
                assert app.filtered_view is None
                assert main.value == "v == 62"
                await pilot.press("f4")
                assert not menu.display
                assert entry.value == '["literal.key"] == "v-064" '
                await pilot.resize_terminal(65, 30)
                await pilot.press("f2")
                assert app.query_one("#inspector").display
                await pilot.press("ctrl+d")
                assert app.query_one("#stream").display
                assert not app.query_one("#inspector").display
                assert entry.has_focus and app.aggregate_filter.draft == entry.value
                await pilot.press("ctrl+p")
                names = {command.title for command in app.get_system_commands(app.screen)}
                assert {"Edit independent aggregate filter", "Reattach aggregate to Main"} <= names
                await pilot.press("escape")

    asyncio.run(scenario())


def test_failed_initial_detach_never_uses_an_unfiltered_population(tmp_path, monkeypatch):
    import subprocess

    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "failed-detach.jsonl"
    source.write_text('{"keep":true,"cost":2}\n{"keep":false,"cost":7}')
    original_popen = subprocess.Popen
    fail = True

    def fail_first_worker(*args, **kwargs):
        nonlocal fail
        if fail:
            fail = False
            raise OSError("worker unavailable")
        return original_popen(*args, **kwargs)

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 40)) as pilot:
                await pilot.press("f4")
                app.query_one("#main-filter", Input).focus()
                app.query_one("#main-filter", Input).value = "keep == true"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).focus()
                app.query_one("#aggregate-field", Input).value = "cost"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                previous = app.aggregate_result
                pane = app.query_one(AggregatePane)
                old_scope = pane.displayed_scope
                monkeypatch.setattr(subprocess, "Popen", fail_first_worker)
                await pilot.press("ctrl+d")
                assert app.detached_view is None
                assert "worker unavailable" in app.aggregate_filter.status_text
                await pilot.press("f9")
                app.query_one("#aggregate-metrics", Input).focus()
                app.query_one("#aggregate-metrics", Input).value = "count, sum"
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert app.aggregate_result is previous
                assert pane.displayed_scope == old_scope
                assert "no successful scope" in pane.status_text
                await pilot.press("ctrl+d", "enter")
                await settle(pilot, lambda: app.aggregate_result is not previous)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"count": 1, "sum": 2}]
                assert app.aggregate_result is not None
                assert app.detached_view is not None
                assert app.aggregate_result.scope.input_scope == app.detached_view.view_scope

    asyncio.run(scenario())


def test_reattaching_during_numeric_replay_rejects_stale_result_and_keeps_drafts(
    tmp_path, monkeypatch
):
    import threading
    from pathlib import Path

    from textual.widgets import Input

    from slogger.tools import ToolError
    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "leased-replay.jsonl"
    source.write_text('{"keep":true,"cost":2}\n{"keep":false,"cost":7}')
    entered, release = threading.Event(), threading.Event()
    original_open = Path.open
    paused = False

    def pause_first_replay(path, mode="r", *args, **kwargs):
        nonlocal paused
        if path.name.startswith("numeric-") and mode == "rb" and not paused:
            paused = True
            entered.set()
            assert release.wait(10)
        return original_open(path, mode, *args, **kwargs)

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(135, 40)) as pilot:
                await pilot.press("f4")
                main = app.query_one("#main-filter", Input)
                main.focus()
                main.value = "keep == true"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f5")
                field = app.query_one("#aggregate-field", Input)
                field.focus()
                field.value = "cost"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                await pilot.press("ctrl+d")
                await settle(
                    pilot,
                    lambda: (
                        app.detached_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.detached_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                previous = app.aggregate_result
                pane = app.query_one(AggregatePane)
                old_scope = pane.displayed_scope
                await pilot.press("f4")
                main.focus()
                main.value = "keep == false"
                await pilot.press("enter")
                await settle(pilot, lambda: app.main_filter.applied_text == "keep == false")
                assert app.aggregate_result is previous
                monkeypatch.setattr(Path, "open", pause_first_replay)
                await pilot.press("f9")
                metrics = app.query_one("#aggregate-metrics", Input)
                metrics.focus()
                metrics.value = "mean"
                await pilot.press("enter")
                try:
                    await settle(pilot, entered.is_set)
                    stale = app.pending_aggregate
                    independent_view = app.detached_view
                    assert stale is not None and independent_view is not None
                    field.value = "new field draft"
                    metrics.value = "new metric draft"
                    await pilot.click("#aggregate-reattach")
                    assert app.aggregate_result is previous
                    assert pane.displayed_scope == old_scope
                    assert (
                        "Pending:" in pane.status_text
                        and "follows Main: keep == false" in pane.status_text
                    )
                    with pytest.raises(ToolError, match="closed"):
                        independent_view.page()
                finally:
                    release.set()
                await settle(pilot, lambda: app.pending_aggregate is None)
                assert stale.done and stale.status.phase == "cancelled"
                assert app.aggregate_result is not previous
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"mean": 7.0}]
                assert app.aggregate_result is not None
                assert app.filtered_view is not None
                assert app.aggregate_result.scope.input_scope == app.filtered_view.view_scope
                assert field.value == "new field draft" and metrics.value == "new metric draft"
                assert session.resources.reserved_disk_bytes == 0

    asyncio.run(scenario())


def test_independent_filter_cancel_errors_and_supersession_keep_applied_scope(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.aggregates import AggregatePane
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "cancel-scope.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"message": "a" * 50000 + "!", "v": "first"},
                {"message": "other", "v": "second"},
            ]
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(135, 40)) as pilot:
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).focus()
                app.query_one("#aggregate-field", Input).value = "v"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                await pilot.press("ctrl+d")
                await settle(
                    pilot,
                    lambda: (
                        app.detached_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.detached_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                previous = app.aggregate_result
                pane = app.query_one(AggregatePane)
                old_scope = pane.displayed_scope
                editor = app.query_one("#aggregate-filter", Input)
                editor.focus()
                editor.value = 'message matches "(a+)+$"'
                await pilot.press("enter")
                stale = app.pending_detached_filter
                assert stale is not None
                assert app.aggregate_result is previous and pane.displayed_scope == old_scope
                editor.focus()
                await pilot.press("escape")
                assert app.focused is app.query_one("#console")
                await settle(pilot, lambda: app.pending_detached_filter is None)
                assert stale.done and stale.status.phase == "cancelled"
                assert app.aggregate_result is previous
                assert "Canceled" in app.aggregate_filter.status_text
                editor.focus()
                editor.value = "message =="
                await pilot.press("enter")
                assert "Draft error" in app.aggregate_filter.status_text
                assert app.aggregate_result is previous
                editor.focus()
                editor.value = 'message matches "["'
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_detached_filter is None)
                assert app.aggregate_result is previous and pane.displayed_scope == old_scope
                assert app.aggregate_filter.applied_text == ""
                editor.focus()
                editor.value = 'message matches "(a+)+$"'
                await pilot.press("enter")
                stale = app.pending_detached_filter
                assert stale is not None
                editor.focus()
                editor.value = 'message == "other"'
                await pilot.press("enter")
                editor.value = "newer unsubmitted draft"
                await settle(pilot, lambda: app.aggregate_result is not previous)
                assert stale.done and stale.status.phase == "cancelled"
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": "second", "count": 1}]
                assert app.aggregate_filter.applied_text == 'message == "other"'
                assert editor.value == "newer unsubmitted draft"
                assert app.filtered_view is None
                assert session.resources.reserved_disk_bytes == 0

    asyncio.run(scenario())


def test_detach_ignores_main_pending_filter_and_preserves_its_prior_applied_scope(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "pending-main.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"keep": True, "v": "first", "message": "a" * 5000 + "!"},
                {"keep": False, "v": "second", "message": "other"},
            ]
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 40)) as pilot:
                await pilot.press("f4")
                main = app.query_one("#main-filter", Input)
                main.focus()
                main.value = "keep == true"
                await pilot.press("enter")
                await settle(pilot, lambda: app.filtered_view is not None)
                await pilot.press("f5")
                app.query_one("#aggregate-field", Input).focus()
                app.query_one("#aggregate-field", Input).value = "v"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                await pilot.press("f4")
                main.focus()
                main.value = 'message matches "(a+)+$"'
                await pilot.press("enter")
                pending = app.pending_filter
                assert pending is not None
                await pilot.click("#aggregate-detach")
                assert app.aggregate_filter.draft == "keep == true"
                await settle(
                    pilot,
                    lambda: (
                        app.detached_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.detached_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                assert app.aggregate_filter.applied_text == "keep == true"
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [{"value": "first", "count": 1}]
                assert app.main_filter.pending_text == 'message matches "(a+)+$"'
                assert main.value == 'message matches "(a+)+$"'
                await pilot.press("f6", "escape")
                await settle(pilot, lambda: app.pending_filter is None)
                assert pending.status.phase == "cancelled"
                assert app.main_filter.applied_text == "keep == true"
                assert app.aggregate_filter.applied_text == "keep == true"

    asyncio.run(scenario())


def test_grouped_independent_scope_reattaches_with_configuration_and_newer_drafts(tmp_path):
    from textual.widgets import Input

    from slogger.tools import GroupBinding
    from slogger.tools.tui.aggregates import AggregatePane, AggregateViewport
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "grouped-detached.jsonl"
    rows = [
        {"keep": True, "cost": 2, "g": {"region": "north"}},
        {"keep": True, "cost": None, "g": {"region": "south"}},
        {"keep": True, "g": {"region": "excluded-missing-cost"}},
        {"keep": False, "cost": 7, "g": {"region": "south"}},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(135, 40)) as pilot:
                await pilot.press("f5")
                field = app.query_one("#aggregate-field", Input)
                field.focus()
                field.value = "cost"
                await pilot.press("enter")
                await settle(pilot, lambda: app.aggregate_result is not None)
                await pilot.press("f9")
                metrics = app.query_one("#aggregate-metrics", Input)
                metrics.focus()
                metrics.value = "count, sum"
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                await pilot.press("m", "tab")
                grouping = app.query_one("#aggregate-grouping", Input)
                assert grouping.has_focus
                grouping.focus()
                grouping.value = "g.region as area"
                await pilot.press("enter")
                await settle(pilot, lambda: app.pending_aggregate is None)
                configured = (GroupBinding(("g", "region"), "area"),)
                assert app.aggregate_grouping == configured
                await pilot.press("f4")
                main = app.query_one("#main-filter", Input)
                main.focus()
                main.value = "keep == true"
                await pilot.press("enter")
                await settle(
                    pilot,
                    lambda: (
                        app.filtered_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.filtered_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"area": "north", "count": 1, "sum": 2},
                    {"area": "south", "count": 1, "sum": 0},
                ]
                await pilot.press("ctrl+d")
                await settle(
                    pilot,
                    lambda: (
                        app.detached_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.detached_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                independent = app.aggregate_result
                assert independent is not None
                assert independent.scope.grouping == configured
                pane = app.query_one(AggregatePane)
                assert "group by g.region as area" in pane.displayed_scope
                assert "independent: keep == true" in pane.displayed_scope
                await pilot.press("f4")
                main.focus()
                main.value = "keep == false"
                await pilot.press("enter")
                await settle(pilot, lambda: app.main_filter.applied_text == "keep == false")
                assert app.aggregate_result is independent
                await pilot.press("ctrl+d")
                app.query_one("#aggregate-filter", Input).focus()
                app.query_one("#aggregate-filter", Input).value = "keep == false"
                await pilot.press("enter")
                field.value = "new field draft"
                metrics.value = "new metric draft"
                grouping.value = "new grouping draft"
                await settle(pilot, lambda: app.aggregate_result is not independent)
                assert app.aggregate_result is not None
                assert app.aggregate_result.page().records == [
                    {"area": "south", "count": 1, "sum": 7}
                ]
                await pilot.resize_terminal(65, 30)
                await pilot.press("f6")
                viewport = app.query_one(AggregateViewport)
                assert viewport.has_focus and viewport.size.height >= 1
                assert "south" in viewport.render_line(0).text
                await pilot.click("#aggregate-reattach")
                await settle(
                    pilot,
                    lambda: (
                        app.filtered_view is not None
                        and app.aggregate_result is not None
                        and app.aggregate_result.scope.input_scope == app.filtered_view.view_scope
                        and app.pending_aggregate is None
                    ),
                )
                assert app.aggregate_result is not None
                assert app.aggregate_result.scope.metrics == ("count", "sum")
                assert app.aggregate_result.scope.grouping == configured
                assert app.aggregate_result.page().records == [
                    {"area": "south", "count": 1, "sum": 7}
                ]
                assert "follows Main: keep == false" in pane.displayed_scope
                assert field.value == "new field draft"
                assert metrics.value == "new metric draft"
                assert grouping.value == "new grouping draft"
                assert session.resources.reserved_disk_bytes == 0

    asyncio.run(scenario())
