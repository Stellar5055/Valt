"""Stage 9 — checks for the four verbs: change-pw, remove, verify, add.

Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import hashlib
import os

import pytest

from valt.crypto import random_bytes
from valt.container import write_skeleton, FormatError
from valt.packer import pack_folder
from valt.vault import create, open_container, change_password, remove, add
from valt.unpacker import extract_all, verify_compartment

CHUNK = 65536


def make_folder(tmp_path, name="docs"):
    f = tmp_path / name
    f.mkdir(parents=True, exist_ok=True)
    (f / "a.txt").write_bytes(b"hello " * 20)
    (f / "b.txt").write_bytes(b"world" * 10)
    return f


def sha(b):
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def vault(tmp_path):
    folder = make_folder(tmp_path, "photos")
    p = tmp_path / "v.valt"
    create(p, [(str(folder), "pwA", "photos")])
    return p, folder, "pwA"


# ---------- change_password ----------

def test_change_password_flips_access(vault):
    p, folder, old = vault
    changed = change_password(p, old, "brand new pw", slot=0)
    assert changed == ["photos"]
    assert open_container(p, old) == []            # the old password opens nothing
    seen = open_container(p, "brand new pw")
    assert [c["name"] for c in seen] == ["photos"]


def test_data_survives_a_password_change(vault, tmp_path):
    p, folder, old = vault
    change_password(p, old, "brand new pw", slot=0)
    comp = open_container(p, "brand new pw")[0]
    dest = tmp_path / "out"
    extract_all(p, comp["segment_offset"], comp["segment_len"],
                comp["folder_key"], comp["index_len"], str(dest))
    for src in folder.rglob("*"):
        if src.is_file():
            assert sha((dest / src.relative_to(folder)).read_bytes()) == sha(src.read_bytes())


def test_wrong_old_password_changes_nothing(vault):
    p, folder, old = vault
    changed = change_password(p, "wrong", "brand new pw")
    assert changed == []
    assert open_container(p, "brand new pw") == []
    assert len(open_container(p, old)) == 1        # the real one still works


def test_change_password_without_slot_changes_all(vault, tmp_path):
    p, folder, old = vault
    other = make_folder(tmp_path, "taxes")
    add(p, str(other), old, "taxes", slot=1)       # same password, second compartment

    change_password(p, old, "new pw")              # no slot -> change all of them
    assert open_container(p, old) == []
    assert len(open_container(p, "new pw")) == 2


# ---------- remove ----------

def test_remove_wipes_one_compartment(tmp_path):
    p = tmp_path / "v.valt"
    f1 = make_folder(tmp_path, "photos")
    f2 = make_folder(tmp_path, "taxes")
    create(p, [(str(f1), "pwA", "photos"), (str(f2), "pwB", "taxes")])

    name = remove(p, "pwA", 0)
    assert name == "photos"
    assert open_container(p, "pwA") == []          # gone for its own password
    seen = open_container(p, "pwB")                # the other one untouched
    assert [c["name"] for c in seen] == ["taxes"]


def test_old_backup_still_opens_a_removed_compartment(tmp_path):
    p = tmp_path / "v.valt"
    folder = make_folder(tmp_path, "photos")
    create(p, [(str(folder), "pwA", "photos")])
    backup = tmp_path / "backup.valt"
    backup.write_bytes(open(p, "rb").read())       # a copy made before removal

    remove(p, "pwA", 0)
    assert open_container(p, "pwA") == []          # removed from the live vault
    seen = open_container(backup, "pwA")           # acceptance test 9: backups remember
    assert [c["name"] for c in seen] == ["photos"]


# ---------- verify ----------

def test_verify_healthy_compartment(vault):
    p, folder, key = vault
    comp = open_container(p, key)[0]
    ok, bad = verify_compartment(p, comp["segment_offset"], comp["segment_len"],
                                 comp["folder_key"], comp["index_len"])
    assert ok is True
    assert bad is None


def test_verify_names_the_corrupted_file(vault):
    p, folder, key = vault
    comp = open_container(p, key)[0]
    data = bytearray(open(p, "rb").read())
    data[comp["segment_offset"] + comp["index_len"] + 50] ^= 1   # inside a.txt
    open(p, "wb").write(bytes(data))
    ok, bad = verify_compartment(p, comp["segment_offset"], comp["segment_len"],
                                 comp["folder_key"], comp["index_len"])
    assert ok is False
    assert bad == "a.txt"


# ---------- add ----------

def test_add_appends_and_opens(tmp_path):
    p = tmp_path / "v.valt"
    first = make_folder(tmp_path, "photos")
    create(p, [(str(first), "pwA", "photos")])
    comp_a = open_container(p, "pwA")[0]

    second = make_folder(tmp_path, "taxes")
    name = add(p, str(second), "pwB", "taxes", slot=1)
    assert name == "taxes"

    comp_b = open_container(p, "pwB")[0]
    gap = comp_b["segment_offset"] - (comp_a["segment_offset"] + comp_a["segment_len"])
    assert gap >= 0                                # B never overlaps A
    assert gap <= 8192                             # the random overhead is the only gap
    assert comp_b["name"] == "taxes"
    assert len(open_container(p, "pwA")) == 1      # the first one untouched


def test_add_slot_out_of_range_raises(tmp_path):
    p = tmp_path / "v.valt"
    write_skeleton(p, 2)
    folder = make_folder(tmp_path, "docs")
    with pytest.raises(ValueError):
        add(p, str(folder), "pw", "docs", slot=5)
