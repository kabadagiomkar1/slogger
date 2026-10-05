"""Retired native populations remain owned until deletion really settles."""

import asyncio
import time
from pathlib import Path

import pytest

from slogger.tools import Investigation, RecordView, ToolError

pytest.importorskip("textual")


@pytest.mark.parametrize("population", ["aggregate", "main", "detached", "reattach"])
def test_native_replacement_retains_failed_retirement_and_retries(
    tmp_path, monkeypatch, population
):
    from textual.widgets import Input

    from slogger.tools.tui.app import ConsoleViewport, InvestigationApp

    source = tmp_path / "records.jsonl"
    source.write_text('{"a":"old","b":"new","keep":true}\n{"a":"old","b":"other","keep":false}\n')
    unlink = Path.unlink
    rejected = False
    reject = True
    previous = None

    def reject_retired(path, *args, **kwargs):
        nonlocal rejected
        if reject and previous is not None and path == previous._path:
            rejected = True
            raise OSError("controlled retired allocation deletion failure")
        return unlink(path, *args, **kwargs)

    async def settled(pilot, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            await pilot.pause(0.01)
        assert predicate()

    async def scenario():
        nonlocal previous, reject
        with Investigation.open([source], storage_dir=tmp_path / "managed") as owner:
            app = InvestigationApp(owner, preferences_path=tmp_path / "preferences.json")
            async with app.run_test(size=(130, 35)) as pilot:
                await settled(
                    pilot, lambda: app.discovery_job is not None and app.discovery_job.done
                )
                if population == "aggregate":
                    app.request_aggregate(("a",), infer_metrics=False)
                    await settled(pilot, lambda: app.aggregate_result is not None)
                    previous = app.aggregate_result
                elif population == "main":
                    await pilot.press("f4")
                    app.query_one("#main-filter", Input).focus()
                    app.query_one("#main-filter", Input).value = "keep == true"
                    await pilot.press("enter")
                    await settled(pilot, lambda: app.filtered_view is not None)
                    previous = app.filtered_view
                else:
                    app.action_focus_aggregate_filter()
                    await settled(pilot, lambda: app.detached_view is not None)
                    previous = app.detached_view
                assert previous is not None
                old_allocation = previous._path.stat().st_blocks * 512
                monkeypatch.setattr(Path, "unlink", reject_retired)
                if population == "aggregate":
                    app.request_aggregate(("b",), infer_metrics=False)
                elif population == "main":
                    app.query_one("#main-filter", Input).focus()
                    app.query_one("#main-filter", Input).value = "keep == false"
                    await pilot.press("enter")
                elif population == "detached":
                    entry = app.query_one("#aggregate-filter", Input)
                    entry.focus()
                    entry.focus()
                    entry.value = "keep == false"
                    await pilot.press("enter")
                else:
                    app.action_reattach_aggregate()
                await settled(pilot, lambda: rejected)
                assert previous in app._retired_handles
                assert previous._path.exists()
                assert "cleanup_failed" in app.capture_heading()
                assert owner.status.complete and owner.page(0, 1).records[0]["a"] == "old"
                with pytest.raises(ToolError, match="closed"):
                    previous.page()
                if population == "aggregate":
                    assert app.aggregate_result is not None
                    assert app.aggregate_result.page().records == [
                        {"value": "new", "count": 1},
                        {"value": "other", "count": 1},
                    ]
                    assert app.pending_aggregate is None
                elif population == "main":
                    assert app.filtered_view is not None
                    assert app.filtered_view.page().records[0]["keep"] is False
                    assert app.pending_filter is None
                    assert app.query_one(ConsoleViewport).view is app.filtered_view
                elif population == "detached":
                    assert app.detached_view is not None
                    assert app.detached_view.page().records[0]["keep"] is False
                    assert app.pending_detached_filter is None
                else:
                    assert app.aggregate_follows_main and app.detached_view is None
                if isinstance(previous, RecordView):
                    assert previous._leases == 0
                before = owner.resources.disk_bytes
                reject = False
                app.action_retry_cleanup()
                assert not previous._path.exists() and not app._retired_handles
                assert owner.resources.disk_bytes <= before - old_allocation
                assert owner.resources.reserved_disk_bytes == 0
                previous.close()
                await pilot.press("f3", "down", "home")
                assert owner.status.complete

    asyncio.run(scenario())
