"""Behavioral checks for the development command's deterministic guardrails."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev.py"


@pytest.fixture
def dev():
    spec = importlib.util.spec_from_file_location("dev_workflow", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_docs(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "docs", "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_documentation_check_reports_broken_local_link(tmp_path):
    (tmp_path / "README.md").write_text("[guide](docs/missing.md)\n")
    result = check_docs(tmp_path)
    assert result.returncode == 1
    assert "missing link target docs/missing.md" in result.stderr


def test_documentation_check_accepts_links_and_external_examples(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n")
    (tmp_path / "README.md").write_text(
        "[guide](guide.md#section) [web](https://example.com)\n"
        '```python\n"[example](generated.json)"\n```\n'
    )
    assert check_docs(tmp_path).returncode == 0


def test_documentation_check_catches_completed_migration_claimed_pending(tmp_path):
    old = tmp_path / ".scratch/old"
    new = tmp_path / ".scratch/new"
    old.mkdir(parents=True)
    new.mkdir()
    (old / "spec.md").write_text(
        "Status: implemented\nSuperseded by: ../new/spec.md\n"
        "The migration is not yet implemented.\n## Problem Statement\nHistorical details.\n"
    )
    (new / "spec.md").write_text("Status: implemented\n")
    result = check_docs(tmp_path)
    assert result.returncode == 1
    assert "superseding migration is implemented" in result.stderr


def test_documentation_check_catches_unresolved_and_cyclic_tickets(tmp_path):
    feature = tmp_path / ".scratch/feature"
    issues = feature / "issues"
    issues.mkdir(parents=True)
    (feature / "spec.md").write_text("Status: implemented\n")
    (issues / "01-first.md").write_text("Status: claimed\nBlocked by: 02\n")
    (issues / "02-second.md").write_text("Status: resolved\nBlocked by: 01\n")
    result = check_docs(tmp_path)
    assert result.returncode == 1
    assert "unresolved ticket" in result.stderr
    assert "cyclic ticket dependencies" in result.stderr


def test_documentation_check_accepts_completed_bold_ticket_metadata(tmp_path):
    feature = tmp_path / ".scratch/feature"
    issues = feature / "issues"
    issues.mkdir(parents=True)
    (feature / "spec.md").write_text("Status: implemented\n")
    (issues / "01-first.md").write_text("**Status:** resolved\n**Blocked by:** None\n")
    assert check_docs(tmp_path).returncode == 0


def test_preflight_rejects_environment_pointing_at_another_checkout(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "preflight",
            "--root",
            str(tmp_path),
            "--python",
            sys.executable,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert '"correct_checkout": false' in result.stdout


def test_setup_reuses_ready_environment_without_installing(tmp_path):
    if not all(importlib.util.find_spec(name) for name in ("ruff", "pyrefly")):
        pytest.skip("Idempotent setup requires a complete development environment")
    # A real installed environment over the same source tree, with no project
    # metadata in this temporary checkout: a pip install here would fail.
    (tmp_path / "src").symlink_to(SCRIPT.parents[1] / "src", target_is_directory=True)
    (tmp_path / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "setup", "--offline", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".dev/environment.json").exists()


def test_tui_preflight_rejects_missing_textual_before_checks(dev, monkeypatch, tmp_path):
    monkeypatch.setattr(
        dev,
        "environment",
        lambda *_: {
            "correct_checkout": True,
            "editable": True,
            "packages": {"pytest": "1", "ruff": "1", "pyrefly": "1", "textual": None},
        },
    )
    with pytest.raises(ValueError, match="setup --tui"):
        dev.checks(tmp_path, None, tui=True, fast=False, report_dir=None)
    assert not (tmp_path / ".dev/checks").exists()
    assert dev.preflight(tmp_path, None)["editable"]  # Base profile remains independent.


def test_tui_setup_adds_missing_extra_to_existing_environment(dev, monkeypatch, tmp_path):
    (tmp_path / ".venv").mkdir()
    info = {
        "correct_checkout": True,
        "editable": True,
        "packages": {"pytest": "1", "ruff": "1", "pyrefly": "1", "textual": None, "polars": "1"},
    }
    monkeypatch.setattr(dev, "environment", lambda *_: info)
    monkeypatch.setattr(dev, "preflight", lambda *_, **__: info)
    commands = []
    monkeypatch.setattr(dev, "run", lambda _, arguments, __: commands.append(arguments))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "setup", "--tui", "--polars", "--offline", "--root", str(tmp_path)],
    )
    assert dev.main() == 0
    assert commands == [
        [
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "-e",
            ".[dev,tools-polars,tools-tui]",
            "--no-index",
        ]
    ]


def test_tui_interaction_failure_stops_before_full_suite(dev, monkeypatch, tmp_path):
    info = {"python": sys.executable, "packages": {"polars": None}}
    monkeypatch.setattr(dev, "preflight", lambda *_, **__: info)
    monkeypatch.setattr(dev, "docs", lambda _: None)
    names = []

    def command(self, name, python, arguments, root):
        names.append(name)
        if name == "tui-interactions":
            assert "-x" in arguments and "tests/test_tools_tui_focus.py" in arguments
            raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(dev.CheckReport, "command", command)
    destination = tmp_path / "evidence"
    with pytest.raises(subprocess.CalledProcessError):
        dev.checks(SCRIPT.parents[1], None, tui=True, fast=False, report_dir=destination)
    assert names == ["ruff", "types", "tui-interactions"]
    report = json.loads((destination / "report.json").read_text())
    assert report["result"] == "failed" and report["revision"]


def test_report_distinguishes_whole_modules_and_individual_skips(dev, tmp_path, capsys):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_missing.py").write_text(
        'import pytest\npytest.importorskip("slogger_nonexistent_optional_dependency")\n'
        "def test_never_collected():\n    assert False\n"
    )
    (suite / "test_cases.py").write_text(
        "import pytest\n"
        "def test_ran():\n    assert True\n"
        '@pytest.mark.skip(reason="optional backend absent")\n'
        "def test_skipped():\n    assert False\n"
        '@pytest.mark.xfail(reason="known issue")\n'
        "def test_expected_failure():\n    assert False\n"
    )
    report = dev.CheckReport(SCRIPT.parents[1], tmp_path / "evidence", {}, "base")
    report.command(
        "probe",
        sys.executable,
        ["-m", "pytest", "-v", "-ra", str(suite), f"--junitxml={report.path / 'probe.xml'}"],
        suite,
    )
    check = json.loads((report.path / "report.json").read_text())["checks"][0]
    assert check["test_summary"] == {
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "xfailed": 1,
        "skipped_tests": 1,
        "skipped_modules": 1,
        "collection_errors": 0,
    }
    outcomes = {item["nodeid"]: item for item in check["test_outcomes"]}
    assert outcomes["test_cases.py::test_ran"]["outcome"] == "passed"
    assert outcomes["test_cases.py::test_skipped"]["reason"] == "optional backend absent"
    assert outcomes["test_missing.py"]["scope"] == "module"
    assert "slogger_nonexistent_optional_dependency" in outcomes["test_missing.py"]["reason"]
    assert all("never_collected" not in name for name in outcomes)
    terminal = capsys.readouterr().out
    assert "individual tests skipped: 1, whole modules not collected: 1" in terminal
    assert "Module not collected: test_missing.py" in terminal
    assert "their count is unknown" in terminal


def test_report_retains_output_command_and_exact_failure_case(dev, tmp_path):
    report = dev.CheckReport(SCRIPT.parents[1], tmp_path / "evidence", {}, "base")
    junit = report.path / "probe.xml"
    junit.write_text(
        '<testsuite><testcase classname="tests.test_ui" name="test_focus">'
        '<failure message="focus"/></testcase></testsuite>'
    )
    with pytest.raises(subprocess.CalledProcessError):
        report.command(
            "probe",
            sys.executable,
            ["-c", "print('failure detail', flush=True); raise SystemExit(3)"],
            SCRIPT.parents[1],
        )
    saved = json.loads((report.path / "report.json").read_text())
    check = saved["checks"][0]
    assert check["exit_code"] == 3
    assert check["failed_tests"] == ["tests.test_ui::test_focus"]
    assert check["command"][0] == sys.executable
    assert "failure detail" in (report.path / "probe.log").read_text()


def test_tui_fast_profile_still_requires_dependency_but_skips_tests(dev, monkeypatch, tmp_path):
    requirements = []
    monkeypatch.setattr(
        dev,
        "preflight",
        lambda *_, **kwargs: requirements.append(kwargs["tui"]) or {"python": sys.executable},
    )
    monkeypatch.setattr(dev, "docs", lambda _: None)
    names = []
    monkeypatch.setattr(dev.CheckReport, "command", lambda _, name, *__: names.append(name))
    dev.checks(SCRIPT.parents[1], None, tui=True, fast=True, report_dir=tmp_path / "evidence")
    assert requirements == [True]
    assert names == ["ruff", "types"]


@pytest.mark.parametrize("polars", [None, "1.44.2"])
def test_check_announces_coverage_and_names_every_test(dev, monkeypatch, tmp_path, capsys, polars):
    info = {"python": sys.executable, "packages": {"polars": polars}}
    monkeypatch.setattr(dev, "preflight", lambda *_, **__: info)
    monkeypatch.setattr(dev, "docs", lambda _: None)
    commands = {}
    monkeypatch.setattr(
        dev.CheckReport,
        "command",
        lambda _, name, python, arguments, root: commands.update({name: arguments}),
    )
    dev.checks(SCRIPT.parents[1], None, tui=True, fast=False, report_dir=tmp_path / "evidence")
    assert "-v" in commands["tui-interactions"] and "-v" in commands["suite"]
    terminal = capsys.readouterr().out
    assert "focused native interactions, then full suite" in terminal
    if polars:
        assert "Polars coverage: enabled (1.44.2)" in terminal
    else:
        assert "Polars coverage: unavailable" in terminal
        assert "setup --tui --polars" in terminal
