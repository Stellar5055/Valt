"""Stage 6 — automatic checks for valt/unpacker.py.

The read side, and the round-trip milestone: pack (Stage 5), extract here,
every byte identical. Plus the zip-slip defense.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import hashlib

import pytest
from cryptography.exceptions import InvalidTag

from valt.crypto import new_key, random_bytes, u16, lock
from valt.container import create_empty, read_header, FormatError
from valt.packer import pack_folder
from valt.unpacker import read_index, extract_file, extract_all

SIZE = 4 * 1024 * 1024
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
    create_empty(container, SIZE, SLOTS)
    index_len = pack_folder(container, 0, str(folder), folder_key)
    return container, folder, folder_key, index_len


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------- 🏁 the milestone: the full round trip ----------

def test_round_trip_every_file_byte_identical(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, 0, folder_key, index_len, str(dest))
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            out = dest / path.relative_to(folder)
            assert out.exists(), f"missing: {path.name}"
            assert sha(out.read_bytes()) == sha(path.read_bytes()), f"different: {path.name}"


def test_read_index_lists_everything_in_order(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    expected = sorted([
        "notes.txt", "docs/report.txt", "exact.bin",
        "exact_plus_1.bin", "empty.txt", "🔐 secret.txt",
    ])
    assert [e["name"] for e in entries] == expected


def test_empty_file_is_recreated(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, 0, folder_key, index_len, str(dest))
    assert (dest / "empty.txt").exists()
    assert (dest / "empty.txt").stat().st_size == 0


def test_nested_directories_are_created(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    extract_all(container, 0, folder_key, index_len, str(dest))
    assert (dest / "docs" / "report.txt").exists()


# ---------- fail closed ----------

def test_wrong_folder_key_fails_clean(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    dest = tmp_path / "out"
    with pytest.raises(FormatError):
        extract_all(container, 0, "wrong password", index_len, str(dest))


def test_tampered_index_is_rejected(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    slot_count, file_size, data_offset, segment_len = read_header(container)
    data = bytearray(open(container, "rb").read())
    data[data_offset + 30] ^= 1                  # inside the locked index
    open(container, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_index(container, 0, folder_key, index_len)


def test_corrupted_chunk_fails_and_cleans_up_partial_file(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    slot_count, file_size, data_offset, segment_len = read_header(container)
    geometry = (slot_count, file_size, data_offset, segment_len)

    entry = next(e for e in entries if e["name"] == "docs/report.txt")
    data_base = data_offset + index_len
    data = bytearray(open(container, "rb").read())
    data[data_base + entry["start"] + 100] ^= 1  # kill one bit of chunk 0
    open(container, "wb").write(bytes(data))

    dest = tmp_path / "out"
    with pytest.raises((FormatError, InvalidTag)):
        extract_file(container, geometry, folder_key, index_len, 0,
                     dict(entry), str(dest))
    assert not (dest / "docs" / "report.txt").exists()   # partial file wiped


def test_extract_blocks_path_traversal(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    geometry = read_header(container)
    dest = tmp_path / "out"
    dest.mkdir()
    evil = {"name": "../evil.txt", "start": 0, "size": 10}
    with pytest.raises(FormatError):
        extract_file(container, geometry, folder_key, index_len, 0, evil, str(dest))
    assert not (tmp_path / "evil.txt").exists()          # nothing escaped the dest


def test_bad_slot_is_rejected(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    with pytest.raises(FormatError):
        read_index(container, 5, folder_key, index_len)  # slots are 0..1
    with pytest.raises(FormatError):
        read_index(container, -1, folder_key, index_len)


# ---------- stage 5 regression guard: the writer still stands ----------

def test_packer_still_round_trips(tmp_path):
    container, folder, folder_key, index_len = pack_fixture(tmp_path)
    entries = read_index(container, 0, folder_key, index_len)
    assert len(entries) == 6
