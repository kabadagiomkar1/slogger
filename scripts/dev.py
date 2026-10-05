#!/usr/bin/env python3
"""Development preflight, checks, and documentation consistency (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import importlib.metadata as m, importlib.util as u, json, sys
packages = {}
for name in ('pytest', 'ruff', 'pyrefly', 'polars'):
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


def preflight(root: Path, python: str | None, register: bool = False) -> dict:
    info = environment(root, python)
    print(json.dumps(info, indent=2), flush=True)
    missing = [name for name in ("pytest", "ruff", "pyrefly") if not info["packages"][name]]
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
                if ready and (not args.polars or existing["packages"]["polars"]):
                    preflight(root, str(destination / "bin/python"), register=True)
                    return 0
            if not destination.exists():
                run(args.python or sys.executable, ["-m", "venv", str(destination)], root)
            python = str(destination / "bin/python")
            extras = "dev,tools-polars" if args.polars else "dev"
            arguments = ["-m", "pip", "install", "--no-cache-dir", "-e", f".[{extras}]"]
            if args.offline:
                arguments.append("--no-index")
            run(python, arguments, root)
            preflight(root, python, register=True)
        elif args.command == "preflight":
            preflight(root, args.python, register=args.register)
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
            info = preflight(root, args.python)
            docs(root)
            run(
                info["python"],
                ["-m", "ruff", "check", "src", "tests", "examples", "benchmarks", "scripts"],
                root,
            )
            run(
                info["python"],
                ["-m", "pyrefly", "check", "--python-interpreter-path", info["python"]],
                root,
            )
            if not args.fast:
                run(info["python"], ["-m", "pytest"], root)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Development check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
