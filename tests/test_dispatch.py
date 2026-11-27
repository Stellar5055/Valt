"""Stage 11 — dispatch checks for the two launchers.

The full exe routes: no arguments -> GUI, any arguments -> CLI.
The CLI exe is always the CLI.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import pytest


def test_launcher_gui_routes_arguments_to_the_cli(monkeypatch):
    import launcher_gui
    called = []
    monkeypatch.setattr(launcher_gui, "main", lambda argv=None: called.append(argv))
    monkeypatch.setattr(launcher_gui, "main", lambda argv=None: called.append(argv))
    monkeypatch.setattr("valt.cli.ask_password",
                        lambda confirm=False, for_name=None: "pw")
    assert launcher_gui.run(["open", "x.valt"]) == "cli"
    assert called == [["open", "x.valt"]]


def test_launcher_gui_without_arguments_opens_the_gui(monkeypatch):
    import launcher_gui
    opened = []
    monkeypatch.setattr(launcher_gui, "run_gui", lambda: opened.append(True))
    assert launcher_gui.run([]) == "gui"
    assert opened == [True]


def test_launcher_help_exits_zero_and_lists_commands(capsys):
    import launcher_gui
    with pytest.raises(SystemExit) as e:
        launcher_gui.run(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("create", "open", "extract", "change-pw", "remove", "verify", "add"):
        assert cmd in out


def test_launcher_cli_always_runs_the_cli(monkeypatch):
    import launcher_cli
    called = []
    monkeypatch.setattr(launcher_cli, "main", lambda argv=None: called.append(argv))
    launcher_cli.run(["open", "x.valt"])
    assert called == [["open", "x.valt"]]
