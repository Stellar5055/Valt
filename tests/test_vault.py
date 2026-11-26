"""Stage 7 — automatic checks for valt/vault.py.

The Valt moment: one file, many passwords, each seeing only its own world.
Acceptance tests 3, 4 and 6 live here.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import hashlib
import os

import pytest

from valt.container import create_empty, FormatError
from valt.vault import create, open_container

SIZE = 5 * 1024 * 1024   # 5 MiB: with 4 slots -> segments of ~1.25 MiB (>= 1 MiB minimum)
SLOTS = 4


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_folders(tmp_path):
    photos = tmp_path / "photos"; photos.mkdir()
    (photos / "beach.txt").write_bytes(b"sand " * 100)
    (photos / "sunset.txt").write_bytes(random_junk(300))
    taxes = tmp_path / "taxes"; taxes.mkdir()
    (taxes / "IRS.txt").write_bytes(b"numbers " * 50)
    docs = tmp_path / "docs"; docs.mkdir()
    (docs / "notes.txt").write_bytes(b"plain " * 80)
    return photos, taxes, docs


def random_junk(n):
    from valt.crypto import random_bytes
    return random_bytes(n)


def test_each_password_sees_only_its_own_world(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, SIZE, SLOTS, [
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
    create(p, SIZE, SLOTS, [
        (str(photos), "pwA", "photos"),
        (str(taxes), "pwB", "taxes"),
        (str(docs), "pwC", "docs"),
    ])
    assert open_container(p, "banana") == []      # acceptance test 3


def test_empty_container_and_full_container_behave_identically(tmp_path):
    empty = tmp_path / "empty.valt"
    create_empty(empty, SIZE, SLOTS)

    full = tmp_path / "full.valt"
    photos, _, _ = make_folders(tmp_path)
    create(full, SIZE, SLOTS, [(str(photos), "pwA", "photos")])

    # the app cannot tell these two apart by asking with a password
    assert open_container(empty, "anything") == []
    assert open_container(full, "anything") == []


def test_same_password_opens_two_compartments(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, SIZE, SLOTS, [
        (str(photos), "one pw", "photos"),
        (str(taxes), "one pw", "taxes"),
    ])
    seen = open_container(p, "one pw")
    assert sorted(c["name"] for c in seen) == ["photos", "taxes"]
    assert {c["slot"] for c in seen} == {0, 1}


def test_compartments_get_fresh_folder_keys(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, SIZE, SLOTS, [
        (str(photos), "pwA", "photos"),
        (str(taxes), "pwA", "taxes"),              # same password, two slots
    ])
    seen = open_container(p, "pwA")
    assert seen[0]["folder_key"] != seen[1]["folder_key"]   # SPEC Law 1, observable


def test_two_containers_from_same_input_differ(tmp_path):
    photos, taxes, docs = make_folders(tmp_path)
    a = tmp_path / "a.valt"
    b = tmp_path / "b.valt"
    create(a, SIZE, SLOTS, [(str(photos), "pwA", "photos")])
    create(b, SIZE, SLOTS, [(str(photos), "pwA", "photos")])
    assert open(a, "rb").read() != open(b, "rb").read()     # acceptance test 6


def test_full_stack_round_trip_through_open(tmp_path):
    photos, _, _ = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, SIZE, SLOTS, [(str(photos), "pwA", "photos")])

    from valt.unpacker import extract_all
    comp = open_container(p, "pwA")[0]
    dest = tmp_path / "out"
    extract_all(p, comp["slot"], comp["folder_key"], comp["index_len"], str(dest))

    for src in sorted(photos.rglob("*")):
        if src.is_file():
            out = dest / src.relative_to(photos)
            assert sha(out.read_bytes()) == sha(src.read_bytes())


def test_corrupted_container_is_rejected_by_open(tmp_path):
    photos, _, _ = make_folders(tmp_path)
    p = tmp_path / "v.valt"
    create(p, SIZE, SLOTS, [(str(photos), "pwA", "photos")])
    data = open(p, "rb").read()
    open(p, "wb").write(data[:-25])                # chop the tail off
    with pytest.raises(FormatError):
        open_container(p, "pwA")
