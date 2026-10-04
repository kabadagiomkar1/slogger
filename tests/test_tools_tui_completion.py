"""Syntax completion exercised through a real native investigation."""

import asyncio
import json
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_operator_completion_applies_an_ixr_filter_without_losing_the_suffix(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text(
        json.dumps({"message": "timeout", "level": "ERROR"})
        + "\n"
        + json.dumps({"message": "ready", "level": "INFO"})
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = 'message co "timeout"'
                entry.cursor_position = 10
                await pilot.pause()
                choices = app.main_filter.completion.choices
                assert [choice.label for choice in choices] == [
                    "contains",
                    "contains_any",
                    "contains_all",
                ]
                await pilot.press("tab")
                assert entry.value == 'message contains "timeout"'
                await pilot.press("end", "enter")
                deadline = time.monotonic() + 5
                while app.filtered_view is None and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None
                assert app.filtered_view.record_count == 1
                assert app.selected_record == {"message": "timeout", "level": "ERROR"}
                assert app.selected_origin is not None and app.selected_origin.position == 1

    asyncio.run(scenario())


def test_functions_typed_operands_and_parentheses_are_contextual(tmp_path):
    from textual.widgets import Input, OptionList

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"timeout", "tags":["slow"]}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = "ex"
                entry.cursor_position = 2
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == ["exists("]
                await pilot.press("tab")
                assert entry.value == "exists("
                assert app.main_filter.completion.kind == "field"
                entry.value = "(message contains "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == ['"timeout"', '""']
                await pilot.press("down", "tab")
                assert entry.value == '(message contains ""'
                assert entry.cursor_position == len(entry.value) - 1
                await pilot.press(*"timeout", "end")
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == ["AND", "OR", ")"]
                await pilot.press("down", "down", "tab")
                assert entry.value.strip() == '(message contains "timeout")'
                entry.value = "tags IN "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == ["[]"]
                await pilot.press("tab")
                assert entry.value == "tags IN []" and entry.cursor_position == 9
                entry.value = "message > "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == [
                    '"timeout"',
                    '""',
                    "0",
                ]
                assert app.main_filter.query_one(OptionList).display

    asyncio.run(scenario())


def test_dismissal_mouse_selection_stale_choice_and_reusable_editors(tmp_path):
    from textual.app import App, ComposeResult
    from textual.widgets import Input, OptionList, Static

    from slogger.tools.tui.filter_editor import FilterEditor

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"ready"}')

    class TwoEditors(App):
        def compose(self) -> ComposeResult:
            yield FilterEditor()
            yield FilterEditor(id="aggregate-editor", input_id="aggregate-filter", label="Scope")
            yield Static("Records stay browseable", id="stream")

    async def scenario():
        with Investigation.open([source]) as session:
            app = TwoEditors()
            async with app.run_test(size=(90, 20)) as pilot:
                main = app.query_one("#main-editor", FilterEditor)
                aggregate = app.query_one("#aggregate-editor", FilterEditor)
                entry = aggregate.query_one(Input)
                entry.focus()
                entry.value = "n NOT "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert [c.label for c in aggregate.completion.choices] == ["IN"]
                await pilot.press("escape")
                assert not aggregate.query_one(OptionList).display
                assert entry.has_focus
                await pilot.press("ctrl+space", "tab")
                assert entry.value == "n NOT IN "
                entry.value = "message st"
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                old = aggregate.completion
                entry.value = "message ma"
                entry.cursor_position = len(entry.value)
                assert (
                    old.apply(
                        old.choices[0],
                        text=entry.value,
                        cursor=entry.cursor_position,
                        generation=aggregate.draft_generation,
                    )
                    is None
                )
                await pilot.pause()
                menu = aggregate.query_one(OptionList)
                assert [c.label for c in aggregate.completion.choices] == ["matches"]
                assert await pilot.click(menu, offset=(2, 1))
                assert entry.value == "message matches " and entry.has_focus
                assert main.draft == ""
                assert session.page().records == [{"message": "ready"}]
                entry.value = 'message contains "unterminated'
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert "closing quote" in aggregate.status_text
                assert "Applied: all records" in aggregate.status_text

    asyncio.run(scenario())


