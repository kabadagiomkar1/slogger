#!/usr/bin/env python3
"""Development preflight, checks, and documentation consistency (stdlib only)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TUI_INTERACTIONS = [
    "tests/test_tools_tui_focus.py",
    "tests/test_tools_tui_console.py",
    "tests/test_tools_tui_completion.py",
    "tests/test_tools_tui_preferences.py",
    "tests/test_tools_tui_search.py",
    "tests/test_tools_tui_aggregates.py",
]
PROBE = """
import importlib.metadata as m, importlib.util as u, json, sys
packages = {}
for name in ('pytest', 'ruff', 'pyrefly', 'polars', 'textual'):
    try: packages[name] = m.version(name)
    except m.PackageNotFoundError: packages[name] = None
spec = u.find_spec('slogger')
try:
    direct = json.loads(m.distribution('slogger').read_text('direct_url.json') or '{}')
except m.PackageNotFoundError:
    direct = {}
print(json.dumps({'python': sys.executable, 'version': sys.version.split()[0],
                 'slogger': spec.origin if spec else None, 'packages': packages,
                 'editable': bool(direct.get('dir_info', {}).get('editable'))}))
"""


def environment(root: Path, python: str | None) -> dict:
    registration = root / ".dev/environment.json"
    if python is None:
        python = os.environ.get("SLOGGER_PYTHON")
    if python is None and registration.exists():
        python = json.loads(registration.read_text())["python"]
    if python is None:
        local = root / ".venv/bin/python"
        python = str(local) if local.exists() else sys.executable
    result = subprocess.run([python, "-c", PROBE], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    expected = root / "src/slogger/__init__.py"
    info["checkout"] = str(root)
    info["correct_checkout"] = bool(
        info["slogger"] and Path(info["slogger"]).resolve() == expected.resolve()
    )
    return info


def preflight(root: Path, python: str | None, register: bool = False, tui: bool = False) -> dict:
    info = environment(root, python)
    print(json.dumps(info, indent=2), flush=True)
    missing = [name for name in ("pytest", "ruff", "pyrefly") if not info["packages"][name]]
    if tui and not info["packages"]["textual"]:
        missing.append("textual (install the tools-tui extra or run setup --tui)")
    if not info["correct_checkout"] or not info["editable"] or missing:
        raise ValueError(
            "Environment is not ready: use an editable install of this checkout "
            f"with the dev extra. Missing tools: {', '.join(missing) or 'none'}."
        )
    if register:
        destination = root / ".dev/environment.json"
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps({"python": info["python"]}, indent=2) + "\n")
    return info


def field(text: str, name: str) -> str | None:
    match = re.search(rf"^(?:\*\*)?{re.escape(name)}:(?:\*\*)? (.+)$", text, re.MULTILINE)
    return match[1].strip() if match else None


def dependency_errors(graph: dict[str, list[str]], label: str) -> list[str]:
    errors = []
    visited: set[str] = set()
    active: set[str] = set()

    def visit(number: str) -> None:
        if number in active:
            errors.append(f"{label}: cyclic ticket dependencies at {number}")
            return
        if number in visited:
            return
        active.add(number)
        for blocker in graph.get(number, []):
            visit(blocker)
        active.remove(number)
        visited.add(number)

    for number, blockers in graph.items():
        if any(blocker not in graph for blocker in blockers):
            errors.append(f"{label}: ticket {number} has unknown blocker")
        visit(number)
    return errors


def documentation_errors(root: Path) -> list[str]:
    errors = []
    paths = set(root.glob("*.md")) | set((root / "docs").rglob("*.md"))
    paths |= set((root / ".scratch").rglob("*.md"))
    for path in sorted(paths):
        text = path.read_text()
        # Examples and historical references may deliberately name removed files.
        historical = "historical" in text[:350].lower()
        if not historical:
            prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            for target in re.findall(r"\]\(([^)\n]+)\)", prose):
                target = target.split(' "', 1)[0].strip().strip("<>")
                target = unquote(target.split("#", 1)[0])
                if not target or target.startswith("/") or re.match(r"\w[\w+.-]*:", target):
                    continue
                if not (path.parent / target).exists():
                    errors.append(f"{path.relative_to(root)}: missing link target {target}")
        successor = field(text, "Superseded by")
        if successor:
            replacement = path.parent / successor
            if not replacement.is_file():
                errors.append(f"{path.relative_to(root)}: missing superseding specification")
            elif field(replacement.read_text(), "Status") == "implemented":
                prelude = text.split("\n## ", 1)[0]
                if re.search(r"not yet implemented|forthcoming", prelude, re.IGNORECASE):
                    errors.append(f"{path.relative_to(root)}: superseding migration is implemented")
    for spec in sorted((root / ".scratch").glob("*/spec.md")):
        tickets = sorted((spec.parent / "issues").glob("[0-9][0-9]-*.md"))
        graph = {}
        for ticket in tickets:
            text = ticket.read_text()
            number = ticket.name[:2]
            blocked = field(text, "Blocked by")
            graph[number] = re.findall(r"\b\d{2}\b", blocked or "")
            if (
                field(spec.read_text(), "Status") == "implemented"
                and field(text, "Status") != "resolved"
            ):
                errors.append(f"{ticket.relative_to(root)}: implemented spec has unresolved ticket")
        errors.extend(dependency_errors(graph, str(spec.relative_to(root))))
    return errors


def docs(root: Path) -> None:
    errors = documentation_errors(root)
    if errors:
        raise ValueError("\n".join(errors))
    print("Documentation links, supersession notices, and ticket lifecycle passed.", flush=True)


def run(python: str, arguments: list[str], root: Path) -> None:
    print("Running:", python, *arguments, flush=True)
    subprocess.run([python, *arguments], cwd=root, check=True)


def junit_outcomes(path: Path, root: Path) -> list[dict]:
    """Separate collection skips from test outcomes in pytest's JUnit report."""
    outcomes = []
    for case in ET.parse(path).iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        skipped, failure, error = case.find("skipped"), case.find("failure"), case.find("error")
        module = not classname
        components = (classname or name).split(".")
        nodeid = f"{classname}::{name}" if classname else name
        for length in range(len(components), 0, -1):
            candidate = Path(*components[:length]).with_suffix(".py")
            if (root / candidate).is_file():
                nodeid = candidate.as_posix()
                if not module:
                    nodeid += "::" + "::".join([*components[length:], name])
                break
        reason = ""
        if skipped is not None:
            outcome = "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
            reason = skipped.get("message", "")
            if reason == "collection skipped" and skipped.text:
                try:
                    location = ast.literal_eval(skipped.text)
                    if isinstance(location, tuple) and len(location) == 3:
                        reason = str(location[2]).removeprefix("Skipped: ")
                except (ValueError, SyntaxError):
                    reason = skipped.text
        elif failure is not None:
            outcome, reason = "failed", failure.get("message", "")
        elif error is not None:
            outcome, reason = "error", error.get("message", "")
        else:
            outcome = "passed"
        outcomes.append(
            {
                "nodeid": nodeid,
                "scope": "module" if module else "test",
                "outcome": outcome,
                "reason": reason,
            }
        )
    return outcomes


