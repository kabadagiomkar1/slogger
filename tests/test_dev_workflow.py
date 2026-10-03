"""Behavioral checks for the development command's deterministic guardrails."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev.py"


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
