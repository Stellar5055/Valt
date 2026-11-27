"""Dispatch checks for the two launchers.

valt.exe is a pure windowed GUI app: an existing .valt argument preselects
that vault, anything else is ignored. valt-cli.exe is always the CLI.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import pytest


def test_valt_argument_preselects_the_vault(monkeypatch, tmp_path):
    import launcher_gui
    vault = tmp_path / "mine.valt"
    vault.write_bytes(b"VALT")
    got = []
    monkeypatch.setattr(launcher_gui, "run_gui",
                        lambda initial_vault=None: got.append(initial_vault))
    assert launcher_gui.run([str(vault)]) == "gui"
    assert got == [str(vault)]


def test_missing_or_non_valt_arguments_are_ignored(monkeypatch, tmp_path):
    import launcher_gui
    got = []
    monkeypatch.setattr(launcher_gui, "run_gui",
                        lambda initial_vault=None: got.append(initial_vault))
    assert launcher_gui.run([str(tmp_path / "nope.valt"), "extra"]) == "gui"
    assert got == [None]
    assert launcher_gui.run([str(tmp_path / "notes.txt")]) == "gui"
    assert got == [None, None]


def test_launcher_gui_without_arguments_opens_the_gui(monkeypatch):
    import launcher_gui
    opened = []
    monkeypatch.setattr(launcher_gui, "run_gui",
                        lambda initial_vault=None: opened.append(True))
    assert launcher_gui.run([]) == "gui"
    assert opened == [True]


def test_launcher_cli_is_always_the_cli(monkeypatch):
    import launcher_cli
    called = []
    monkeypatch.setattr(launcher_cli, "main", lambda argv=None: called.append(argv))
    monkeypatch.setattr("valt.cli.ask_password",
                        lambda confirm=False, for_name=None: "pw")
    assert launcher_cli.run(["open", "x.valt"]) == "cli"
    assert called == [["open", "x.valt"]]
    assert launcher_cli.run([]) == "cli"


def test_launcher_cli_help_exits_zero_and_lists_commands(capsys):
    import launcher_cli
    with pytest.raises(SystemExit) as e:
        launcher_cli.run(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("create", "open", "extract", "change-pw", "remove", "verify", "add"):
        assert cmd in out
