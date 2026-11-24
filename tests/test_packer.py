"""Stage 5 — automatic checks for valt/packer.py.

The write side: a real folder becomes sealed chunks + an encrypted index,
with starts that survive the seal drift and a fits-check that fires first.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import json
import math
import os

import pytest

from valt.crypto import new_key, random_bytes, u32, u64, unlock
from valt.container import create_empty, read_header
from valt.packer import collect_files, plan_starts, build_index, pack_folder

SIZE = 4 * 1024 * 1024
SLOTS = 2
CHUNK = 65536


def make_tree(base):
    """A deliberately awkward folder: subfolder, multi-chunk files, empty, unicode."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "docs").mkdir()
    (base / "notes.txt").write_bytes(b"hello valt" * 10)          # 100 B, 1 chunk
    (base / "docs" / "report.txt").write_bytes(random_bytes(70_000))  # 2 chunks
    (base / "big.dat").write_bytes(random_bytes(150_000))          # 3 chunks
    (base / "empty.txt").write_bytes(b"")                          # 0 chunks
    (base / "🔐 secret.txt").write_bytes(b"emoji encrypted")       # 1 chunk
    return base


def pack_fixture(tmp_path, size=SIZE, slots=SLOTS):
    container = tmp_path / "c.valt"
    folder = make_tree(tmp_path / "src")
    folder_key = new_key()
    create_empty(container, size, slots)
    index_len = pack_folder(container, 0, str(folder), folder_key)
    return container, folder, folder_key, index_len


def read_index(container_path, slot, folder_key, index_len):
    slot_count, file_size, data_offset, segment_len = read_header(container_path)
    segment_start = data_offset + slot * segment_len
    with open(container_path, "rb") as f:
        f.seek(segment_start)
        blob = f.read(index_len)
    nonce, ct = blob[:12], blob[12:]
    return json.loads(unlock(folder_key, nonce, ct))


# ---------- the index ----------

def test_index_unlocks_and_lists_everything(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    names = [e["name"] for e in entries]
    assert names == sorted([
        "notes.txt", "docs/report.txt", "big.dat", "empty.txt", "🔐 secret.txt",
    ])
    by_name = {e["name"]: e["size"] for e in entries}
    assert by_name["empty.txt"] == 0
    assert by_name["big.dat"] == 150_000


def test_starts_survive_the_seal_drift(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    for i in range(1, len(entries)):
        prev, cur = entries[i - 1], entries[i]
        prev_chunks = math.ceil(prev["size"] / CHUNK)
        assert cur["start"] == prev["start"] + prev["size"] + 16 * prev_chunks


# ---------- the bytes on disk round-trip, chunk by chunk ----------

def test_every_file_decrypts_back_identically(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    slot_count, file_size, data_offset, segment_len = read_header(container)
    segment_start = data_offset + 0 * segment_len
    entries = read_index(container, 0, folder_key, index_len)

    with open(container, "rb") as f:
        for file_number, e in enumerate(entries):
            chunks = math.ceil(e["size"] / CHUNK) if e["size"] else 0
            data = b""
            for c in range(chunks):
                clen = min(CHUNK, e["size"] - c * CHUNK) + 16   # + the seal
                pos = segment_start + index_len + e["start"] + c * (CHUNK + 16)
                f.seek(pos)
                nonce = u32(file_number) + u64(c)
                data += unlock(folder_key, nonce, f.read(clen))
            original = (folder / e["name"]).read_bytes()
            assert data == original                              # byte-identical


# ---------- hygiene ----------

def test_names_use_forward_slashes(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    for e in entries:
        assert "\\" not in e["name"]
        assert "//" not in e["name"]
    assert "docs/report.txt" in [e["name"] for e in entries]


def test_two_packs_look_nothing_alike(tmp_path):
    a, _, ka, _ = pack_fixture(tmp_path / "one")
    b, _, kb, _ = pack_fixture(tmp_path / "two")
    seg_a = open(a, "rb").read()[8 + 128 * SLOTS:]
    seg_b = open(b, "rb").read()[8 + 128 * SLOTS:]
    assert seg_a[:4096] != seg_b[:4096]          # fresh keys + nonces everywhere


def test_packed_segment_is_noise(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    slot_count, file_size, data_offset, segment_len = read_header(container)
    with open(container, "rb") as f:
        f.seek(data_offset + index_len)
        sample = f.read(256 * 1024)
    run = best = 0
    for byte in sample:
        run = run + 1 if 32 <= byte < 127 else 0
        best = max(best, run)
    assert best < 25                              # no readable text anywhere


# ---------- the guardrails ----------

def test_folder_too_big_raises_and_container_unchanged(tmp_path):
    container = tmp_path / "c.valt"
    create_empty(container, SIZE, SLOTS)
    before = open(container, "rb").read()
    big = tmp_path / "src"
    big.mkdir()
    (big / "huge.dat").write_bytes(random_bytes(3 * 1024 * 1024))  # > 2 MiB segment

    with pytest.raises(ValueError):
        pack_folder(container, 0, str(big), new_key())

    assert open(container, "rb").read() == before  # nothing was written


def test_bad_slot_raises(tmp_path):
    container, folder, folder_key, _ = pack_fixture(tmp_path)
    with pytest.raises(ValueError):
        pack_folder(container, 2, str(folder), new_key())   # slots are 0..1
    with pytest.raises(ValueError):
        pack_folder(container, -1, str(folder), new_key())


def test_second_slot_does_not_clobber_the_first(tmp_path):
    # the +/* bug from review: slots must land in their own segments
    container = tmp_path / "c.valt"
    create_empty(container, SIZE, SLOTS)
    folder_a = tmp_path / "a"; folder_a.mkdir()
    folder_b = tmp_path / "b"; folder_b.mkdir()
    (folder_a / "only_a.txt").write_bytes(b"AAAA" * 100)
    (folder_b / "only_b.txt").write_bytes(b"BBBB" * 100)
    key_a, key_b = new_key(), new_key()

    len_a = pack_folder(container, 0, str(folder_a), key_a)
    len_b = pack_folder(container, 1, str(folder_b), key_b)

    entries_a = read_index(container, 0, key_a, len_a)
    entries_b = read_index(container, 1, key_b, len_b)
    assert [e["name"] for e in entries_a] == ["only_a.txt"]
    assert [e["name"] for e in entries_b] == ["only_b.txt"]
