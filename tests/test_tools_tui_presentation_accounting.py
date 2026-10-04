"""Dense native presentation must not scan its growing prefix for every scalar."""

import asyncio
import json
import sys
import time

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_dense_native_controls_search_and_field_targeting_bound_prefix_scans(tmp_path):
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector
    from slogger.tools.tui.presentation import _token, console_text

    row = {
        "message": "first\tneedle\nsecond\x00tail",
        "items": ["word"] * 2048,
        "odd\tkey": {"new\nkey": "tail\tvalue", "zero": 0},
    }
    source = tmp_path / "dense.jsonl"
    source.write_text(json.dumps(row) + "\n")
    builds = scans = 0
    token_code, console_code = _token.__code__, console_text.__code__

    def observe(frame, event, argument):
        nonlocal builds, scans
        if event == "call" and frame.f_code is console_code:
            builds += 1
        elif (
            event == "c_call"
            and frame.f_code is token_code
            and getattr(argument, "__name__", None) == "rsplit"
        ):
            scans += 1

    async def settled(pilot, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.01)
        assert condition()

    async def scenario():
        with Investigation.open([source], storage_dir=tmp_path / "managed") as owner:
            app = InvestigationApp(owner, preferences_path=tmp_path / "preferences.json")
            previous_profile = sys.getprofile()
            sys.setprofile(observe)
            try:
                async with app.run_test(size=(150, 38)) as pilot:
                    await settled(
                        pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                    )
                    inspector = app.query_one(JSONInspector)
                    assert json.loads(inspector.document) == row
                    console = app.query_one(ConsoleViewport)
                    await pilot.press("f3", "w", "ctrl+down", "ctrl+up", "w")
                    layout = console._record(0)
                    assert layout.text.plain.count("word") == 2048
                    assert "first needle\nsecond\\u0000tail" in layout.text.plain
                    assert ("odd\tkey",) in {target.path for target in inspector.key_targets}
                    await pilot.press("f7")
                    app.query_one("#record-search", Input).value = "needle"
                    await settled(pilot, lambda: app.search_result is not None)
                    assert app.search_result is not None
                    assert app.search_result.page().identities[0].ordinal == 0
                    await pilot.press("f3", "alt+right", "alt+right")
                    assert console.selected_field == ("items",)
                    await pilot.press("enter")
                    await settled(pilot, lambda: app.pending_aggregate is None)
                    assert app.requested_field == ("items",)
                    assert owner.page(0, 1).records == [row]
            finally:
                sys.setprofile(previous_profile)

    asyncio.run(scenario())
    assert builds > 0
    # Algorithmic guard: tab-bearing display tokens may inspect the prefix; array
    # cardinality must not add one full-prefix scan per scalar. No elapsed-time SLA.
    assert scans <= builds * 8, (builds, scans)


