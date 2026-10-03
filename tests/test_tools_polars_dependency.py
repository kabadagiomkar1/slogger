"""Optional dependency absence is tested in a fresh interpreter."""

import subprocess
import sys


def test_base_imports_do_not_load_polars_and_missing_dependency_is_explicit():
    code = """
import importlib.abc
import sys
import slogger
from slogger.tools import scan, ToolError
assert "polars" not in sys.modules
class BlockPolars(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "polars":
            raise ModuleNotFoundError("Polars intentionally absent")
sys.meta_path.insert(0, BlockPolars())
assert scan([{"x": 1}]).execute().records == [{"x": 1, "_id": "mem:0"}]
for action in (scan([]).execute, scan([]).explain):
    try:
        action(backend="polars")
    except ToolError as error:
        assert error.code == "dependency_missing"
        assert isinstance(error.__cause__, ModuleNotFoundError)
    else:
        raise AssertionError("missing dependency was not reported")
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
