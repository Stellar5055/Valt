"""Stage 7 — checks for valt/vault.py (v1.1).

The Valt moment: one file, many passwords, each seeing only its own world.
Acceptance tests 3, 4 and 6 live here. v1.1: no size/slots input, no waste.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import hashlib
import math
import os

import pytest

from valt.crypto import random_bytes
from valt.container import write_skeleton, read_header, FormatError
from valt.unpacker import extract_all
from valt.vault import create, open_container

SLOTS = 4   # 3 compartments + 2 spares would be 5; 4 keeps this test light


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_folders(tmp_path):
    photos = tmp_path / "photos"; photos.mkdir()
    (photos / "beach.txt").write_bytes(b"sand " * 100)
    (photos / "sunset.txt").write_bytes(random_bytes(300))
    taxes = tmp_path / "taxes"; taxes.mkdir()
    (taxes / "IRS.txt").write_bytes(b"numbers " * 50)
    docs = tmp_path / "docs"; docs.mkdir()
    (docs / "notes.txt").write_bytes(b"plain " * 80)
    return photos, taxes, docs


def test_each_password_sees_only_its_own_world(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [
        (str(photos), "pwA", "photos"),
        (str(taxes), "pwB", "taxes"),
        (str(docs), "pwC", "docs"),
    ])

    seen_a = open_container(p, "pwA")
    assert len(seen_a) == 1                       # only ONE compartment exists for A
    assert seen_a[0]["name"] == "photos"
    assert [e["name"] for e in seen_a[0]["entries"]] == ["beach.txt", "sunset.txt"]

    seen_b = open_container(p, "pwB")
    assert [c["name"] for c in seen_b] == ["taxes"]

    seen_c = open_container(p, "pwC")
    assert [c["name"] for c in seen_c] == ["docs"]


def test_never_used_password_returns_empty(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [
        (str(photos), "pwA", "photos"),
        (str(taxes), "pwB", "taxes"),
        (str(docs), "pwC", "docs"),
    ])
    assert open_container(p, "banana") == []      # acceptance test 3


def test_empty_vault_and_full_vault_behave_identically(tmp_path):
    empty = tmp_path / "empty.valt"
    write_skeleton(empty, SLOTS)

    full = tmp_path / "full.valt"
    photos, _, _ = make_folders(tmp_path)
    create(full, [(str(photos), "pwA", "photos")])

    # the app cannot tell these two apart by asking with a password
    assert open_container(empty, "anything") == []
    assert open_container(full, "anything") == []


def test_same_password_opens_two_compartments(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [
        (str(photos), "one pw", "photos"),
        (str(taxes), "one pw", "taxes"),
    ])
    seen = open_container(p, "one pw")
    assert sorted(c["name"] for c in seen) == ["photos", "taxes"]
    assert {c["slot"] for c in seen} == {0, 1}


def test_compartments_get_fresh_folder_keys(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [
        (str(photos), "pwA", "photos"),
        (str(taxes), "pwA", "taxes"),              # same password, two slots
    ])
    seen = open_container(p, "pwA")
    assert seen[0]["folder_key"] != seen[1]["folder_key"]   # SPEC Law 1, observable


def test_two_vaults_from_same_input_differ(tmp_path):
    photos, _, _ = make_folders(tmp_path)
    a = tmp_path / "a.valt"
    b = tmp_path / "b.valt"
    create(a, [(str(photos), "pwA", "photos")])
    create(b, [(str(photos), "pwA", "photos")])
    assert open(a, "rb").read() != open(b, "rb").read()      # acceptance test 6
    # the random overhead keeps sizes slightly different too
    assert abs(os.path.getsize(a) - os.path.getsize(b)) <= 8192


def test_vault_size_is_packed_not_padded(tmp_path):
    # v1.1: no slack -- the vault is roughly its contents, plus seals, index,
    # safes and at most 8 KiB of random overhead
    photos, _, _ = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [(str(photos), "pwA", "photos")])

    content = sum(f.stat().st_size for f in photos.rglob("*") if f.is_file())
    seals = sum(16 * math.ceil(f.stat().st_size / 65536)
                for f in photos.rglob("*") if f.is_file())
    # 3 safes (392 B) + index (~400 B) + overhead (<= 8192 B) + small margin
    assert os.path.getsize(p) <= 392 + content + seals + 1024 + 8192 + 512


def test_full_stack_round_trip_through_open(tmp_path):
    photos, _, _ = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [(str(photos), "pwA", "photos")])

    comp = open_container(p, "pwA")[0]
    dest = tmp_path / "out"
    extract_all(p, comp["segment_offset"], comp["segment_len"],
                comp["folder_key"], comp["index_len"], str(dest))

    for src in sorted(photos.rglob("*")):
        if src.is_file():
            out = dest / src.relative_to(photos)
            assert sha(out.read_bytes()) == sha(src.read_bytes())


def test_truncated_vault_is_rejected_by_open(tmp_path):
    photos, _, _ = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, [(str(photos), "pwA", "photos")])
    data = open(p, "rb").read()
    open(p, "wb").write(data[:300])                # chop into the safes area
    with pytest.raises(FormatError):
        open_container(p, "pwA")


def test_too_many_compartments_is_rejected(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    many = [(str(photos), f"pw{i}", f"c{i}") for i in range(17)]
    with pytest.raises(ValueError):
        create(tmp_path / "v.valt", many)
