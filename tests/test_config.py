import io
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import slogger
from slogger import get_logger
from slogger.config import configure, is_configured, reset
from slogger.filters import ContextFilter

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(slogger.__file__).resolve().parent


def test_tests_import_the_src_layout_package():
    # src/ layout keeps the checkout's package off sys.path until installed.
    assert PACKAGE_ROOT == ROOT / "src" / "slogger"
    assert "src" in Path(slogger.__file__).resolve().parts


def test_import_creates_no_handlers_or_files(tmp_path):
    env = os.environ.copy()
    # Prefer the installed/editable package. Do not put the repo root on
    # PYTHONPATH — that would resurrect the pre-src flat layout.
    pythonpath = [
        entry
        for entry in env.get("PYTHONPATH", "").split(os.pathsep)
        if entry and Path(entry).resolve() not in {ROOT, ROOT / "src"}
    ]
    if pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    else:
        env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging, os, slogger\n"
                "print(slogger.__file__)\n"
                "print(len(logging.getLogger().handlers))\n"
                "print(slogger.config.is_configured())\n"
                "print(sorted(os.listdir('.')))\n"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    module_path, handler_count, configured, listing = completed.stdout.splitlines()
    assert Path(module_path).resolve().parent == PACKAGE_ROOT
    assert handler_count == "0"
    assert configured == "False"
    assert listing == "[]"


def test_lazy_default_is_console_only():
    reset()
    before = set(logging.getLogger().handlers)
    assert is_configured() is False
    get_logger("lazy.child").warning("hello lazy")
    assert is_configured() is True
    installed = [handler for handler in logging.getLogger().handlers if handler not in before]
    assert len(installed) == 1
    assert isinstance(installed[0], logging.StreamHandler)
    assert not isinstance(installed[0], logging.FileHandler)


def test_concurrent_first_records_install_one_default_handler():
    reset()
    root = logging.getLogger()
    before = set(root.handlers)
    barrier = threading.Barrier(8)
    logger = get_logger("lazy.concurrent")

    def emit():
        barrier.wait()
        logger.warning("once configured")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: emit(), range(8)))

    installed = [handler for handler in root.handlers if handler not in before]
    assert len(installed) == 1


def test_configure_is_idempotent_and_keeps_foreign_handlers():
    foreign = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(foreign)
    try:
        first = io.StringIO()
        second = io.StringIO()
        configure(level=logging.DEBUG, console=True, console_stream=first)
        configure(level=logging.DEBUG, console=True, console_stream=second)
        installed = [
            handler
            for handler in root.handlers
            if getattr(handler, "stream", None) is second
        ]
        assert len(installed) == 1
        assert foreign in root.handlers
        get_logger("slogger").info("after")
        assert "after" in second.getvalue()
        assert first.getvalue() == ""
    finally:
        if foreign in root.handlers:
            root.removeHandler(foreign)


def test_passed_handlers_are_additive():
    sink = io.StringIO()
    extra = logging.StreamHandler(sink)
    configure(level=logging.DEBUG, console=True, console_stream=io.StringIO(), handlers=[extra])
    assert extra in logging.getLogger().handlers
    get_logger("slogger").info("both")
    assert "both" in sink.getvalue()


def test_capture_stdlib_false_limits_output_to_the_slogger_tree():
    sink = io.StringIO()
    configure(
        level=logging.DEBUG,
        console=True,
        console_stream=sink,
        console_level=logging.DEBUG,
        capture_stdlib=False,
    )
    assert logging.getLogger("slogger").propagate is False
    assert not any(
        getattr(handler, "stream", None) is sink for handler in logging.getLogger().handlers
    )
    get_logger("slogger").info("yes")
    get_logger("slogger.child").info("child")
    logging.getLogger("other").info("no")
    text = sink.getvalue()
    assert "yes" in text
    assert "child" in text
    assert "no" not in text

    configure(level=logging.DEBUG, console=True, console_stream=io.StringIO(), capture_stdlib=True)
    assert logging.getLogger("slogger").propagate is True


def test_reset_restores_only_logger_state_owned_by_slogger():
    root = logging.getLogger()
    named = logging.getLogger("slogger")
    third_party = logging.getLogger("third.party.config")
    old_root = (root.level, root.propagate)
    old_named = (named.level, named.propagate)
    old_third_party = (third_party.level, third_party.propagate)
    try:
        third_party.setLevel(logging.ERROR)
        third_party.propagate = False

        configure(level=logging.DEBUG, console=False, capture_stdlib=True)
        reset()

        assert (root.level, root.propagate) == old_root
        assert (named.level, named.propagate) == old_named
        assert third_party.level == logging.ERROR
        assert logging.getLogger("third.party.config").propagate is False
    finally:
        third_party.setLevel(old_third_party[0])
        third_party.propagate = old_third_party[1]


