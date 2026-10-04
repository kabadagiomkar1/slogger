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