def test_scalar_array_completion_and_argument_repairs_preserve_json_types(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"flag":false,"message":"ready"}\n{"flag":0,"message":"zero"}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(120, 28)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = "flag IN [fal]"
                entry.cursor_position = 12
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == ["false"]
                await pilot.press("tab", "end", "enter")
                deadline = time.monotonic() + 5
                while app.filtered_view is None and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None and app.filtered_view.record_count == 1
                assert app.selected_record == {"flag": False, "message": "ready"}
                entry.value = "flag IN [false, null"
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                await pilot.press("tab")
                assert [c.label for c in app.main_filter.completion.choices] == [",", "]"]
                await pilot.press("down", "tab")
                assert entry.value.strip() == "flag IN [false, null ]"
                entry.value = "starts_with(message "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == [","]
                await pilot.press("tab")
                assert entry.value == "starts_with(message ,"
                await pilot.pause()
                assert app.main_filter.completion.value_kind == "string"
                entry.value = "message > true "
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert "ordering operands" in app.main_filter.status_text
                assert app.main_filter.applied_text == "flag IN [false ]"

    asyncio.run(scenario())


def test_completion_focus_routing_stays_local_during_narrow_layout_and_palette(tmp_path):
    from textual.widgets import Input, OptionList

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector

    source = tmp_path / "logs.jsonl"
    source.write_text('{"a.b":{"quoted\\"key":null}, "message":"ready"}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(65, 20)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = '["a.b"]["quoted\\"key"] == nu'
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                completion = app.main_filter.completion
                assert completion.field_path == ("a.b", 'quoted"key')
                assert [c.label for c in completion.choices] == ["null"]
                assert (
                    completion.apply(
                        completion.choices[0],
                        text=entry.value,
                        cursor=entry.cursor_position - 1,
                        generation=app.main_filter.draft_generation,
                    )
                    is None
                )
                await pilot.press("tab")
                assert entry.has_focus and entry.value.endswith("== null ")
                await pilot.press("f2")
                assert app.query_one(JSONInspector).has_focus
                assert not app.main_filter.query_one(OptionList).display
                await pilot.press("tab")
                assert app.query_one(ConsoleViewport).has_focus
                await pilot.press("f4", "ctrl+p")
                await pilot.pause()
                assert app.screen is not app.screen_stack[0]
                await pilot.press("tab", "escape")
                assert app.screen is app.screen_stack[0]
                assert entry.value.endswith("== null ")
                assert app.selected_record is not None and app.selected_record["message"] == "ready"

    asyncio.run(scenario())


def test_number_and_escaped_string_cursor_context_does_not_invent_syntax_errors(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"n":1.25, "message":"a\\"b"}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(110, 26)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = "n >= -1.25e+3"
                entry.cursor_position = len(entry.value)
                await pilot.pause()
                assert app.main_filter.completion.kind == "value"
                assert app.main_filter.completion.prefix == "-1.25e+3"
                assert "Unexpected input" not in app.main_filter.status_text
                entry.value = 'message == "a\\"b" AND n == 1.25'
                entry.cursor_position = entry.value.index("\\") + 1
                await pilot.pause()
                completion = app.main_filter.completion
                assert entry.value[completion.start : completion.end] == '"a\\"b"'
                assert completion.field_path == ("message",)
                assert "closing quote" in app.main_filter.status_text

    asyncio.run(scenario())


def test_completion_reuses_an_existing_closing_delimiter(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "logs.jsonl"
    source.write_text('{"message":"ready"}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(110, 26)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = "exists(message )"
                entry.cursor_position = len(entry.value) - 1
                await pilot.pause()
                assert [c.label for c in app.main_filter.completion.choices] == [")"]
                await pilot.press("tab")
                assert entry.value == "exists(message )"
                assert entry.cursor_position == len(entry.value)
                await pilot.press("enter")
                deadline = time.monotonic() + 5
                while app.filtered_view is None and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None and app.filtered_view.record_count == 1

    asyncio.run(scenario())


def test_dataset_completion_inserts_escaped_fields_and_typed_values(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "discovery.jsonl"
    source.write_text(
        "\n".join(json.dumps({"literal.key": value}) for value in [1, 1.0, False, 'a "quote"'])
    )

    async def scenario():
        with Investigation.open([source], storage_dir=tmp_path) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("f4")
                entry = app.query_one("#main-filter", Input)
                entry.value = '["lit'
                entry.cursor_position = len(entry.value)
                deadline = time.monotonic() + 5
                while (
                    app.main_filter.completion.text != entry.value
                    or not any(
                        c.label == '["literal.key"]' for c in app.main_filter.completion.choices
                    )
                ) and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert [c.label for c in app.main_filter.completion.choices] == ['["literal.key"]']
                await pilot.press("tab")
                assert entry.value == '["literal.key"]'
                entry.value += " == "
                entry.cursor_position = len(entry.value)
                deadline = time.monotonic() + 5
                while (
                    app.main_filter.completion.text != entry.value
                    or not any(c.label == "1.0" for c in app.main_filter.completion.choices)
                ) and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                choices = app.main_filter.completion.choices
                assert {"1", "1.0", "false", '"a \\"quote\\""'} <= {c.label for c in choices}
                assert app.main_filter.accept_completion(
                    next(i for i, c in enumerate(choices) if c.label == "false")
                )
                await pilot.press("enter")
                deadline = time.monotonic() + 5
                while app.filtered_view is None and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert app.filtered_view is not None and app.filtered_view.record_count == 1
                assert app.selected_record == {"literal.key": False}

    asyncio.run(scenario())


def test_dataset_completion_pages_and_reusable_editors_reject_stale_scopes(tmp_path):
    from textual.app import App, ComposeResult
    from textual.widgets import Input

    from slogger.tools.tui.filter_editor import FilterEditor

    source = tmp_path / "pages.jsonl"
    source.write_text("\n".join(json.dumps({"id": f"v-{i:02}"}) for i in range(45)))
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text('{"different":"fresh"}')

    class TwoEditors(App):
        def compose(self) -> ComposeResult:
            yield FilterEditor(id="one", input_id="first")
            yield FilterEditor(id="two", input_id="second", label="Agg")

    async def scenario():
        with (
            Investigation.open([source], storage_dir=tmp_path) as session,
            Investigation.open([replacement], storage_dir=tmp_path) as newer,
        ):
            index = session.discover(background=False).result()
            new_index = newer.discover(background=False).result()
            app = TwoEditors()
            async with app.run_test(size=(120, 20)) as pilot:
                first, second = (
                    app.query_one("#one", FilterEditor),
                    app.query_one("#two", FilterEditor),
                )
                first.set_discovery(index)
                second.set_discovery(index)
                entry = first.query_one(Input)
                entry.focus()
                entry.value = 'id == "v-'
                entry.cursor_position = len(entry.value)
                deadline = time.monotonic() + 5
                while not first.completion_has_more and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert first.completion.choices[0].label == '"v-00"'
                await pilot.press("pagedown")
                deadline = time.monotonic() + 5
                while (
                    not first.completion.choices or first.completion.choices[0].label != '"v-20"'
                ) and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert first.completion_offset == 20 and first.completion_has_more
                await pilot.press("pagedown")
                deadline = time.monotonic() + 5
                while first.completion_has_more and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert [c.label for c in first.completion.choices] == [
                    '"v-40"',
                    '"v-41"',
                    '"v-42"',
                    '"v-43"',
                    '"v-44"',
                ]
                await pilot.press("pageup")
                deadline = time.monotonic() + 5
                while first.completion.choices[0].label != '"v-20"' and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert first.completion.choices[0].label == '"v-20"'
                entry.value = 'id == "v-0'
                entry.cursor_position = len(entry.value)
                first.set_discovery(new_index)
                entry.value = 'different == "f'
                entry.cursor_position = len(entry.value)
                other = second.query_one(Input)
                other.value = 'id == "v-44'
                other.cursor_position = len(other.value)
                deadline = time.monotonic() + 5
                while (
                    not first.completion.choices
                    or first.completion.choices[0].label != '"fresh"'
                    or not second.completion.choices
                    or second.completion.choices[0].label != '"v-44"'
                ) and time.monotonic() < deadline:
                    await pilot.pause(0.02)
                assert first.completion.text == entry.value
                assert [c.label for c in first.completion.choices] == ['"fresh"']
                assert [c.label for c in second.completion.choices] == ['"v-44"']
                assert first.accept_completion(0)
                assert entry.value == 'different == "fresh" '
                assert other.value == 'id == "v-44'
                await pilot.press("escape")
                await pilot.press("ctrl+space")
                await pilot.pause()

    asyncio.run(scenario())
