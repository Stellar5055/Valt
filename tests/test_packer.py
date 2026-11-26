"""Stage 5 (v1.1) — checks for valt/packer.py.

v1.1: compartments append at end-of-file, variable length, no fits-check --
the folder defines its own segment.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import json
import math
import os

from valt.crypto import new_key, random_bytes, u32, u64, unlock
from valt.container import write_skeleton, read_header
from valt.packer import collect_files, plan_starts, build_index, pack_folder

SLOTS = 2
CHUNK = 65536


def make_tree(base):
    """A deliberately awkward folder: subfolder, multi-chunk files, empty, unicode."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "docs").mkdir()
    (base / "notes.txt").write_bytes(b"hello valt" * 10)              # 100 B, 1 chunk
    (base / "docs" / "report.txt").write_bytes(random_bytes(70_000))  # 2 chunks
    (base / "big.dat").write_bytes(random_bytes(150_000))             # 3 chunks
    (base / "empty.txt").write_bytes(b"")                             # 0 chunks
    (base / "🔐 secret.txt").write_bytes("emoji encrypted".encode("utf-8"))
    return base


def pack_fixture(tmp_path):
    container = tmp_path / "c.valt"
    folder = make_tree(tmp_path / "src")
    folder_key = new_key()
    write_skeleton(container, SLOTS)
    segment_offset, segment_len, index_len = pack_folder(container, str(folder), folder_key)
    return container, folder, folder_key, segment_offset, segment_len, index_len


def read_idx(container, segment_offset, folder_key, index_len):
    with open(container, "rb") as f:
        f.seek(segment_offset)
        blob = f.read(index_len)
    return json.loads(unlock(folder_key, blob[:12], blob[12:]))


# ---------- the index ----------

def test_index_unlocks_and_lists_everything(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_idx(container, seg_off, key, index_len)
    names = [e["name"] for e in entries]
    assert sorted(names) == sorted([
        "notes.txt", "docs/report.txt", "big.dat", "empty.txt", "🔐 secret.txt",
    ])


def test_starts_survive_the_seal_drift(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_idx(container, seg_off, key, index_len)
    for i in range(1, len(entries)):
        prev, cur = entries[i - 1], entries[i]
        prev_chunks = math.ceil(prev["size"] / CHUNK)
        assert cur["start"] == prev["start"] + prev["size"] + 16 * prev_chunks


# ---------- the bytes on disk round-trip, chunk by chunk ----------

def test_every_file_decrypts_back_identically(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_idx(container, seg_off, key, index_len)

    with open(container, "rb") as f:
        for file_number, e in enumerate(entries):
            chunks = math.ceil(e["size"] / CHUNK) if e["size"] else 0
            data = b""
            for c in range(chunks):
                clen = min(CHUNK, e["size"] - c * CHUNK) + 16   # + the seal
                pos = seg_off + index_len + e["start"] + c * (CHUNK + 16)
                f.seek(pos)
                nonce = u32(file_number) + u64(c)
                data += unlock(key, nonce, f.read(clen))
            original = (folder / e["name"]).read_bytes()
            assert data == original


# ---------- hygiene ----------

def test_names_use_forward_slashes(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_idx(container, seg_off, key, index_len)
    for e in entries:
        assert "\\" not in e["name"]
        assert "//" not in e["name"]
    assert "docs/report.txt" in [e["name"] for e in entries]


def test_packed_segment_is_noise(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    with open(container, "rb") as f:
        f.seek(seg_off + index_len)
        sample = f.read(256 * 1024)
    run = best = 0
    for byte in sample:
        run = run + 1 if 32 <= byte < 127 else 0
        best = max(best, run)
    assert best < 25


def test_collect_files_sanitizes(tmp_path):
    folder = make_tree(tmp_path / "src")
    entries = collect_files(str(folder))
    names = [n for n, s in entries]
    assert "docs/report.txt" in names
    for n in names:
        assert "\\" not in n
        assert "//" not in n
        assert not n.startswith("/")


def test_plan_starts_accounts_for_seals():
    entries = [("a", 100_000), ("b", 70_000), ("c", 0)]
    planned, total = plan_starts(entries)
    assert planned[0]["start"] == 0
    assert planned[1]["start"] == 100_000 + 16 * 2      # a: 2 chunks -> 2 seals
    assert planned[2]["start"] == planned[1]["start"] + 70_000 + 16 * 2
    assert total == planned[2]["start"]                  # empty file adds nothing


# ---------- the v1.1 append model ----------

def test_empty_folder_packs_a_bare_index(tmp_path):
    container = tmp_path / "c.valt"
    write_skeleton(container, SLOTS)
    empty = tmp_path / "nothing"
    empty.mkdir()
    key = new_key()
    segment_offset, segment_len, index_len = pack_folder(container, str(empty), key)
    assert read_idx(container, segment_offset, key, index_len) == []


def test_second_pack_appends_right_after_the_first(tmp_path):
    container = tmp_path / "c.valt"
    write_skeleton(container, SLOTS)
    folder_a = tmp_path / "a"; folder_a.mkdir()
    folder_b = tmp_path / "b"; folder_b.mkdir()
    (folder_a / "only_a.txt").write_bytes(b"A" * 1000)
    (folder_b / "only_b.txt").write_bytes(b"B" * 1000)
    key_a, key_b = new_key(), new_key()

    off_a, len_a, idx_a = pack_folder(container, str(folder_a), key_a)
    off_b, len_b, idx_b = pack_folder(container, str(folder_b), key_b)

    assert off_b == off_a + len_a            # packed back-to-back, no gap
    entries_a = read_idx(container, off_a, key_a, idx_a)
    entries_b = read_idx(container, off_b, key_b, idx_b)
    assert [e["name"] for e in entries_a] == ["only_a.txt"]
    assert [e["name"] for e in entries_b] == ["only_b.txt"]
