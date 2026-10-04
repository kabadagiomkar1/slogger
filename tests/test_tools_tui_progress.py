"""Native loading, prefix inspection, and cancellation at the approved UI seam."""

import asyncio

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_loading_prefix_is_selectable_and_escape_retains_inspection(blocked_source):
    from textual.widgets import Static

    from slogger.tools.tui.app import InvestigationApp, JSONInspector

    source, entered, release = blocked_source

    async def scenario():
        with Investigation.open([source], background=True) as session:
            try:
                assert entered.wait(5)
                app = InvestigationApp(session)
                async with app.run_test(size=(130, 25)) as pilot:
                    heading = str(app.query_one("#heading", Static).render())
                    assert "capturing" in heading and "incomplete" in heading
                    await pilot.press("down")
                    assert app.selected_ordinal == 1
                    assert '"n": 1' in app.query_one(JSONInspector).document
                    await pilot.press("escape")
                    release.set()
                    assert session.wait(5).phase == "canceled"
                    await pilot.pause(0.2)
                    heading = str(app.query_one("#heading", Static).render())
                    assert "canceled" in heading and "incomplete" in heading
                    assert "capture_canceled" in heading
                    assert app.selected_ordinal == 1
                    assert '"n": 1' in app.query_one(JSONInspector).document
            finally:
                release.set()

    asyncio.run(scenario())


def test_failed_opening_keeps_prefix_and_reports_error_origin(tmp_path):
    from textual.widgets import Static

    from slogger.tools import ResourceLimits
    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "oversized.jsonl"
    source.write_text('{"n":1}\n{"message":"' + "x" * 100 + '"}\n')

    async def scenario():
        with Investigation.open([source], limits=ResourceLimits(max_record_bytes=32)) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)):
                heading = str(app.query_one("#heading", Static).render())
                assert "failed" in heading and "incomplete" in heading
                assert "record_too_large" in heading
                assert f"{source}:2" in heading
                assert app.inspected_record == {"n": 1}

    asyncio.run(scenario())


def test_capture_completion_preserves_pinned_inspection_and_narrow_controls(blocked_source):
    from textual.widgets import Static

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector

    source, entered, release = blocked_source

    async def scenario():
        with Investigation.open([source], background=True) as session:
            try:
                assert entered.wait(5)
                prefix_count = session.status.record_count
                assert 0 < prefix_count < 1000
                app = InvestigationApp(session)
                async with app.run_test(size=(130, 25)) as pilot:
                    inspector = app.query_one(JSONInspector)
                    await pilot.press("p", "f2", "j", "j", "right", "f3", "down", "w")
                    pinned = app.inspected_identity
                    document = inspector.document
                    assert inspector.selected_path == ("message",)
                    assert inspector.scroll_offset.x > 0
                    await pilot.press("ctrl+p", "escape")
                    assert session.status.phase == "capturing"
                    await pilot.resize_terminal(55, 18)
                    await pilot.press("tab")
                    assert app.focused is inspector
                    assert not app.query_one("#stream").display
                    scroll = inspector.scroll_offset
                    selected = app.selected_identity
                    release.set()
                    assert session.wait(5).complete
                    await pilot.pause(0.2)
                    assert "complete" in str(app.query_one("#heading", Static).render())
                    assert app.selected_identity == selected
                    assert app.query_one(ConsoleViewport).options.wrap
                    assert app.pinned_identity == pinned == app.inspected_identity
                    assert inspector.document == document
                    assert inspector.selected_path == ("message",)
                    assert inspector.scroll_offset == scroll
                    origin = str(app.query_one("#origin", Static).render())
                    assert "Selected 2/1000" in origin and "Pinned 1/1000" in origin
                    assert "Disk" in origin and "RAM browsing cache" in origin
                    await pilot.press("tab")
                    assert app.focused is app.query_one(ConsoleViewport)
                    assert not app.query_one("#inspector").display
            finally:
                release.set()

    asyncio.run(scenario())


def test_verified_cache_reuse_and_io_are_visible(tmp_path):
    from textual.widgets import Static

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text('{"n":1}\n')
    cache = tmp_path / "cache"
    with Investigation.open([source], cache_dir=cache):
        pass

    async def scenario():
        with Investigation.open([source], cache_dir=cache) as session:
            app = InvestigationApp(session)
            async with app.run_test(size=(130, 25)):
                heading = str(app.query_one("#heading", Static).render())
                assert "verified cache reuse" in heading
                assert "bytes verified" in heading
                assert app.inspected_record == {"n": 1}

    asyncio.run(scenario())


def test_reuse_verification_is_incomplete_and_cancel_keeps_good_cache(blocked_source, tmp_path):
    from textual.widgets import Static

    from slogger.tools.tui.app import InvestigationApp

    source, entered, release = blocked_source
    cache = tmp_path / "cache"
    release.set()
    with Investigation.open([source], cache_dir=cache) as captured:
        identity = captured.dataset_id
        assert captured.status.complete
    entered.clear()
    release.clear()

    async def scenario():
        with Investigation.open([source], cache_dir=cache, background=True) as session:
            try:
                assert entered.wait(5)
                assert session.status.phase == "verifying_cache"
                assert not session.status.complete
                assert session.page().records == []
                assert session.status.verified_bytes > 0
                app = InvestigationApp(session)
                async with app.run_test(size=(130, 25)) as pilot:
                    heading = str(app.query_one("#heading", Static).render())
                    assert "verifying_cache" in heading and "incomplete" in heading
                    assert "cache bytes verified" in heading
                    await pilot.press("escape")
                    release.set()
                    assert session.wait(5).phase == "canceled"
            finally:
                release.set()
        with Investigation.open([source], cache_dir=cache) as reopened:
            assert reopened.status.cache_state == "reused"
            assert reopened.dataset_id == identity

    asyncio.run(scenario())
