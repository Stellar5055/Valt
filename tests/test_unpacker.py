"""Stage 6 (v1.1) — checks for valt/unpacker.py.

The read side against v1.1 segments, plus the zip-slip defense.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import hashlib
import math
import os

import pytest
from cryptography.exceptions import InvalidTag

from valt.crypto import new_key, random_bytes, u32, u64, unlock
from valt.container import write_skeleton, read_header, FormatError
from valt.packer import pack_folder
from valt.unpacker import read_index, extract_file, extract_all

SLOTS = 2
CHUNK = 65536


def make_tree(base):
    """The deliberately awkward tree: boundaries, subfolder, empty, unicode."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "docs").mkdir()
    (base / "notes.txt").write_bytes(b"hello valt" * 10)
    (base / "docs" / "report.txt").write_bytes(random_bytes(70_000))
    (base / "exact.bin").write_bytes(random_bytes(CHUNK))             # exactly 1 chunk
    (base / "exact_plus_1.bin").write_bytes(random_bytes(CHUNK + 1))  # full chunk + 1-B tail
    (base / "empty.txt").write_bytes(b"")                             # zero chunks
    (base / "🔐 secret.txt").write_bytes("encrypted 🔐 emoji".encode("utf-8"))
    return base


def pack_fixture(tmp_path):
    container = tmp_path / "c.valt"
    folder = make_tree(tmp_path / "src")
    folder_key = new_key()
    write_skeleton(container, SLOTS)
    segment_offset, segment_len, index_len = pack_folder(container, str(folder), folder_key)
    return container, folder, folder_key, segment_offset, segment_len, index_len


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------- 🏁 the milestone: the full round trip ----------

def test_round_trip_every_file_byte_identical(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, seg_off, seg_len, key, index_len, str(dest))
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            out = dest / path.relative_to(folder)
            assert out.exists(), f"missing: {path.name}"
            assert sha(out.read_bytes()) == sha(path.read_bytes()), f"different: {path.name}"


def test_read_index_lists_everything_in_order(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_index(container, seg_off, seg_len, key, index_len)
    expected = sorted([
        "notes.txt", "docs/report.txt", "exact.bin",
        "exact_plus_1.bin", "empty.txt", "🔐 secret.txt",
    ])
    assert [e["name"] for e in entries] == expected


def test_empty_file_is_recreated(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, seg_off, seg_len, key, index_len, str(dest))
    assert (dest / "empty.txt").exists()
    assert (dest / "empty.txt").stat().st_size == 0


def test_nested_directories_are_created(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, seg_off, seg_len, key, index_len, str(dest))
    assert (dest / "docs" / "report.txt").exists()


# ---------- fail closed ----------

def test_wrong_folder_key_fails_clean(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    with pytest.raises(FormatError):
        extract_all(container, seg_off, seg_len, new_key(), index_len, str(dest))


def test_tampered_index_is_rejected(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    data = bytearray(open(container, "rb").read())
    data[seg_off + 30] ^= 1                  # inside the locked index
    open(container, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_index(container, seg_off, seg_len, key, index_len)


def test_corrupted_chunk_fails_and_cleans_up_partial_file(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    entries = read_index(container, seg_off, seg_len, key, index_len)
    entry = next(e for e in entries if e["name"] == "docs/report.txt")

    data = bytearray(open(container, "rb").read())
    data[seg_off + index_len + entry["start"] + 100] ^= 1   # kill one bit of chunk 0
    open(container, "wb").write(bytes(data))

    dest = tmp_path / "out"
    with pytest.raises((FormatError, InvalidTag)):
        extract_file(container, seg_off, seg_len, key, index_len, 1,
                     dict(entry), str(dest))
    assert not (dest / "docs" / "report.txt").exists()       # partial file wiped


def test_extract_blocks_path_traversal(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()
    evil = {"name": "../evil.txt", "start": 0, "size": 10}
    with pytest.raises(FormatError):
        extract_file(container, seg_off, seg_len, key, index_len, 0, evil, str(dest))
    assert not (tmp_path / "evil.txt").exists()              # nothing escaped the dest


def test_entry_beyond_the_segment_is_rejected(tmp_path):
    container, folder, key, seg_off, seg_len, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()
    far = {"name": "far.txt", "start": 10_000_000, "size": 5}
    with pytest.raises(FormatError):
        extract_file(container, seg_off, seg_len, key, index_len, 0, far, str(dest))
