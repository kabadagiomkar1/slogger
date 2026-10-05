"""Focused native interaction checks; installed optional dependency stays optional."""

import asyncio

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_keyboard_paging_and_mouse_selection_show_complete_json(tmp_path):
    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source = tmp_path / "records.jsonl"
    source.write_text(
        "".join('{"message":"record ' + str(i) + '"}\n' for i in range(300))
        + '{"message":"'
        + "x" * 70000
        + '","tail":"complete"}\n'
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)) as pilot:
                assert app.selected_ordinal == 0
                await pilot.press("down")
                assert app.selected_ordinal == 1
                assert app.inspected_record == {"message": "record 1"}
                await pilot.press("pagedown")
                assert app.selected_ordinal > 1
                await pilot.press("end")
                assert app.selected_ordinal == 300
                assert app.inspected_record is not None
                assert app.inspected_record["tail"] == "complete"
                assert '"tail": "complete"' in app.query_one("#json", JSONInspector).document
                assert len(app.query_one("#json", JSONInspector).document) > 70000
                await pilot.press("home")
                await pilot.click("#console", offset=(5, 2))
                assert app.selected_ordinal == 2
                assert app.inspected_record == {"message": "record 2"}

    asyncio.run(scenario())


def test_console_recognizes_real_slogger_schema_and_aligns_messages(tmp_path):
    import json

    import slogger
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    with slogger.capture_logs() as emitted:
        with slogger.get_logger("short").span("canonical"):
            slogger.get_logger("short").info("ASCII first", customer="café", span_name="external")
            slogger.get_logger("a.logger.name.longer.than.column").warning("ASCII second", n=0)
    source = tmp_path / "real.jsonl"
    source.write_text("\n".join(json.dumps(record) for record in emitted))

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(180, 25)) as pilot:
                console = app.query_one("#console", ConsoleViewport)
                first = console.render_line(1).text
                second = console.render_line(2).text
                assert first.index("ASCII first") == second.index("ASCII second")
                assert "[canonical]" in first and "external" not in first
                assert 'customer="café"' in first
                assert "trace_id" not in first and "file=" not in first and "event=" not in first
                await pilot.press("down")
                assert app.inspected_record == emitted[1]
                assert session.page(1, 1).origins[0].position == 2
                snapshot = app.export_screenshot()
                (tmp_path / "real-console.svg").write_text(snapshot)

    asyncio.run(scenario())