def test_switching_capture_mode_restores_the_previous_target():
    root = logging.getLogger()
    named = logging.getLogger("slogger")
    old_root = (root.level, root.propagate)
    old_named = (named.level, named.propagate)

    configure(level=logging.DEBUG, console=False, capture_stdlib=True)
    configure(level=logging.ERROR, console=False, capture_stdlib=False)
    assert (root.level, root.propagate) == old_root
    assert named.level == logging.ERROR
    assert named.propagate is False

    configure(level=logging.INFO, console=False, capture_stdlib=True)
    assert (named.level, named.propagate) == old_named
    assert root.level == logging.INFO


def test_reset_preserves_preexisting_caller_handler_and_its_filters():
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        configure(level=logging.DEBUG, console=False, handlers=[handler])
        added = [item for item in handler.filters if isinstance(item, ContextFilter)]
        assert len(added) == 1

        reset()

        assert handler in root.handlers
        assert not any(isinstance(item, ContextFilter) for item in handler.filters)
    finally:
        root.removeHandler(handler)


def test_failed_reconfiguration_keeps_the_previous_configuration(tmp_path):
    root = logging.getLogger()
    named = logging.getLogger("slogger")
    sink = io.StringIO()
    configure(level=logging.DEBUG, console=True, console_stream=sink)
    configured_root = (root.level, root.propagate, list(root.handlers))
    configured_named = (named.level, named.propagate, list(named.handlers))
    missing_parent = tmp_path / "missing" / "app.log"

    with pytest.raises(FileNotFoundError):
        configure(
            level=logging.DEBUG,
            console=True,
            console_stream=io.StringIO(),
            json_file=str(missing_parent),
        )

    assert is_configured() is True
    assert (root.level, root.propagate, root.handlers) == configured_root
    assert (named.level, named.propagate, named.handlers) == configured_named
    get_logger("slogger").info("old configuration survived")
    assert "old configuration survived" in sink.getvalue()


def test_reset_does_not_overwrite_application_changes_after_configure():
    root = logging.getLogger()
    named = logging.getLogger("slogger")
    old_root_level = root.level
    old_named_propagate = named.propagate
    configure(level=logging.DEBUG, console=False, capture_stdlib=True)

    root.setLevel(logging.ERROR)
    named.propagate = False
    reset()

    assert root.level == logging.ERROR
    assert logging.getLogger("slogger").propagate is False
    # Leave the process-level objects as the autouse fixture found them.
    root.setLevel(old_root_level)
    named.propagate = old_named_propagate


def test_reconfigure_waits_for_in_flight_emission():
    entered = threading.Event()
    release = threading.Event()
    reconfigured = threading.Event()

    class BlockingHandler(logging.Handler):
        def emit(self, record):
            entered.set()
            assert release.wait(timeout=2)

    configure(level=logging.DEBUG, console=False, handlers=[BlockingHandler()])
    emitter = threading.Thread(target=get_logger("slogger").info, args=("blocked",))
    emitter.start()
    assert entered.wait(timeout=2)

    def replace():
        configure(level=logging.DEBUG, console=False)
        reconfigured.set()

    replacer = threading.Thread(target=replace)
    replacer.start()
    assert not reconfigured.wait(timeout=0.05)
    release.set()
    emitter.join(timeout=2)
    replacer.join(timeout=2)
    assert reconfigured.is_set()


def test_json_file_handler(tmp_path):
    path = tmp_path / "app.log"
    configure(
        level=logging.DEBUG,
        console=False,
        json_file=str(path),
        json_file_level=logging.DEBUG,
    )
    get_logger("file").info("persisted", n=1)
    # Close the rotating handler so the file can be read back on every platform.
    reset()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"message": "persisted"' in lines[0]
    assert '"n": 1' in lines[0]
    assert not isinstance(
        logging.getLogger().handlers[0] if logging.getLogger().handlers else None,
        logging.handlers.TimedRotatingFileHandler,
    )


def test_attachment_failure_restores_previous_configuration(tmp_path):
    class RejectFilter(logging.Handler):
        def addFilter(self, filter):
            raise RuntimeError("cannot attach filter")

    sink = io.StringIO()
    path = tmp_path / "surviving.log"
    configure(
        level=logging.DEBUG, console_stream=sink, span_events=False, json_file=str(path)
    )
    root = logging.getLogger()
    previous = (root.level, list(root.handlers))
    with pytest.raises(RuntimeError, match="cannot attach filter"):
        configure(console=False, handlers=[RejectFilter()], capture_stdlib=False)
    assert is_configured()
    assert (root.level, root.handlers) == previous
    get_logger("slogger").info("survived")
    assert "survived" in sink.getvalue()
    assert "survived" in path.read_text()
    from slogger.config import span_events_enabled
    assert not span_events_enabled()


def test_reconfiguration_reuses_owned_handler_until_reset(tmp_path):
    path = tmp_path / "reused.log"
    configure(console=False, json_file=str(path))
    owned = next(
        handler for handler in logging.getLogger().handlers
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler)
    )
    original_stream = owned.stream
    configure(console=False, handlers=[owned])
    get_logger("slogger").info("reused")
    assert owned.stream is original_stream
    assert "reused" in path.read_text()
    reset()
    assert owned.stream is None
