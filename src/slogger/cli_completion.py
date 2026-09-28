"""Optional shell completion helpers (requires the ``[cli]`` extra).

Importing this module does not import ``argcomplete``. Call
:func:`autocomplete` / :func:`shell_script` only from the CLI entry path.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Sequence
from typing import Any

_OPS = ("!=", ">=", "<=", "!~", "=", ">", "<", "~")
_INSTALL_HINT = "pip install -e '.[cli]'  # or: pip install 'argcomplete>=3'"


def _import_argcomplete():
    try:
        import argcomplete
    except ImportError as exc:
        raise ModuleNotFoundError(
            f"argcomplete is required for shell completion. Install with {_INSTALL_HINT}"
        ) from exc
    return argcomplete


# Space-free placeholder for argcomplete's function_suffix. The real invocation
# is ``python3 -m slogger``; embedding that string in the function name (or relying
# on word-splitting while IFS is set to VT for COMP_LINE) breaks bash/zsh eval.
_SHELLCODE_PLACEHOLDER = "slogger_module"
_SHELLCODE_SCRIPT = "python3 -m slogger"


def shell_script(shell: str = "bash") -> str:
    """Return shell code that registers ``slogger`` completion."""
    if shell not in ("bash", "zsh", "fish"):
        raise ValueError(f"unsupported shell: {shell!r}")
    argcomplete = _import_argcomplete()
    if shell == "fish":
        # fish embeds the script as a bare command line; spaces are fine.
        return argcomplete.shellcode(
            ["slogger"],
            shell=shell,
            argcomplete_script=_SHELLCODE_SCRIPT,
        )

    # bash/zsh: keep a valid identifier as function_suffix, then rewrite the
    # completion runner to call ``python3 -m slogger`` without depending on IFS.
    code = argcomplete.shellcode(
        ["slogger"],
        shell=shell,
        argcomplete_script=_SHELLCODE_PLACEHOLDER,
    )
    code = code.replace(f'local script="{_SHELLCODE_PLACEHOLDER}"\n', "")
    code = code.replace(
        "__python_argcomplete_run ${script:-${words[1]}})",
        f"__python_argcomplete_run {_SHELLCODE_SCRIPT})",
    )
    code = code.replace(
        "__python_argcomplete_run ${script:-$1})",
        f"__python_argcomplete_run {_SHELLCODE_SCRIPT})",
    )
    return code


def _iter_actions(parser: argparse.ArgumentParser) -> Iterable[argparse.Action]:
    yield from parser._actions
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _iter_actions(sub)


def _first_existing_file(parsed_args: Any) -> str | None:
    candidates: list[str] = []
    sources = getattr(parsed_args, "sources", None)
    if isinstance(sources, list):
        candidates.extend(str(item) for item in sources)
    source = getattr(parsed_args, "source", None)
    if isinstance(source, str):
        candidates.append(source)
    before = getattr(parsed_args, "before", None)
    if isinstance(before, str):
        candidates.append(before)
    args = getattr(parsed_args, "args", None)
    if isinstance(args, list):
        candidates.extend(str(item) for item in args)

    for item in candidates:
        if item in ("-",) or any(ch in item for ch in "*?["):
            continue
        if os.path.isfile(item):
            return item
    return None


def _where_completer(prefix: str, parsed_args: Any, **kwargs: Any) -> Sequence[str]:
    path = _first_existing_file(parsed_args)
    if path is None:
        return []
    try:
        from slogger.tools.fields import fields
    except Exception:
        return []

    op_at = None
    op_used = None
    for op in _OPS:
        index = prefix.find(op)
        if index != -1:
            op_at = index
            op_used = op
            break

    try:
        if op_at is None:
            payload = fields(path, cache=True, scan=20_000)
            keys = list(payload.get("keys", {}))
            return [key for key in keys if key.startswith(prefix)]

        key = prefix[:op_at]
        value_prefix = prefix[op_at + len(op_used or "") :]
        if not key:
            return []
        payload = fields(path, key=key, top=20, cache=False, scan=20_000)
        out: list[str] = []
        for row in payload.get("top", []):
            value = row.get("value")
            text = "" if value is None else str(value)
            if text.startswith(value_prefix):
                # Values with spaces/operators are awkward in compact tokens; skip.
                if any(ch.isspace() for ch in text) or any(op in text for op in _OPS):
                    continue
                out.append(f"{key}{op_used}{text}")
        return out
    except Exception:
        return []


def _logger_completer(prefix: str, parsed_args: Any, **kwargs: Any) -> Sequence[str]:
    path = _first_existing_file(parsed_args)
    if path is None:
        return []
    try:
        from slogger.tools.meta import meta

        payload = meta(path)
        loggers = payload.get("loggers") or []
        return [name for name in loggers if str(name).startswith(prefix)]
    except Exception:
        return []


def attach_completers(parser: argparse.ArgumentParser) -> None:
    """Attach dynamic completers to shared filter flags on ``parser``."""
    for action in _iter_actions(parser):
        option_strings = set(action.option_strings)
        if "--where" in option_strings:
            action.completer = _where_completer  # type: ignore[attr-defined]
        if "--logger" in option_strings:
            action.completer = _logger_completer  # type: ignore[attr-defined]


def autocomplete(parser: argparse.ArgumentParser) -> None:
    """Run argcomplete if installed and a completion request is active."""
    if os.environ.get("_ARGCOMPLETE") is None:
        return
    argcomplete = _import_argcomplete()
    attach_completers(parser)
    argcomplete.autocomplete(parser)


__all__ = [
    "attach_completers",
    "autocomplete",
    "shell_script",
]
