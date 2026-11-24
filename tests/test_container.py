"""Stage 4 — automatic checks for valt/container.py.

The container on disk: exact layout, fail-closed header, junk that hides
everything. This is SPEC P2's first appearance on disk.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import os

import pytest

from valt.crypto import u16
from valt.container import FormatError, segment_geometry, create_empty, read_header

SIZE = 4 * 1024 * 1024   # 4 MiB -- small enough for fast tests
SLOTS = 2


def make(path, size=SIZE, slots=SLOTS):
    create_empty(path, size, slots)


def corrupt(path, changes):
    """Overwrite raw bytes at given offsets: {offset: new_bytes}."""
    data = bytearray(open(path, "rb").read())
    for offset, value in changes.items():
        data[offset:offset + len(value)] = value
    open(path, "wb").write(bytes(data))


# ---------- creation ----------

def test_create_makes_a_file_of_the_exact_size(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    assert os.path.getsize(p) == SIZE


def test_header_bytes_are_exactly_per_spec(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    assert open(p, "rb").read(8) == b"VALT" + u16(1) + u16(SLOTS)


def test_too_small_size_is_rejected_and_leaves_no_file_behind(tmp_path):
    p = tmp_path / "c.valt"
    with pytest.raises(ValueError):
        make(p, size=1024 * 1024, slots=2)     # segments would be < 1 MiB
    assert not p.exists()                      # validate BEFORE writing


def test_slot_count_out_of_range_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_empty(tmp_path / "c.valt", SIZE, 1)
    with pytest.raises(ValueError):
        create_empty(tmp_path / "c.valt", SIZE, 99)


def test_segment_geometry_math():
    file_size, data_offset, segment_len = segment_geometry(SIZE, 2)
    assert file_size == SIZE
    assert data_offset == 8 + 128 * 2
    assert segment_len == (SIZE - data_offset) // 2


# ---------- the gatekeeper: read_header ----------

def test_read_header_round_trips(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    slot_count, file_size, data_offset, segment_len = read_header(p)
    assert slot_count == SLOTS
    assert file_size == SIZE
    assert data_offset == 8 + 128 * SLOTS
    assert segment_len == (SIZE - data_offset) // SLOTS


def test_corrupted_magic_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    corrupt(p, {0: b"XALT"})
    with pytest.raises(FormatError):
        read_header(p)


def test_corrupted_version_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    corrupt(p, {4: u16(2)})                    # a future spec version
    with pytest.raises(FormatError):
        read_header(p)


def test_bad_slot_count_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    corrupt(p, {6: u16(0)})
    with pytest.raises(FormatError):
        read_header(p)
    corrupt(p, {6: u16(99)})
    with pytest.raises(FormatError):
        read_header(p)


def test_truncated_file_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    data = open(p, "rb").read()
    open(p, "wb").write(data[:-10])            # chop 10 bytes off the end
    with pytest.raises(FormatError):
        read_header(p)


def test_bloated_file_is_rejected(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    data = open(p, "rb").read()
    open(p, "wb").write(data + b"extra bytes")  # someone glued bytes on
    with pytest.raises(FormatError):
        read_header(p)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(FormatError):
        read_header(tmp_path / "nope.valt")


# ---------- the junk must hide everything ----------

def test_two_containers_with_same_settings_differ(tmp_path):
    a, b = tmp_path / "a.valt", tmp_path / "b.valt"
    make(a)
    make(b)
    assert open(a, "rb").read() != open(b, "rb").read()


def test_body_is_real_junk_not_zeros_or_text(tmp_path):
    p = tmp_path / "c.valt"
    make(p)
    body = open(p, "rb").read()[264:]          # everything after the header
    assert body != b"\x00" * len(body)         # not lazily zero-filled
    # no long printable-ASCII run anywhere: no filenames, headers, hints
    sample = body[264:264 + 256 * 1024]
    run = best = 0
    for byte in sample:
        run = run + 1 if 32 <= byte < 127 else 0
        best = max(best, run)
    assert best < 25
