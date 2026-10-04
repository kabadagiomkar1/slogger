"""Fresh-interpreter optional dependency and installed-launch contracts."""

import subprocess
import sys
from importlib.metadata import distribution


def test_installed_native_launcher_and_extra():
    package = distribution("slogger")
    assert any(
        entry.name == "slogger-tui" and entry.value == "slogger.tools.tui:main"
        for entry in package.entry_points
    )
    assert any(
        'extra == "tools-tui"' in requirement and "textual" in requirement
        for requirement in package.requires or []
    )


def test_base_imports_and_headless_capture_work_without_optional_ui(tmp_path):
    code = """
import importlib.abc
import logging
from pathlib import Path
import sys

class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"textual", "polars", "rich"}:
            raise ModuleNotFoundError("Optional dependency intentionally absent", name=fullname)
sys.meta_path.insert(0, NoOptional())
handlers = list(logging.getLogger().handlers)
before = set(Path.cwd().iterdir())
import slogger
from slogger.tools import Investigation, ToolError, scan
from slogger.tools.tui import launch
assert list(logging.getLogger().handlers) == handlers
assert set(Path.cwd().iterdir()) == before
assert scan([{"x":1}]).execute().records == [{"x":1}]
source = Path("input.jsonl")
source.write_text('{"x":1}\\n')
with Investigation.open([source]) as session:
    assert session.page().records == [{"x":1}]
try:
    launch([source])
except ToolError as error:
    assert error.code == "dependency_missing"
    assert "tools-tui" in str(error)
    assert isinstance(error.__cause__, ModuleNotFoundError)
else:
    raise AssertionError("missing native dependency was not reported")
assert "textual" not in sys.modules
assert "polars" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
