import os
from valt.crypto import random_bytes, u16, read_u16


class FormatError(Exception):
    pass


def segment_geometry(file_size, slot_count):
    chunk = slot_count * 64 * 1024
    if file_size % chunk !=0:
        file_size = (file_size // chunk + 1) * chunk

    data_offset = 8 + 128 * slot_count
    segment_len = (file_size - data_offset) // slot_count
    return file_size, data_offset, segment_len


def create_empty(path, size, slot_count=8):
    if slot_count < 2 or slot_count > 16:
        raise ValueError(f"slot_count must be 2 - 16, received {slot_count}")

    file_size, data_offset, segment_len = segment_geometry(size, slot_count)

    if segment_len < 1024 * 1024:
        raise ValueError("Size too small, each segment must be atleast 1 MiB")

    header = b"VALT" + u16(1) + u16(slot_count)

    try:
        with open(path, "wb") as f:
            f.write(header)

            remaining = file_size - 8
            chunk = 1024 * 1024
            while remaining > 0:
                to_write = min(chunk, remaining)
                f.write(random_bytes(to_write))
                remaining -= to_write

        if os.path.getsize(path) != file_size:
            os.remove(path)
            raise FormatError("Invalid or corrupted container")

    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


def read_header(path):
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

    file_size = os.path.getsize(path)
    file_size_r, data_offset, segment_len = segment_geometry(file_size, slot_count)

    if file_size_r != file_size:
        raise FormatError("Invalid or corrupted container")

    if segment_len < 1024 * 1024:
        raise FormatError("Invalid or corrupted container")

    return slot_count, file_size_r, data_offset, segment_len