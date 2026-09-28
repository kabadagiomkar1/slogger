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
