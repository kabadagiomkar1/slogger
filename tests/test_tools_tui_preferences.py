"""Native settings at the approved consumer interaction seam."""

import asyncio
import json

import pytest

from slogger.tools import Investigation

pytest.importorskip("textual")


def test_settings_apply_session_changes_without_saving_and_explicitly_save_defaults(tmp_path):
    from textual.widgets import Input, Select, Switch

    from slogger.tools.tui.app import InvestigationApp
    from slogger.tools.tui.preferences import PreferencesStore

    source = tmp_path / "records.jsonl"
    source.write_text(
        json.dumps(
            {"timestamp": "2026-10-04T12:34:56.000Z", "message": "inspect", "duration_ms": 3}
        )
    )
    config = tmp_path / "config" / "preferences.json"

    async def scenario():
        with Investigation.open([source], cache_dir=tmp_path / "cache") as session:
            app = InvestigationApp(session, preferences_path=config)
            async with app.run_test(size=(130, 30)) as pilot:
                await pilot.press("p", "f10")
                assert app.screen.id == "settings"
                assert "Apply" in app.screen.query_one("#settings-apply").render_line(0).text
                app.screen.query_one("#preference-wrap", Switch).value = True
                app.screen.query_one("#preference-theme", Select).value = "light"
                app.screen.query_one("#preference-timestamp", Select).value = "datetime"
                app.screen.query_one("#preference-duration", Switch).value = True
                app.screen.query_one("#preference-json-lines", Switch).value = True
                app.screen.query_one("#preference-width", Input).value = "25"
                await pilot.press("ctrl+enter")
                assert app.current_theme.dark is False
                assert app.preferences.console.wrap is True
                assert app.preferences.console.timestamp_mode == "datetime"
                assert app.inspector_percent == 25
                assert app.pinned_identity == session.page(0, 1).identities[0]
                assert not config.exists()
                await pilot.press("ctrl+s")
                assert config.exists()
                loaded = PreferencesStore(config).load()
                assert loaded.console == app.preferences.console
                assert loaded.theme == "light"
                assert set(json.loads(config.read_text())) == {"version", "preferences"}
                await pilot.press("escape")
                assert app.focused is not None and app.focused.id == "console"

    asyncio.run(scenario())


def test_preferences_paths_and_loading_never_write_and_failed_save_preserves_defaults(
    tmp_path, monkeypatch
):
    import os

    import pytest

    from slogger.tools import ToolError
    from slogger.tools.tui.preferences import NativePreferences, PreferencesStore

    config = tmp_path / "preferences" / "defaults.json"
    store = PreferencesStore(config)
    assert store.load() == NativePreferences()
    assert not config.parent.exists()
    saved = NativePreferences(theme="light")
    store.save(saved)
    before = config.read_bytes()

    def failed_replace(*args):
        raise OSError("disk disconnected")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(ToolError, match="disk disconnected"):
        store.save(NativePreferences(theme="dark"))
    assert config.read_bytes() == before
    assert list(config.parent.iterdir()) == [config]
    config.write_text('{"version":2,"preferences":{}}')
    with pytest.raises(ToolError, match="unsupported"):
        store.load()


def test_narrow_settings_keyboard_access_errors_and_protected_clearing(tmp_path):
    from textual.widgets import Input, Static

    from slogger.tools.tui.app import InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text('{"message":"active"}')
    other = tmp_path / "other.jsonl"
    other.write_text('{"message":"inactive"}')
    cache = tmp_path / "cache"
    with Investigation.open([other], cache_dir=cache):
        pass

    async def scenario():
        with Investigation.open([source], cache_dir=cache) as session:
            app = InvestigationApp(session, preferences_path=tmp_path / "defaults.json")
            async with app.run_test(size=(55, 22)) as pilot:
                await pilot.press("f10")
                original = app.preferences
                app.screen.query_one("#preference-disk_bytes", Input).value = "0.001"
                await pilot.press("ctrl+enter")
                status = str(app.screen.query_one("#settings-status", Static).render())
                assert "unchanged" in status and "disk" in status
                assert app.preferences == original
                for _ in range(20):
                    await pilot.press("tab")
                    if app.focused is not None and app.focused.id == "clear-unused":
                        break
                assert app.focused is not None and app.focused.id == "clear-unused"
                await pilot.press("enter")
                assert "1 entries" in str(app.screen.query_one("#settings-status", Static).render())
                assert "protected" in str(app.screen.query_one("#settings-status", Static).render())
                assert session.page().records == [{"message": "active"}]
                assert app.screen.query_one("#clear-unused").region.width < 20
                snapshot = app.export_screenshot()
                assert "Settings" in snapshot and "protected" in snapshot
                (tmp_path / "settings-narrow.svg").write_text(snapshot)
                await pilot.press("escape", "f4")
                assert app.focused is not None and app.focused.id == "main-filter"

    asyncio.run(scenario())


