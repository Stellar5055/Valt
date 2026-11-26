import os, secrets
from valt.crypto import new_key, random_bytes, u16
from valt.container import write_skeleton, read_header
from valt.safes import build_payload, wrap_safe, try_open_safe, safe_aad, resolve_label, resolve_label
from valt.packer import pack_folder
from valt.unpacker import read_index


def _header_bytes(slot_count):
    return b"VALT" + u16(1) + u16(slot_count)


def create(path, compartments, progress=None):
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
            name = resolve_label(folder, name)
            folder_key = new_key()
            segment_offset, segment_len, index_len = pack_folder(path, folder, folder_key,
                                                                 progress=progress, label=name)

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


def open_container(path, password, progress=None):
    slot_count, data_offset = read_header(path)
    header_bytes = _header_bytes(slot_count)
    results = []

    with open(path, "rb") as f:
        for slot in range(slot_count):
            f.seek(8 + 128 * slot)
            safe = f.read(128)

            opened = try_open_safe(password, safe, safe_aad(header_bytes, slot))
            if progress:
                progress(slot + 1, slot_count)

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


def change_password(path, password, new_password, slot=None):
    """Re-lock the compartment(s) with a new password. Instant: only the
    84-byte payload is re-wrapped, the data is never touched."""
    views = [v for v in open_container(path, password)
             if slot is None or v["slot"] == slot]
    slot_count, data_offset = read_header(path)
    header_bytes = _header_bytes(slot_count)
    changed = []

    with open(path, "r+b") as f:
        for v in views:
            payload = build_payload(v["folder_key"], v["segment_offset"],
                                    v["segment_len"], v["index_len"], v["name"])
            new_safe = wrap_safe(new_password, payload, safe_aad(header_bytes, v["slot"]))
            f.seek(8 + 128 * v["slot"])
            f.write(new_safe)
            changed.append(v["name"])

    return changed


def remove(path, password, slot):
    """Wipe the safe at `slot`. Returns the compartment name, or None if the
    password does not open that safe. The segment's bytes stay behind as
    unreferenced noise; old backups still contain everything."""
    slot_count, data_offset = read_header(path)
    header_bytes = _header_bytes(slot_count)

    with open(path, "rb") as f:
        f.seek(8 + 128 * slot)
        safe = f.read(128)

    payload = try_open_safe(password, safe, safe_aad(header_bytes, slot))
    if payload is None:
        return None

    name = payload[4]

    with open(path, "r+b") as f:
        f.seek(8 + 128 * slot)
        f.write(random_bytes(128))       # the safe becomes junk again

    return name


def add(path, folder, password, name, slot, progress=None):
    """Append a new compartment at end-of-file and lock it into `slot`.
    The CLI must warn: if that slot secretly holds a compartment whose
    password is forgotten, writing here destroys it."""
    slot_count, data_offset = read_header(path)
    if not 0 <= slot < slot_count:
        raise ValueError(f"slot {slot} is out of range 0..{slot_count - 1}")

    folder_key = new_key()
    name = resolve_label(folder, name)
    segment_offset, segment_len, index_len = pack_folder(path, folder, folder_key,
                                                         progress=progress, label=name)
    payload = build_payload(folder_key, segment_offset, segment_len, index_len, name)
    safe = wrap_safe(password, payload, safe_aad(_header_bytes(slot_count), slot))

    with open(path, "r+b") as f:
        f.seek(8 + 128 * slot)
        f.write(safe)

    return name
