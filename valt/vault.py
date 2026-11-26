import os, secrets
from valt.crypto import new_key, random_bytes, u16
from valt.container import write_skeleton, read_header
from valt.safes import build_payload, wrap_safe, try_open_safe, safe_aad
from valt.packer import pack_folder
from valt.unpacker import read_index


def _header_bytes(slot_count):
    return b"VALT" + u16(1) + u16(slot_count)


def create(path, compartments):
    """compartments = [(folder, password, name), ...]. Size and slot count
    are derived: slots = compartments + 2 spares, size = exactly what the
    folders need plus a small random overhead (0 - 8 KiB)."""
    if len(compartments) > 16:
        raise ValueError("a vault holds at most 16 compartments")
    slots = max(2, min(16, len(compartments) + 2))

    try:
        write_skeleton(path, slots)
        header_bytes = _header_bytes(slots)

        for slot, (folder, password, name) in enumerate(compartments):
            folder_key = new_key()
            segment_offset, segment_len, index_len = pack_folder(path, folder, folder_key)

            payload = build_payload(folder_key, segment_offset, segment_len, index_len, name)
            safe = wrap_safe(password, payload, safe_aad(header_bytes, slot))

            with open(path, "r+b") as f:
                f.seek(8 + 128 * slot)
                f.write(safe)

        with open(path, "r+b") as f:
            f.seek(0, os.SEEK_END)
            f.write(random_bytes(secrets.randbelow(8193)))   # the small random overhead

    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


def open_container(path, password):
    slot_count, data_offset = read_header(path)
    header_bytes = _header_bytes(slot_count)
    results = []

    with open(path, "rb") as f:
        for slot in range(slot_count):
            f.seek(8 + 128 * slot)
            safe = f.read(128)

            opened = try_open_safe(password, safe, safe_aad(header_bytes, slot))
            if opened is None:
                continue

            folder_key, segment_offset, segment_len, index_len, name = opened
            entries = read_index(path, segment_offset, segment_len, folder_key, index_len)

            results.append({
                "slot": slot,
                "name": name,
                "folder_key": folder_key,
                "segment_offset": segment_offset,
                "segment_len": segment_len,
                "index_len": index_len,
                "entries": entries,
            })

    return results