def test_themes_keep_json_search_and_controls_readable_and_wrap_tree_records(tmp_path, monkeypatch):
    from textual.widgets import Input, Select

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp, JSONInspector
    from slogger.tools.tui.tree import TreeViewport

    monkeypatch.delenv("NO_COLOR", raising=False)
    source = tmp_path / "records.jsonl"
    source.write_text(
        json.dumps(
            {
                "message": "needle " * 60 + "TAIL",
                "level": "ERROR",
                "span": "request",
                "trace_id": "t",
                "span_id": "s",
            }
        )
    )

    async def scenario():
        with Investigation.open([source]) as session:
            app = InvestigationApp(session, preferences_path=tmp_path / "defaults.json")
            async with app.run_test(size=(130, 32)) as pilot:
                for theme in ("light", "dark"):
                    await pilot.press("f10")
                    app.screen.query_one("#preference-theme", Select).value = theme
                    await pilot.press("ctrl+enter", "escape", "f7")
                    app.query_one("#record-search", Input).value = "needle"
                    await pilot.pause()
                    console = app.query_one(ConsoleViewport)
                    assert any(
                        segment.style
                        and segment.style.bgcolor
                        and segment.style.bgcolor.name == "yellow"
                        for segment in console.render_line(0)
                    )
                    inspector = app.query_one(JSONInspector)
                    key_line = inspector.key_targets[0].line
                    assert "\n" not in inspector.render_line(key_line).text
                    assert any(
                        segment.style and segment.style.color
                        for segment in inspector.render_line(key_line)
                    )
                    assert all(
                        not segment.style
                        or not segment.style.bgcolor
                        or segment.style.bgcolor.name != "default"
                        for segment in inspector.render_line(key_line)
                    )
                    assert app.current_theme.dark is (theme == "dark")
                    screenshot = app.export_screenshot()
                    assert "needle" in screenshot and "Find" in screenshot
                    (tmp_path / f"preferences-{theme}-wide.svg").write_text(screenshot)
                    app.query_one("#record-search", Input).value = ""
                    await pilot.pause()
                await pilot.press("f3", "b")
                for _ in range(100):
                    if app.tree_mode:
                        break
                    await pilot.pause(0.02)
                assert app.tree_mode
                await pilot.press("f10")
                from textual.widgets import Switch

                app.screen.query_one("#preference-wrap", Switch).value = True
                await pilot.press("ctrl+enter", "escape")
                tree = app.query_one(TreeViewport)
                lines = [tree.render_line(index).text for index in range(tree.size.height)]
                assert sum("needle" in line for line in lines) > 2
                await pilot.press("pagedown")
                assert any(
                    "TAIL" in tree.render_line(index).text for index in range(tree.size.height)
                )
                await pilot.press("f10")
                await pilot.resize_terminal(55, 22)
                for _ in range(12):
                    await pilot.press("tab")
                assert app.focused is not None and app.focused.id == "preference-page_memory_bytes"
                assert app.focused.region.y >= 0 and app.focused.region.bottom <= 22
                screenshot = app.export_screenshot()
                assert "Settings" in screenshot
                (tmp_path / "preferences-dark-narrow.svg").write_text(screenshot)

    asyncio.run(scenario())
