"""Independent populations remain explicit immutable headless view scopes."""

import json

from slogger.tools import Field, Investigation, parse_filter


def test_independent_aggregate_inputs_preserve_presence_occurrences_and_scope(tmp_path):
    source = tmp_path / "populations.jsonl"
    rows = [
        {"keep": True, "v": 0},
        {"keep": True, "v": False},
        {"keep": True, "v": None},
        {"keep": True},
        {"keep": False, "v": 7, "__scope": "application"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    with Investigation.open([source, source]) as session:
        main = session.filter(parse_filter("keep == true"), request_generation=1).wait(10)
        independent = session.filter(parse_filter("keep == false"), request_generation=2).wait(10)
        assert main is not None and independent is not None
        categorical = session.count_values(("v",), input_view=main, request_generation=3).wait(10)
        numeric = session.summarize_values(
            ("v",), metrics=("count", "sum"), input_view=independent, request_generation=4
        ).wait(10)
        assert categorical is not None and numeric is not None
        assert categorical.scope.input_scope == main.view_scope
        assert numeric.scope.input_scope == independent.view_scope
        assert categorical.scope.presence == Field("v").exists()
        assert categorical.page().records == [
            {"value": 0, "count": 2},
            {"value": False, "count": 2},
            {"value": None, "count": 2},
        ]
        assert numeric.page().records == [{"count": 2, "sum": 14}]
        assert numeric.page().origins == [None]
        assert independent.page(0, 1).records == [rows[-1]]
        main.close()
        independent.close()
        assert categorical.page().records[0] == {"value": 0, "count": 2}
        assert numeric.page().records == [{"count": 2, "sum": 14}]
        assert session.resources.reserved_disk_bytes == 0


def test_filter_drains_results_that_arrive_between_empty_poll_and_worker_exit(
    tmp_path, monkeypatch
):
    import subprocess
    import threading
    from multiprocessing.connection import Connection

    source = tmp_path / "poll-race.jsonl"
    source.write_text('{"keep":true,"v":2}\n{"keep":false,"v":7}')
    processes = []
    crossed = threading.Event()
    original_popen, original_poll = subprocess.Popen, Connection.poll

    def capture_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    def delay_empty_pipe_snapshot(connection, timeout=0.0):
        if not crossed.is_set() and not original_poll(connection, 0):
            crossed.set()
            # This is an actual empty IPC observation. The real child writes its
            # small result and exits before the caller checks the exit status.
            assert processes[0].wait(5) == 0
            return False
        return original_poll(connection, timeout)

    with Investigation.open([source]) as session:
        monkeypatch.setattr(subprocess, "Popen", capture_process)
        monkeypatch.setattr(Connection, "poll", delay_empty_pipe_snapshot)
        job = session.filter(parse_filter("keep == true"), request_generation=7)
        view = job.wait(10)
        assert crossed.is_set()
        assert view is not None, job.diagnostics
        assert job.status.phase == "complete"
        assert view.scope.request_generation == 7
        assert view.page().records == [{"keep": True, "v": 2}]
        result = session.summarize_values(("v",), input_view=view, metrics=("count", "sum")).wait(
            10
        )
        assert result is not None
        assert result.page().records == [{"count": 1, "sum": 2}]
        assert session.resources.reserved_disk_bytes == 0
