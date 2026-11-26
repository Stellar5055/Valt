"""Stage 8.5 — checks for the flag-driven CLI.

Flags carry everything non-secret; passwords arrive via a faked getpass.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import os

import pytest

from valt import cli
from valt.container import read_header
from valt.vault import create, open_container


def make_folder(tmp_path, name="docs"):
    f = tmp_path / name
    f.mkdir(parents=True, exist_ok=True)
    (f / "a.txt").write_bytes(b"hello " * 20)
    (f / "b.txt").write_bytes(b"world" * 10)
    return f


@pytest.fixture
def passwords(monkeypatch):
    queue = []
    # the tests below simulate a real console: stdin looks like a tty,
    # and the queued strings are what getpass "reads"
    class FakeTty:
        def isatty(self):
            return True

        def readline(self, limit=-1):
            return ""

    monkeypatch.setattr("sys.stdin", FakeTty())
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": queue.pop(0))
    return queue


# ---------- the happy paths ----------

def test_create_then_open_round_trip(tmp_path, passwords, capsys):
    folder = make_folder(tmp_path)
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(tmp_path / "v.valt"), "--folder", str(folder),
              "--label", "docs"])

    passwords += ["longenough"]
    cli.main(["open", str(tmp_path / "v.valt")])
    out = capsys.readouterr().out
    assert "docs" in out and "a.txt" in out


def test_auto_label_from_folder_basename(tmp_path, passwords):
    folder = make_folder(tmp_path, "tax documents")
    passwords += ["longenough", "longenough"]
    p = tmp_path / "v.valt"
    cli.main(["create", str(p), "--folder", str(folder)])
    seen = open_container(p, "longenough")
    assert [c["name"] for c in seen] == ["tax documents"]


def test_extract_round_trip(tmp_path, passwords):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(container), "--folder", str(folder), "--label", "docs"])
    dest = tmp_path / "out"
    passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest)])
    for name in ("a.txt", "b.txt"):
        assert (dest / name).read_bytes() == (folder / name).read_bytes()


def test_short_password_is_refused_then_reasked(tmp_path, passwords, capsys):
    folder = make_folder(tmp_path)
    passwords += ["short", "longenough", "longenough"]
    cli.main(["create", str(tmp_path / "v.valt"), "--folder", str(folder)])
    assert "8 characters" in capsys.readouterr().out


def test_password_prompt_shows_the_compartment(tmp_path, passwords, capsys, monkeypatch):
    # the compartment name travels into the prompt via ask_password's context
    folder = make_folder(tmp_path)
    seen = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": seen.append(prompt) or "longenough")
    cli.main(["create", str(tmp_path / "v.valt"), "--folder", str(folder), "--label", "docs"])
    assert any("(for 'docs')" in p for p in seen)


def test_password_falls_back_to_redirected_stdin(monkeypatch):
    # when input is redirected (script/pipe), getpass would read the console
    # and block - ask_password takes the line from stdin instead
    import io
    fake = io.StringIO("piped password line\n")
    fake.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", fake)
    assert cli.ask_password() == "piped password line"


# ---------- the guardrails ----------

def test_extract_refuses_overwrite_without_force(tmp_path, passwords, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(container), "--folder", str(folder), "--label", "docs"])
    dest = tmp_path / "out"
    passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest)])

    passwords += ["longenough"]
    with pytest.raises(SystemExit) as e:
        cli.main(["extract", str(container), str(dest)])
    assert e.value.code == 1
    assert "already exist" in capsys.readouterr().out

    passwords += ["longenough"]
    cli.main(["extract", str(container), str(dest), "--force"])


def test_open_with_never_used_password_is_neutral(tmp_path, passwords, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(container), "--folder", str(folder), "--label", "docs"])

    passwords += ["not-the-password"]
    with pytest.raises(SystemExit) as e:
        cli.main(["open", str(container)])
    assert e.value.code == 1
    assert "No compartments found for this password." in capsys.readouterr().out


def test_truncated_vault_gets_the_uniform_error(tmp_path, passwords, capsys):
    folder = make_folder(tmp_path)
    container = tmp_path / "v.valt"
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(container), "--folder", str(folder), "--label", "docs"])
    data = open(container, "rb").read()
    open(container, "wb").write(data[:300])

    passwords += ["longenough"]
    with pytest.raises(SystemExit) as e:
        cli.main(["open", str(container)])
    assert e.value.code == 1
    assert "Invalid or corrupted container." in capsys.readouterr().out


def test_value_error_prints_the_real_message(tmp_path, passwords, capsys):
    folders = []
    for i in range(17):
        folders.append(str(make_folder(tmp_path, f"f{i}")))
    passwords += ["longenough", "longenough"] * 17
    argv = ["create", str(tmp_path / "v.valt")]
    for f in folders:
        argv += ["--folder", f]
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 1
    assert "at most 16" in capsys.readouterr().out


def test_label_with_multiple_folders_errors(tmp_path, passwords, capsys):
    f1 = make_folder(tmp_path, "photos")
    f2 = make_folder(tmp_path, "taxes")
    with pytest.raises(SystemExit) as e:
        cli.main(["create", str(tmp_path / "v.valt"), "--folder", str(f1),
                  "--folder", str(f2), "--label", "x"])
    assert e.value.code == 1
    assert "exactly one" in capsys.readouterr().out


def test_slots_override_lands_in_the_header(tmp_path, passwords):
    p = tmp_path / "v.valt"
    folder = make_folder(tmp_path)
    passwords += ["longenough", "longenough"]
    cli.main(["create", str(p), "--slots", "4", "--folder", str(folder)])
    assert read_header(p)[0] == 4


def test_extract_compartment_picker_rejects_bad_choice(tmp_path, passwords, capsys,
                                                       monkeypatch):
    f1 = make_folder(tmp_path, "photos")
    f2 = make_folder(tmp_path, "taxes")
    container = tmp_path / "v.valt"
    passwords += ["longenough", "longenough", "longenough", "longenough"]
    cli.main(["create", str(container), "--folder", str(f1), "--folder", str(f2)])
    dest = tmp_path / "out"

    passwords += ["longenough"]
    monkeypatch.setattr(cli, "input", lambda prompt="": "-1", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["extract", str(container), str(dest)])
    assert e.value.code == 1
    assert "Invalid choice." in capsys.readouterr().out
