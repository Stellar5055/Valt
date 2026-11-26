"""Stage 4 (v1.1) — checks for valt/container.py.

An empty vault = header + junk safes. Nothing else on disk.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import os

import pytest

from valt.crypto import u16
from valt.container import FormatError, write_skeleton, read_header

SLOTS = 4


def test_skeleton_is_exactly_header_plus_safes(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    assert os.path.getsize(p) == 8 + 128 * SLOTS


def test_header_bytes_are_exactly_per_spec(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    assert open(p, "rb").read(8) == b"VALT" + u16(1) + u16(SLOTS)


def test_read_header_round_trips(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    slot_count, data_offset = read_header(p)
    assert slot_count == SLOTS
    assert data_offset == 8 + 128 * SLOTS


def test_corrupted_magic_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    data = bytearray(open(p, "rb").read())
    data[0:4] = b"XALT"
    open(p, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_header(p)


def test_corrupted_version_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    data = bytearray(open(p, "rb").read())
    data[4:6] = u16(2)                       # a future spec version
    open(p, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_header(p)


def test_bad_slot_count_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    data = bytearray(open(p, "rb").read())
    data[6:8] = u16(0)
    open(p, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_header(p)
    data[6:8] = u16(99)
    open(p, "wb").write(bytes(data))
    with pytest.raises(FormatError):
        read_header(p)


def test_truncated_safes_area_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    data = open(p, "rb").read()
    open(p, "wb").write(data[:8 + 64])       # chop into the safes
    with pytest.raises(FormatError):
        read_header(p)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(FormatError):
        read_header(tmp_path / "nope.valt")


def test_slot_count_out_of_range_raises(tmp_path):
    with pytest.raises(ValueError):
        write_skeleton(tmp_path / "c.valt", 1)
    with pytest.raises(ValueError):
        write_skeleton(tmp_path / "c.valt", 99)


def test_two_skeletons_differ(tmp_path):
    a, b = tmp_path / "a.valt", tmp_path / "b.valt"
    write_skeleton(a, SLOTS)
    write_skeleton(b, SLOTS)
    assert open(a, "rb").read() != open(b, "rb").read()   # fresh junk


def test_safes_are_junk_not_zeros(tmp_path):
    p = tmp_path / "c.valt"
    write_skeleton(p, SLOTS)
    safes = open(p, "rb").read()[8:]
    assert safes != b"\x00" * len(safes)
