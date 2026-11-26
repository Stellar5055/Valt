import os
from valt.crypto import random_bytes, u16, read_u16


class FormatError(Exception):
    pass


def write_skeleton(path, slot_count):
    """Header + slot_count junk safes. An empty vault is exactly this."""
    if slot_count < 2 or slot_count > 16:
        raise ValueError(f"slot_count must be 2 - 16, received {slot_count}")

    try:
        with open(path, "wb") as f:
            f.write(b"VALT" + u16(1) + u16(slot_count))
            f.write(random_bytes(128 * slot_count))   # every safe starts as junk
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


def read_header(path):
    """The front door. Validates the header, returns (slot_count, data_offset)."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        raise FormatError("Invalid or corrupted container")

    if (len(header) < 8) or (header[0:4] != b"VALT") or (read_u16(header[4:6]) != 1):
        raise FormatError("Invalid or corrupted container")

    slot_count = read_u16(header[6:8])
    if slot_count < 2 or slot_count > 16:
        raise FormatError("Invalid or corrupted container")

    data_offset = 8 + 128 * slot_count
    if os.path.getsize(path) < data_offset:
        raise FormatError("Invalid or corrupted container")

    return slot_count, data_offset