def summarize_tests(outcomes: list[dict]) -> dict:
    summary = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "xfailed": 0,
        "skipped_tests": 0,
        "skipped_modules": 0,
        "collection_errors": 0,
    }
    for item in outcomes:
        if item["outcome"] == "skipped":
            key = "skipped_modules" if item["scope"] == "module" else "skipped_tests"
        elif item["outcome"] == "error":
            key = "collection_errors" if item["scope"] == "module" else "errors"
        else:
            key = item["outcome"]
        summary[key] += 1
    return summary


class CheckReport:
    """Stream checks to the terminal and retain revision-scoped evidence."""

    def __init__(self, root: Path, destination: Path | None, info: dict, profile: str):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = destination or root / ".dev/checks" / stamp
        self.path.mkdir(parents=True, exist_ok=False)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True)
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
        self.data = {
            "revision": revision.strip(),
            "working_tree_status": status,
            "environment": info,
            "profile": profile,
            "checks": [],
            "result": "running",
        }
        self.save()
        print(f"Check evidence: {self.path}", flush=True)

    def save(self) -> None:
        (self.path / "report.json").write_text(json.dumps(self.data, indent=2) + "\n")

    def command(self, name: str, python: str, arguments: list[str], root: Path) -> None:
        command = [python, *arguments]
        print("Running:", *command, flush=True)
        started = time.monotonic()
        with (self.path / f"{name}.log").open("w") as log:
            with subprocess.Popen(
                command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                code = process.wait()
        failures = []
        outcomes = []
        junit = self.path / f"{name}.xml"
        if junit.exists():
            outcomes = junit_outcomes(junit, root)
            for case in ET.parse(junit).iter("testcase"):
                if case.find("failure") is not None or case.find("error") is not None:
                    failures.append(f"{case.get('classname')}::{case.get('name')}")
        summary = summarize_tests(outcomes) if junit.exists() else None
        if summary is not None:
            print(
                f"{name}: {summary['passed']} passed, {summary['failed']} failed, "
                f"{summary['errors']} errors, {summary['xfailed']} expected failures; "
                f"individual tests skipped: {summary['skipped_tests']}, "
                f"whole modules not collected: {summary['skipped_modules']}, "
                f"{summary['collection_errors']} collection errors.",
                flush=True,
            )
            for item in outcomes:
                if item["scope"] == "module" and item["outcome"] == "skipped":
                    print(
                        f"  Module not collected: {item['nodeid']} — {item['reason']}", flush=True
                    )
            if summary["skipped_modules"]:
                print(
                    "  Tests inside skipped modules were not collected; their count is unknown "
                    "in this environment.",
                    flush=True,
                )
        self.data["checks"].append(
            {
                "name": name,
                "command": command,
                "exit_code": code,
                "seconds": time.monotonic() - started,
                "failed_tests": failures,
                "test_summary": summary,
                "test_outcomes": outcomes,
            }
        )
        self.save()
        if code:
            raise subprocess.CalledProcessError(code, command)


def checks(
    root: Path, python: str | None, *, tui: bool, fast: bool, report_dir: Path | None
) -> None:
    info = preflight(root, python, tui=tui)
    report = CheckReport(root, report_dir, info, "tui" if tui else "base")
    if fast:
        print("Test execution disabled (--fast).", flush=True)
    else:
        print(
            "Test plan: "
            + ("focused native interactions, then full suite" if tui else "full suite"),
            flush=True,
        )
        polars = info["packages"].get("polars")
        enable = "python3 scripts/dev.py setup " + ("--tui " if tui else "") + "--polars"
        print(
            f"Polars coverage: enabled ({polars})"
            if polars
            else "Polars coverage: unavailable; Polars-specific modules and cases will skip. "
            f"Enable with: {enable}",
            flush=True,
        )
    try:
        docs(root)
        report.data["checks"].append({"name": "docs", "exit_code": 0})
        report.command(
            "ruff",
            info["python"],
            ["-m", "ruff", "check", "src", "tests", "examples", "benchmarks", "scripts"],
            root,
        )
        report.command(
            "types",
            info["python"],
            ["-m", "pyrefly", "check", "--python-interpreter-path", info["python"]],
            root,
        )
        if not fast:
            if tui:
                report.command(
                    "tui-interactions",
                    info["python"],
                    [
                        "-m",
                        "pytest",
                        "-x",
                        "-v",
                        "-ra",
                        *TUI_INTERACTIONS,
                        f"--junitxml={report.path / 'tui-interactions.xml'}",
                    ],
                    root,
                )
            report.command(
                "suite",
                info["python"],
                ["-m", "pytest", "-v", "-ra", f"--junitxml={report.path / 'suite.xml'}"],
                root,
            )
        report.data["result"] = "passed"
    except BaseException as error:
        report.data["result"] = "failed"
        report.data["error"] = repr(error)
        raise
    finally:
        report.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "setup", "check", "docs", "install-hook"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--python", help="Interpreter for preflight/check; base interpreter for setup"
    )
    parser.add_argument(
        "--register", action="store_true", help="Remember a verified environment per checkout"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Skip pytest; run docs, Ruff, and Pyrefly"
    )
    parser.add_argument(
        "--polars", action="store_true", help="Include the optional backend during setup"
    )
    parser.add_argument("--offline", action="store_true", help="Use pip --no-index during setup")
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Require Textual; setup installs it, check runs interaction tests first",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="New check evidence directory (default: .dev/checks/<UTC time>)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "docs":
            docs(root)
        elif args.command == "setup":
            destination = root / ".venv"
            if destination.exists():
                existing = environment(root, str(destination / "bin/python"))
                if args.python:
                    requested = environment(root, args.python)
                    if existing["version"].split(".")[:2] != requested["version"].split(".")[:2]:
                        raise ValueError(
                            "Existing .venv has a different Python version; "
                            "use a fresh checkout environment."
                        )
                ready = (
                    existing["correct_checkout"]
                    and existing["editable"]
                    and all(existing["packages"][name] for name in ("pytest", "ruff", "pyrefly"))
                )
                if (
                    ready
                    and (not args.polars or existing["packages"]["polars"])
                    and (not args.tui or existing["packages"]["textual"])
                ):
                    preflight(root, str(destination / "bin/python"), register=True, tui=args.tui)
                    return 0
            if not destination.exists():
                run(args.python or sys.executable, ["-m", "venv", str(destination)], root)
            python = str(destination / "bin/python")
            extras = ",".join(
                ["dev"]
                + (["tools-polars"] if args.polars else [])
                + (["tools-tui"] if args.tui else [])
            )
            arguments = ["-m", "pip", "install", "--no-cache-dir", "-e", f".[{extras}]"]
            if args.offline:
                arguments.append("--no-index")
            run(python, arguments, root)
            preflight(root, python, register=True, tui=args.tui)
        elif args.command == "preflight":
            preflight(root, args.python, register=args.register, tui=args.tui)
        elif args.command == "install-hook":
            preflight(root, args.python, register=True)
            hooks = subprocess.run(
                ["git", "config", "--get", "core.hooksPath"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if hooks.stdout.strip() not in ("", ".githooks"):
                raise ValueError(
                    "An existing hooksPath is configured; integrate the hook there explicitly."
                )
            subprocess.run(
                ["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=True
            )
            print("Installed local pre-commit checks.")
        else:
            checks(
                root,
                args.python,
                tui=args.tui,
                fast=args.fast,
                report_dir=args.report_dir.resolve() if args.report_dir else None,
            )
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Development check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
