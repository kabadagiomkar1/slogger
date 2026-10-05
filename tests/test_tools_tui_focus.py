"""Rendered input visibility and discoverable native pane navigation."""

import asyncio

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_search_navigation_uses_terminal_letter_keys(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text(
        '{"message":"start"}\n{"message":"payment retry"}\n{"message":"payment failed"}\n'
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("/", *"payment")
                for _ in range(100):
                    if app.search_result is not None:
                        break
                    await pilot.pause(0.02)
                assert app.search_result is not None
                await pilot.press("alt+1", "n")
                assert app.selected_ordinal == 1
                await pilot.press("n")
                assert app.selected_ordinal == 2
                await pilot.press("N")
                assert app.selected_ordinal == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("theme", ["textual-dark", "textual-light"])
@pytest.mark.parametrize("width", [65, 130])
@pytest.mark.parametrize(
    "input_id,text",
    [("main-filter", 'message = "visible-draft"'), ("record-search", "visible-search")],
)
def test_focused_editor_displays_typed_text(tmp_path, theme, width, input_id, text):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"visible-search","level":"INFO"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            app.theme = theme
            async with app.run_test(size=(width, 30)) as pilot:
                entry = app.query_one("#" + input_id, Input)
                entry.focus()
                await pilot.press(*text)
                await pilot.pause()
                assert entry.value == text
                assert entry.content_region.height >= 1
                assert text in app.screen._compositor.render_strips()[entry.region.y].text

    asyncio.run(scenario())


def test_completion_does_not_cover_filter_entry(tmp_path):
    from textual.widgets import Input, OptionList

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"hello","level":"INFO"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                entry = app.query_one("#main-filter", Input)
                entry.focus()
                await pilot.press("l", "e")
                await pilot.pause()
                menu = app.main_filter.query_one(OptionList)
                assert menu.display
                assert not menu.region.overlaps(entry.region)
                assert not menu.region.overlaps(app.query_one("#record-search").region)

    asyncio.run(scenario())


def test_direct_and_editor_pane_switching_and_footer_only_hints(tmp_path):
    from textual.widgets import Input, Static

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"hello"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f")
                assert app.focused is app.query_one("#main-filter", Input)
                await pilot.press("ctrl+tab")
                assert app.focused is app.query_one("#console")
                await pilot.press("alt+2")
                assert app.focused is app.query_one("#json")
                await pilot.press("alt+1", "i", "tab")
                assert app.focused is app.query_one("#console")
                assert not app.query_one("#inspector").display
                await pilot.press("/", "ctrl+tab")
                assert app.focused is app.query_one("#console")
                assert "PgUp/PgDn" not in str(app.query_one("#heading", Static).render())
                assert "F4" not in app.main_filter.status_text
                assert "F7" not in app.search_bar.status_text
                footer = app.screen._compositor.render_strips()[-1].text
                assert "Filter" in footer and "Search" in footer
                assert "f2" not in footer.lower() and "f7" not in footer.lower()

    asyncio.run(scenario())


def test_shortcuts_and_focus_indicator_do_not_steal_draft_characters(tmp_path):
    from textual.widgets import Input, Static

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"hello","level":"INFO"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f")
                entry = app.query_one("#main-filter", Input)
                assert app.focused is entry
                await pilot.press(*'message = "f/a,n"')
                assert entry.value == 'message = "f/a,n"'
                app.action_focus_console()
                await pilot.press("/")
                assert app.focused is app.query_one("#record-search", Input)
                app.action_focus_console()
                await pilot.press("tab")
                assert app.focused is app.query_one("#json")
                heading = app.query_one("#inspector-heading", Static)
                assert (
                    heading.styles.background != app.query_one("#console-heading").styles.background
                )
                assert "Focus: JSON" in str(app.query_one("#origin", Static).render())
                await pilot.press("shift+tab")
                assert app.focused is app.query_one("#console")
                assert "Focus: Console" in str(app.query_one("#origin", Static).render())
                await pilot.click("#json", offset=(2, 1))
                assert app.focused is app.query_one("#json")
                assert "Focus: JSON" in str(app.query_one("#origin", Static).render())

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "editor,expression", [("main-filter", 'level = "INFO"'), ("record-search", "hello")]
)
def test_enter_returns_to_console_and_invalid_filter_keeps_editor(tmp_path, editor, expression):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"start","level":"INFO"}\n{"message":"hello","level":"INFO"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                entry = app.query_one("#" + editor, Input)
                entry.focus()
                entry.value = expression
                await pilot.press("enter")
                assert app.focused is app.query_one("#console")
                if editor == "record-search":
                    for _ in range(100):
                        if app.search_result is not None:
                            break
                        await pilot.pause(0.02)
                    assert app.search_result is not None
                    assert app.selected_ordinal == 1
                await pilot.press("f")
                entry = app.query_one("#main-filter", Input)
                entry.value = "level ="
                await pilot.press("enter")
                assert app.focused is entry
                assert "Draft error" in app.main_filter.status_text

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "editor,text",
    [
        ("aggregate-field", "amount"),
        ("aggregate-metrics", "count, sum"),
        ("aggregate-grouping", "level"),
        ("aggregate-filter", 'level = "INFO"'),
    ],
)
def test_aggregate_editors_return_to_results(tmp_path, editor, text):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"hello","level":"INFO","amount":12}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                app.action_focus_aggregate()
                app.query_one("#aggregate-field", Input).value = "amount"
                if editor == "aggregate-filter":
                    app.action_focus_aggregate_filter()
                entry = app.query_one("#" + editor, Input)
                entry.focus()
                entry.value = text
                await pilot.press("enter")
                assert app.focused is app.query_one("#aggregate-results")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "editor",
    [
        "main-filter",
        "record-search",
        "aggregate-field",
        "aggregate-metrics",
        "aggregate-grouping",
        "aggregate-filter",
    ],
)
def test_escape_leaves_editor_in_one_press_without_applying_draft(tmp_path, editor):
    from textual.widgets import Input, OptionList

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "escape.jsonl"
    source.write_text('{"message":"hello","level":"INFO"}\n')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                if editor.startswith("aggregate"):
                    app.action_focus_aggregate()
                    if editor == "aggregate-filter":
                        app.action_focus_aggregate_filter()
                entry = app.query_one("#" + editor, Input)
                entry.focus()
                entry.value = "level"
                await pilot.pause()
                owner = app.main_filter if editor == "main-filter" else app.aggregate_filter
                if editor in ("main-filter", "aggregate-filter"):
                    assert owner.query_one(OptionList).display
                await pilot.press("escape")
                assert app.focused is app.query_one("#console")
                assert entry.value == "level"
                assert app.main_filter.applied_text == ""
                if editor in ("main-filter", "aggregate-filter"):
                    assert not owner.query_one(OptionList).display
                await pilot.press("f")
                assert app.focused is app.query_one("#main-filter")

    asyncio.run(scenario())
