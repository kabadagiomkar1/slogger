import builtins
import threading
from pathlib import Path

import pytest

from slogger import capture_logs
from slogger.config import reset

REPO_ROOT = Path(__file__).resolve().parent.parent


def fixture_path(name: str) -> str:
    """Return a fixture path relative to the repository root."""
    return f"tests/fixtures/logs/{name}"


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    reset()


@pytest.fixture
def records():
    reset()
    with capture_logs() as found:
        yield found


@pytest.fixture
def blocked_source(tmp_path, monkeypatch, request):
    """Delay a real filesystem read so the published prefix is observable."""
    source = tmp_path / "records.jsonl"
    source.write_text(
        "".join('{"n":' + str(n) + ',"message":"' + "x" * 300 + '"}\n' for n in range(1000))
    )
    entered = threading.Event()
    release = threading.Event()
    real_open = builtins.open

    class DelayedFile:
        def __init__(self, stream):
            self.stream = stream
            self.reads = 0
            self.verifying = False
            self.delayed = False

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def seek(self, offset, whence=0):
            self.verifying = offset == 0 and whence == 0
            return self.stream.seek(offset, whence)

        def read(self, size=-1):
            self.reads += 1
            wait_here = (
                self.verifying
                if getattr(request, "param", None) == "verification"
                else self.reads == 2
            )
            if wait_here and not self.delayed:
                self.delayed = True
                entered.set()
                if not release.wait(10):
                    raise OSError("test filesystem read timed out")
            return self.stream.read(size)

    def delayed_open(file, mode="r", *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        return DelayedFile(stream) if str(file) == str(source) and mode == "rb" else stream

    monkeypatch.setattr(builtins, "open", delayed_open)
    yield source, entered, release
    release.set()
