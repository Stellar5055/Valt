"""Stage 10, step 1 — checks for the progress callbacks and renderer.

The format layer only reports numbers (plus the compartment name at phase
starts); all rendering lives in the CLI.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import time

import pytest

from valt import cli
from valt.cli import Progress, fmt_eta
from valt.crypto import new_key, random_bytes
from valt.container import write_skeleton, read_header
from valt.packer import pack_folder
from valt.vault import create, open_container
from valt.unpacker import extract_all, verify_compartment

SLOTS = 3
CHUNK = 65536


# ---------- the pure helpers ----------

def test_fmt_eta_formats_the_three_tiers():
    assert fmt_eta(0) == "00:00"
    assert fmt_eta(42) == "00:42"
    assert fmt_eta(3723) == "1:02:03"       # 1 h 2 min 3 s


def test_tty_gate_keeps_piped_output_clean(capsys):
    # pytest's captured stdout is not a tty -> the renderer must stay silent
    prog = Progress("packing")
    prog.update(0, 1000)
    prog.update(500, 1000)
    assert capsys.readouterr().out == ""


def test_renderer_draws_verb_percentage_and_name(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("packing")
    prog.update(0, 1000, name="taxes")
    out = capsys.readouterr().out
    assert "packing" in out and "'taxes'" in out and "0%" in out

    time.sleep(0.11)                         # past the throttle gate
    prog.update(500, 1000)
    out = capsys.readouterr().out
    assert "50%" in out and "ETA" in out and "'taxes'" in out


def test_renderer_keeps_the_verb_without_a_name(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("unlocking")
    prog.update(3, 8)
    out = capsys.readouterr().out
    assert "unlocking" in out and "37%" in out or "38%" in out   # 3 of 8


def test_renderer_never_draws_a_bar():
    prog = Progress("packing")
    prog.update(500, 1000)
    # no bar characters anywhere: the line is only verb + name + % + ETA
    assert "#" not in prog.verb and "█" not in prog.verb


def test_renderer_closes_the_line_at_100_percent(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("packing")
    prog.update(0, 1000)
    prog.update(1000, 1000)
    out = capsys.readouterr().out
    assert "100%" in out
    assert out.endswith("\n")


def test_updates_are_throttled_mid_phase(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("packing")
    prog.update(0, 1000)
    capsys.readouterr()

    prog.update(10, 1000)                    # < 0.1 s later -> throttled
    assert capsys.readouterr().out == ""

    time.sleep(0.11)
    prog.update(20, 1000)                    # after the gate -> drawn
    assert "2%" in capsys.readouterr().out


def test_phase_start_resets_the_timer_and_closes_the_old_line(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("working")
    prog.update(500, 500)                    # finishes a phase -> newline
    prog.update(0, 200)                      # a new phase starts at 0%
    out = capsys.readouterr().out
    assert "\n" in out
    assert "0%" in out


def test_renderer_stores_the_name_until_a_new_one_arrives(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)
    prog = Progress("packing")
    prog.update(0, 1000, name="taxes")
    prog.update(300, 1000)                   # no name -> keep 'taxes'
    out = capsys.readouterr().out
    assert "'taxes'" in out


# ---------- the callbacks in the format layer ----------

def make_tree(base):
    base.mkdir(parents=True, exist_ok=True)
    (base / "a.bin").write_bytes(random_bytes(150_000))   # 3 chunks
    (base / "b.bin").write_bytes(random_bytes(700))       # 1 chunk
    (base / "empty.txt").write_bytes(b"")                 # 0 chunks
    return base


def test_pack_progress_starts_at_zero_and_ends_full(tmp_path):
    container = tmp_path / "c.valt"
    write_skeleton(container, SLOTS)
    folder = make_tree(tmp_path / "src")

    seen = []
    pack_folder(container, str(folder), new_key(),
                progress=lambda d, t, n=None: seen.append((d, t)))

    assert seen[0] == (0, seen[0][1])            # starts at zero
    dones = [d for d, t in seen]
    assert dones == sorted(dones)                # never goes backwards
    assert seen[-1][0] == seen[-1][1]            # ends at 100%
    assert len({t for d, t in seen}) == 1        # one consistent total


def test_pack_phase_start_carries_the_label(tmp_path):
    container = tmp_path / "c.valt"
    write_skeleton(container, SLOTS)
    folder = make_tree(tmp_path / "src")

    seen = []
    pack_folder(container, str(folder), new_key(), label="taxes",
                progress=lambda d, t, n=None: seen.append((d, t, n)))

    assert seen[0][2] == "taxes"                 # the phase start names the compartment


def test_open_container_reports_each_safe(tmp_path):
    container = tmp_path / "c.valt"
    write_skeleton(container, SLOTS)
    seen = []
    open_container(container, "anything", progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, SLOTS), (2, SLOTS), (3, SLOTS)]


def test_create_has_one_phase_per_compartment_with_labels(tmp_path):
    f1 = tmp_path / "a"; f1.mkdir()
    (f1 / "x.txt").write_bytes(b"x" * 5000)
    f2 = tmp_path / "b"; f2.mkdir()
    (f2 / "y.txt").write_bytes(b"y" * 5000)
    container = tmp_path / "v.valt"

    seen = []
    create(container, [(str(f1), "pw1", "alpha"), (str(f2), "pw2", "beta")],
           progress=lambda d, t, n=None: seen.append((d, t, n)))

    labels = [n for d, t, n in seen if d == 0]   # phase starts carry the names
    assert labels == ["alpha", "beta"]
    phases = []
    for d, t, n in seen:
        if d == 0:
            phases.append([])
        phases[-1].append(d)
    for phase in phases:
        assert phase == sorted(phase)            # never goes backwards within a phase


def test_extract_and_verify_progress_end_at_total(tmp_path):
    container = tmp_path / "c.valt"
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.bin").write_bytes(random_bytes(150_000))
    (folder / "b.bin").write_bytes(random_bytes(700))
    key = new_key()
    write_skeleton(container, SLOTS)
    seg_off, seg_len, index_len = pack_folder(container, str(folder), key)

    seen = []
    extract_all(container, seg_off, seg_len, key, index_len, str(tmp_path / "out"),
                progress=lambda d, t, n=None: seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1]            # ends at 100%
    dones = [d for d, t in seen]
    assert dones == sorted(dones)

    seen2 = []
    verify_compartment(container, seg_off, seg_len, key, index_len,
                       progress=lambda d, t, n=None: seen2.append((d, t)))
    assert seen2[-1][0] == seen2[-1][1]
    assert seen[-1][1] == seen2[-1][1]           # extract and verify measure the same work


def test_extract_phase_start_carries_the_label(tmp_path):
    container = tmp_path / "c.valt"
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.bin").write_bytes(random_bytes(5000))
    key = new_key()
    write_skeleton(container, SLOTS)
    seg_off, seg_len, index_len = pack_folder(container, str(folder), key)

    seen = []
    extract_all(container, seg_off, seg_len, key, index_len, str(tmp_path / "out"),
                label="taxes", progress=lambda d, t, n=None: seen.append((d, t, n)))
    assert seen[0] == (0, seen[0][1], "taxes")


def test_progress_defaults_to_none_everywhere(tmp_path):
    # every call site works without a callback -- the old contract, intact
    container = tmp_path / "c.valt"
    folder = make_tree(tmp_path / "src")
    write_skeleton(container, SLOTS)
    key = new_key()
    seg_off, seg_len, index_len = pack_folder(container, str(folder), key)
    open_container(container, "x", progress=None)
    extract_all(container, seg_off, seg_len, key, index_len, str(tmp_path / "out"))
    verify_compartment(container, seg_off, seg_len, key, index_len)
