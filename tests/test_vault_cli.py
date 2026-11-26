"""Stage 8 — checks for valt/cli.py.

The CLI: three commands, uniform errors, no oracles, no passwords in argv.
Prompts are faked, so no typing -- and no real passwords in tests.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import os

import pytest

from valt import cli
from valt.vault import create


class FakeIO:
    """Queued answers for input() and getpass.getpass(), in order."""

    def __init__(self, lines=(), passwords=()):
        self.lines = list(lines)
        self.passwords = list(passwords)

    def input(self, prompt=""):
        assert self.lines, f"unexpected input() call: {prompt}"
        return self.lines.pop(0)

    def getpass(self, prompt=""):
        assert self.passwords, f"unexpected getpass() call: {prompt}"
        return self.passwords.pop(0)


@pytest.fixture
def io(monkeypatch):
    fake = FakeIO()
    monkeypatch.setattr(cli.getpass, "getpass", fake.getpass)
    monkeypatch.setattr(cli, "input", fake.input, raising=False)
    return fake


def make_folder(tmp_path, name="docs"):
    f = tmp_path / name
    f.mkdir()
    (f / "a.txt").write_bytes(b"hello " * 20)
    (f / "b.txt").write_bytes(b"world" * 10)
    return f


# ---------- the happy paths ----------

def test_create_then_open_round_trip(tmp_path, io, capsys):
    folder = make_folder(tmp_path)
    io.lines += ["y", str(folder), "docs", "n"]
    io.passwords += ["longenough", "longenough"]
    cli.main(["create", str(tmp_path / "v.valt")])

    io.passwords += ["longenough"]
    cli.main(["open", str(tmp_path / "v.valt")])           # exit 0: no SystemExit
    out = capsys.readouterr().out
    assert "docs" in out
    assert "a.txt" in out


def test_extract_round_trip(tmp_path, io):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    io.lines += ["y", str(folder), "docs", "n"]
    io.passwords += ["longenough", "longenough"]
    cli.main(["create", str(container)])

    dest = tmp_path / "out"
    io.passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest)])

    for name in ("a.txt", "b.txt"):
        assert (dest / name).read_bytes() == (folder / name).read_bytes()


def test_short_password_is_refused_then_reasked(tmp_path, io, capsys):
    folder = make_folder(tmp_path)
    io.lines += ["y", str(folder), "", "n"]
    io.passwords += ["short", "longenough", "longenough"]   # refused, then accepted
    cli.main(["create", str(tmp_path / "v.valt")])
    assert "8 characters" in capsys.readouterr().out


def test_extract_refuses_overwrite_without_force(tmp_path, io, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    io.lines += ["y", str(folder), "docs", "n"]
    io.passwords += ["longenough", "longenough"]
    cli.main(["create", str(container)])

    dest = tmp_path / "out"
    io.passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest)])        # first extract is fine

    io.passwords += ["longenough"]
    with pytest.raises(SystemExit) as e:
        cli.main(["extract", str(container), str(dest)])    # second one clashes
    assert e.value.code == 1
    assert "already exist" in capsys.readouterr().out

    io.passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest), "--force"])  # override works


# ---------- the promises ----------

def test_open_with_never_used_password_is_neutral(tmp_path, io, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    io.lines += ["y", str(folder), "docs", "n"]
    io.passwords += ["longenough", "longenough"]
    cli.main(["create", str(container)])

    io.passwords += ["not-the-password"]       # >= 8 chars, but wrong
    with pytest.raises(SystemExit) as e:
        cli.main(["open", str(container)])
    assert e.value.code == 1
    assert "No compartments found for this password." in capsys.readouterr().out


def test_truncated_vault_gets_the_uniform_error(tmp_path, io, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    io.lines += ["y", str(folder), "docs", "n"]
    io.passwords += ["longenough", "longenough"]
    cli.main(["create", str(container)])

    data = open(container, "rb").read()
    open(container, "wb").write(data[:300])      # chop into the safes area
    io.passwords += ["longenough"]
    with pytest.raises(SystemExit) as e:
        cli.main(["open", str(container)])
    assert e.value.code == 1
    assert "Invalid or corrupted container." in capsys.readouterr().out


# ---------- these three document known findings (see report) ----------

def test_value_error_prints_the_real_message(tmp_path, io, capsys):
    # bug #1: the error net prints the ValueError CLASS, not its message
    folders = []
    for i in range(17):
        f = tmp_path / f"f{i}"
        f.mkdir()
        (f / "x.txt").write_bytes(b"x")
        folders.append(str(f))
    for f in folders:
        io.lines += ["y", f, ""]
        io.passwords += ["longenough", "longenough"]
    io.lines += ["n"]

    with pytest.raises(SystemExit) as e:
        cli.main(["create", str(tmp_path / "v.valt")])
    assert e.value.code == 1
    assert "at most 16" in capsys.readouterr().out


def test_extract_compartment_picker_rejects_bad_choice(tmp_path, io, capsys):
    # bug #2: choice "-1" wraps around with Python negative indexing
    photos = make_folder(tmp_path, "photos")
    taxes = tmp_path / "taxes"; taxes.mkdir()
    (taxes / "IRS.txt").write_bytes(b"numbers")
    container = tmp_path / "v.valt"
    io.lines += ["y", str(photos), "photos", "y", str(taxes), "taxes", "n"]
    io.passwords += ["longenough", "longenough", "longenough", "longenough"]
    cli.main(["create", str(container)])

    dest = tmp_path / "out"
    io.passwords += ["longenough"]
    io.lines += ["-1"]
    with pytest.raises(SystemExit) as e:
        cli.main(["extract", str(container), str(dest)])
    assert e.value.code == 1
    assert "Invalid choice." in capsys.readouterr().out


def test_no_means_no(tmp_path, io, capsys):
    # bug #3: only exact "n" ended the loop -- "no" was taken as "yes"
    io.lines += ["no"]
    cli.main(["create", str(tmp_path / "v.valt")])
    assert "No compartments added" in capsys.readouterr().out
