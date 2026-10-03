"""Core logging regressions retained after tooling retirement."""

import subprocess
import sys
import textwrap

import pytest

from slogger import capture_logs, get_logger, instrument


def test_reentrant_logging_and_callback_configuration_do_not_deadlock():
    script = textwrap.dedent("""
        import logging
        import threading
        from slogger import configure, get_logger
        from slogger.config import _EmissionGate, reset

        class Callback(logging.Handler):
            def emit(self, record):
                for change in (configure, reset):
                    try:
                        change()
                    except RuntimeError as error:
                        assert "during emission" in str(error)
                    else:
                        raise AssertionError("configuration must be rejected")
        configure(console=False, handlers=[Callback()])
        get_logger().info("callback")
        reset()
        gate = _EmissionGate()
        entered = threading.Event()
        def writer():
            with gate.write():
                entered.set()
        with gate.read():
            worker = threading.Thread(target=writer, daemon=True)
            worker.start()
            with gate._condition:
                assert gate._condition.wait_for(lambda: gate._waiting_writers == 1, timeout=1)
            with gate.read():
                assert not entered.is_set()
        worker.join(timeout=1)
        assert entered.is_set()
    """)
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("error", [False, True])
def test_span_logging_control_fields_are_preserved(error):
    log = get_logger("review.controls")
    with capture_logs() as records:
        if error:
            with pytest.raises(RuntimeError, match="original"):
                with log.span("child", stacklevel="field", exc_info="field", stack_info="field"):
                    raise RuntimeError("original")
        else:
            with log.span("child", stacklevel="field", exc_info="field", stack_info="field"):
                pass
    end = dict(records[-1])
    assert end["status"] == ("error" if error else "ok")
    assert end["stacklevel"] == end["exc_info"] == end["stack_info"] == "field"
    assert ("exception" in end) == error
    assert "stack" not in end
    assert end["func"] == "test_span_logging_control_fields_are_preserved"


def test_instrument_can_capture_logging_control_parameter():
    @instrument(capture="stacklevel")
    def work(stacklevel):
        return stacklevel

    with capture_logs() as records:
        assert work("value") == "value"
    assert dict(records[-1])["stacklevel"] == "value"
    assert records[-1]["func"] == "test_instrument_can_capture_logging_control_parameter"
