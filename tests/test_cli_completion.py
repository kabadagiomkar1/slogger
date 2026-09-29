from __future__ import annotations

from types import SimpleNamespace

import pytest

from slogger.cli import build_parser, main
from slogger.cli_completion import (
    _first_existing_file,
    _logger_completer,
    _where_completer,
    attach_completers,
    shell_script,
)


def test_completion_cli_prints_bash_script(capsys):
    code = main(["completion", "--shell", "bash"])
    out = capsys.readouterr().out
    assert code == 0
    assert "_ARGCOMPLETE" in out or "argcomplete" in out
    assert "python3 -m slogger" in out
    # Regression: argcomplete used to embed "python3 -m slogger" in the
    # function name, which makes `eval "$(… completion …)"` a syntax error.
    assert "_python_argcomplete_python3 -m" not in out
    assert " -F _python_argcomplete_python3 -m " not in out


def test_shell_script_bash_eval_safe(tmp_path):
    import subprocess

    script = shell_script("bash")
    assert "python3 -m slogger" in script
    syntax = subprocess.run(
        ["bash", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    probe = tmp_path / "probe.sh"
    probe.write_text(
        script + "\n" + "complete -p slogger\n",
        encoding="utf-8",
    )
    ran = subprocess.run(
        ["bash", str(probe)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert "slogger" in ran.stdout


def test_completion_cli_missing_argcomplete(monkeypatch, capsys):
    import slogger.cli_completion as mod

    def boom():
        raise ModuleNotFoundError("argcomplete is required")

    monkeypatch.setattr(mod, "_import_argcomplete", boom)
    code = main(["completion", "--shell", "bash"])
    err = capsys.readouterr().err
    assert code == 64
    assert "argcomplete" in err


def test_where_completer_keys_and_values(tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        '{"timestamp":"2026-09-26T16:00:00.000Z","level":"INFO","logger":"app",'
        '"message":"hi","file":"a.py","func":"f","line":1,"user":"ada"}\n'
        '{"timestamp":"2026-09-26T16:00:01.000Z","level":"INFO","logger":"app",'
        '"message":"hi","file":"a.py","func":"f","line":2,"user":"grace"}\n',
        encoding="utf-8",
    )
    ns = SimpleNamespace(sources=[str(log)])
    keys = _where_completer("us", ns)
    assert "user" in keys
    values = _where_completer("user=", ns)
    assert "user=ada" in values
    assert "user=grace" in values
    assert _first_existing_file(ns) == str(log)


def test_logger_completer(tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        '{"timestamp":"2026-09-26T16:00:00.000Z","level":"INFO","logger":"app.db",'
        '"message":"hi","file":"a.py","func":"f","line":1}\n',
        encoding="utf-8",
    )
    ns = SimpleNamespace(sources=[str(log)])
    assert "app.db" in _logger_completer("app", ns)


def test_attach_completers_sets_where():
    from slogger.cli_completion import _iter_actions

    parser = build_parser()
    attach_completers(parser)
    found = False
    for action in _iter_actions(parser):
        if "--where" in action.option_strings:
            assert getattr(action, "completer", None) is _where_completer
            found = True
            break
    assert found


def test_shell_script_rejects_unknown_shell():
    with pytest.raises(ValueError, match="unsupported shell"):
        shell_script("tcsh")


@pytest.mark.parametrize("prefix, completed", [("qu", "query"), ("tre", "tree"), ("tra", "trace")])
def test_readme_zsh_setup_completes_on_tab(prefix, completed):
    """Exercise Zsh's alias/function dispatch, not just script registration."""
    import os
    import pty
    import re
    import select
    import shutil
    import subprocess
    import time
    from pathlib import Path

    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("requires zsh")
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    match = re.search(r"```zsh\n(.*?)\n```", readme, re.DOTALL)
    assert match is not None
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [zsh, "-f"], stdin=slave, stdout=slave, stderr=slave,
        env={**os.environ, "TERM": "xterm", "PS1": "READY> "},
        start_new_session=True,
    )
    os.close(slave)

    def wait_for(expected):
        received = b""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                received += os.read(master, 65536)
                if expected in re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", received):
                    return
        pytest.fail(f"expected {expected!r}; terminal returned {received!r}")

    try:
        wait_for(b"READY> ")
        # Apply the documented setup after an older alias registration.
        setup = "alias slogger='python3 -m slogger'\n" + match.group(1)
        os.write(master, (setup + "\nprintf 'SETUP_%s\\n' DONE\n").encode())
        wait_for(b"SETUP_DONE")
        os.write(master, f"slogger {prefix}\t".encode())
        wait_for(f"slogger {completed} ".encode())
    finally:
        process.kill()
        process.wait(timeout=5)
        os.close(master)
