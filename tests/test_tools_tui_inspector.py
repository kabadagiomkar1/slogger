"""Inspector behavior through real capture and the focused native consumer seam."""

import asyncio
import json

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_complete_json_scrolls_independently_and_line_numbers_are_optional(tmp_path):
    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "long.jsonl"
    source.write_text(json.dumps({"wide": "界" * 40000, "rows": list(range(180)), "tail": "end"}))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                inspector = app.query_one(JSONInspector)
                await pilot.press("tab", "end")
                assert app.selected_ordinal == 0
                assert inspector.scroll_offset.y > 150
                assert '"tail": "end"' in inspector.document
                assert json.loads(inspector.document) == session.page(0, 1).records[0]
                await pilot.press("home", "right")
                assert inspector.scroll_offset.x > 0
                await pilot.press("left", "l")
                assert inspector.line_numbers is True
                assert inspector.render_line(0).text.lstrip().startswith("1 ")
                await pilot.press("l")
                assert inspector.line_numbers is False
                assert inspector.render_line(0).text.startswith("{")

    asyncio.run(scenario())


def test_json_keys_expose_exact_mapping_paths_and_guidance_for_unsupported_keys(tmp_path):
    from slogger.tools import Field
    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "keys.jsonl"
    source.write_text(
        json.dumps(
            {
                "a": {"b": 1},
                "a.b": 2,
                "sp ace": {'quo"te': 3},
                "items": [{"inside": 4}],
                "": {"child": 5},
            }
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                inspector = app.query_one(JSONInspector)
                await pilot.press("tab", "j")
                assert inspector.selected_path == ("a",)
                await pilot.press("j", "enter")
                assert inspector.selected_path == ("a", "b")
                assert app.requested_field == Field("a", "b").path
                await pilot.press("j")
                assert inspector.selected_path == ("a.b",)
                assert inspector.selected_target is not None
                assert inspector.selected_target.label == '["a.b"]'
                await pilot.press("j", "j")
                assert inspector.selected_path == ("sp ace", 'quo"te')
                assert inspector.selected_target is not None
                assert inspector.selected_target.label == '["sp ace"]["quo\\"te"]'
                await pilot.press("j", "j")
                assert inspector.selected_path is None
                assert inspector.selected_target is not None
                assert inspector.selected_target.guidance is not None
                assert "array" in inspector.selected_target.guidance
                await pilot.press("j", "j", "enter")
                assert inspector.selected_path is None
                assert inspector.selected_target is not None
                assert inspector.selected_target.guidance is not None
                assert "empty" in inspector.selected_target.guidance
                assert app.requested_field == ("a", "b")
                await pilot.press("k", "k", "k")
                assert inspector.selected_path == ("items",)
                await pilot.click("#json", offset=(8, 2))
                assert inspector.selected_path == ("a", "b")

    asyncio.run(scenario())


def test_pin_retains_inspected_occurrence_while_console_selection_moves(tmp_path):
    from textual.widgets import Static

    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "records.jsonl"
    source.write_text('\n{"event":"reference"}\n{"event":"comparison"}')

    async def scenario():
        with Investigation.open([source, source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                reference = session.page(0, 1).identities[0]
                await pilot.press("p", "down", "down")
                assert app.selected_identity == session.page(2, 1).identities[0]
                assert app.selected_identity != reference
                assert app.pinned_identity == reference
                assert app.inspected_identity == reference
                assert app.inspected_record == {"event": "reference"}
                assert "pinned" in str(app.query_one("#inspector-heading", Static).render())
                origin = str(app.query_one("#origin", Static).render())
                assert "Selected" in origin and "input 2" in origin
                assert "Pinned" in origin and "input 1" in origin and "records.jsonl:2" in origin
                await pilot.press("p")
                assert app.pinned_identity is None
                assert app.inspected_identity == app.selected_identity
                assert json.loads(app.query_one(JSONInspector).document) == {"event": "reference"}
                await pilot.press("down")
                assert app.inspected_record == {"event": "comparison"}

    asyncio.run(scenario())


def test_hiding_resizing_and_narrow_focus_preserve_the_pin(tmp_path):
    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "records.jsonl"
    source.write_text('{"reference":1}\n{"other":2}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(140, 25)) as pilot:
                inspector = app.query_one(JSONInspector)
                await pilot.press("p", "ctrl+j")
                assert app.focused is inspector
                width = app.inspector_percent
                await pilot.press("[", "[")
                assert app.inspector_percent < width
                await pilot.press("]")
                assert app.inspector_percent == width - 5
                await pilot.press("i")
                assert not app.query_one("#inspector").display
                assert app.focused is not None
                assert app.focused.id == "console"
                await pilot.press("down", "i", "ctrl+j")
                assert app.inspected_record == {"reference": 1}
                await pilot.resize_terminal(55, 18)
                assert app.focused is not None
                assert app.focused.id == "console"
                assert not app.query_one("#inspector").display
                await pilot.press("ctrl+j")
                assert app.focused is inspector
                assert app.query_one("#inspector").display
                assert not app.query_one("#stream").display
                assert inspector.size.width >= 50
                await pilot.press("tab")
                assert app.focused is not None
                assert app.focused.id == "console"
                assert not app.query_one("#inspector").display
                assert app.query_one("#stream").display
                await pilot.resize_terminal(140, 25)
                assert app.query_one("#inspector").display
                assert app.pinned_identity == session.page(0, 1).identities[0]
                assert app.selected_ordinal == 1
                assert json.loads(inspector.document) == {"reference": 1}
                snapshot = app.export_screenshot()
                assert "Pinned" in snapshot and "Selected" in snapshot
                (tmp_path / "inspector-wide.svg").write_text(snapshot)

    asyncio.run(scenario())


def test_copy_reports_unavailable_or_sends_complete_pinned_json_to_terminal_transport(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps({"reference": "界" * 40000, "tail": "complete"}) + '\n{"other":2}')
    sent = []

    async def scenario():
        with Investigation.open([source]) as session:
            unavailable = InvestigationApp(session)
            async with unavailable.run_test(size=(130, 25)) as pilot:
                await pilot.press("c")
                assert "unavailable" in unavailable.copy_status.lower()
                assert unavailable.clipboard == ""
            app = InvestigationApp(session, clipboard_writer=sent.append)
            async with app.run_test(size=(130, 25)) as pilot:
                await pilot.press("p", "down", "c")
                assert json.loads(sent[0]) == {"reference": "界" * 40000, "tail": "complete"}
                assert "sent" in app.copy_status.lower()
                assert "unverified" in app.copy_status.lower()

    asyncio.run(scenario())


def test_inspector_handles_empty_input_and_terminal_transport_failure_without_losing_pin(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    source = tmp_path / "records.jsonl"
    source.write_text('{"message":"reference"}')
    storage = tmp_path / "storage"

    def failed_terminal_write(document):
        raise OSError("terminal disconnected")

    async def scenario():
        with Investigation.open([empty], storage_dir=storage) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(55, 18)) as pilot:
                await pilot.press("p", "c", "f2", "j", "enter", "f3")
                assert app.pinned_identity is None
                assert app.requested_field is None
                assert "no record" in app.copy_status
                assert app.focused is not None
                assert app.focused.id == "console"
        assert list(storage.iterdir()) == []
        with Investigation.open([source], storage_dir=storage) as session:
            app = InvestigationApp(session, clipboard_writer=failed_terminal_write)
            async with app.run_test(size=(130, 25)) as pilot:
                await pilot.press("p", "c")
                assert "unavailable" in app.copy_status.lower()
                assert "terminal disconnected" in app.copy_status
                assert app.pinned_identity == session.page(0, 1).identities[0]
                assert app.inspected_record == {"message": "reference"}
        assert list(storage.iterdir()) == []

    asyncio.run(scenario())


def test_inspector_controls_are_discoverable_from_the_narrow_command_palette(tmp_path):
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text('{"reference":1}')

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(55, 18)) as pilot:
                await pilot.press("ctrl+p")
                names = {command.title for command in app.get_system_commands(app.screen)}
                assert {
                    "Focus JSON",
                    "Focus console",
                    "Pin JSON",
                    "Copy JSON",
                    "Narrower JSON",
                    "Wider JSON",
                    "JSON line numbers",
                } <= names
                await pilot.press("escape", "f2")
                assert app.focused is not None
                assert app.focused.id == "json"
                await pilot.press("f3")
                assert app.focused is not None
                assert app.focused.id == "console"

    asyncio.run(scenario())