def test_dense_native_steady_viewport_preserves_highlights_targets_and_bounds_span_work(tmp_path):
    from rich.text import Text
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector

    row = {
        "message": "first\tneedle\nsecond\x00tail",
        "items": ["word"] * 2048,
        "wide": "🙂" * 80 + "WIDE-TAIL",
    }
    source = tmp_path / "dense-viewport.jsonl"
    source.write_text(json.dumps(row) + "\n")
    span_work = 0
    divide_code = Text.divide.__code__

    def observe(frame, event, argument):
        nonlocal span_work
        if event == "call" and frame.f_code is divide_code:
            text = frame.f_locals.get("self")
            if isinstance(text, Text) and len(text.spans) >= 2048:
                span_work += len(text.spans)

    async def settled(pilot, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            await pilot.pause(0.01)
        assert condition()

    async def scenario():
        with Investigation.open([source], storage_dir=tmp_path / "managed") as owner:
            app = InvestigationApp(owner, preferences_path=tmp_path / "preferences.json")
            async with app.run_test(size=(150, 38)) as pilot:
                await settled(
                    pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                )
                await pilot.press("f7")
                app.query_one("#record-search", Input).value = "word"
                await settled(pilot, lambda: app.search_result is not None)
                await pilot.press("f3", "alt+right", "alt+right", "w")
                console = app.query_one(ConsoleViewport)
                assert console.selected_field == ("items",)
                identity = app.selected_identity
                layout = console._record(0)
                assert layout.text.plain.count("word") == 2048
                previous_profile = sys.getprofile()
                sys.setprofile(observe)
                try:
                    await pilot.press("ctrl+down", "ctrl+down", "ctrl+up", "ctrl+up")
                    segments = [
                        segment
                        for strip in (console.render_line(y) for y in range(3))
                        for segment in strip
                    ]
                    highlighted = [
                        segment
                        for segment in segments
                        if segment.style
                        and segment.style.bgcolor
                        and segment.style.bgcolor.name == "yellow"
                    ]
                    assert highlighted and any(segment.text == "word" for segment in highlighted)
                    assert all(segment.text in "word" for segment in highlighted)
                    assert all(
                        segment.style
                        and segment.style.bold
                        and segment.style.underline
                        and segment.style.meta.get("field_path") == ("items",)
                        for segment in highlighted
                    )
                    await pilot.press("w", "shift+right", "right", "left", "ctrl+left")
                finally:
                    sys.setprofile(previous_profile)
                assert app.selected_identity == identity
                assert json.loads(app.query_one(JSONInspector).document) == row
                assert owner.page(0, 1).records == [row]
                # At most two complete-record passes are allowed at a layout
                # transition. Steady visible rows must not rescan/render all spans.
                assert span_work <= len(layout.text.spans) * 2, span_work

    asyncio.run(scenario())


def test_native_partial_wide_cell_pan_preserves_glyphs_and_message_hit_target(tmp_path):
    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector

    row = {"message": "lead" + "🙂" * 80 + "WIDE-TAIL"}
    source = tmp_path / "wide-cell.jsonl"
    source.write_text(json.dumps(row) + "\n")

    async def scenario():
        with Investigation.open([source], storage_dir=tmp_path / "managed") as owner:
            app = InvestigationApp(owner, preferences_path=tmp_path / "preferences.json")
            async with app.run_test(size=(130, 32)) as pilot:
                await pilot.press("f3")
                console = app.query_one(ConsoleViewport)
                identity = app.selected_identity
                first = console._record(0).text.plain.index("🙂")
                await pilot.press(*(["right"] * (first + 1)))
                assert console.scroll_offset.x == first + 1
                assert console.render_line(0).text.startswith(" 🙂🙂")
                assert console.render_line(0).cell_length == console.size.width
                await pilot.press("left")
                assert console.render_line(0).text.startswith("🙂🙂")
                await pilot.press("left")
                assert console.render_line(0).text.startswith("d🙂🙂")
                await pilot.click("#console", offset=(3, 0))
                assert console.selected_field == ("message",)
                assert app.selected_identity == identity
                assert json.loads(app.query_one(JSONInspector).document) == row
                assert owner.page(0, 1).records == [row]

    asyncio.run(scenario())


def test_native_clip_keeps_trailing_combining_and_variation_marks_like_full_rich(tmp_path):
    from rich.style import Style
    from textual.strip import Strip

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    row = {"message": "abce\u0301f♥\ufe0fg" * 80 + "TAIL"}
    source = tmp_path / "combining.jsonl"
    source.write_text(json.dumps(row) + "\n")

    async def scenario():
        with Investigation.open([source], storage_dir=tmp_path / "managed") as owner:
            app = InvestigationApp(owner, preferences_path=tmp_path / "preferences.json")
            async with app.run_test(size=(130, 32)) as pilot:
                await pilot.press("f3")
                console = app.query_one(ConsoleViewport)
                identity = app.selected_identity
                full = console._record(0).text
                # Independent oracle: Rich renders/crops the complete original
                # styled record. Exercise every boundary in the seven-cell repeat.
                reference = Strip(full.render(app.console)).apply_style(console.rich_style)
                for _ in range(9):
                    await pilot.press("right")
                    offset, width = console.scroll_offset.x, console.size.width
                    expected = (
                        reference.crop(offset, offset + width)
                        .apply_style(Style(reverse=True))
                        .adjust_cell_length(width, console.rich_style)
                    )
                    actual = console.render_line(0)
                    assert actual.text == expected.text, (offset, actual.text, expected.text)
                    assert list(actual) == list(expected)
                assert app.selected_identity == identity
                assert owner.page(0, 1).records == [row]

    asyncio.run(scenario())
