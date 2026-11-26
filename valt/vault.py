from valt.crypto import new_key, u16
from valt.container import create_empty, read_header, FormatError
from valt.safes import build_payload, wrap_safe, try_open_safe, safe_aad
from valt.packer import pack_folder
from valt.unpacker import read_index


def _header_bytes(slot_count):
    return b"VALT" + u16(1) + u16(slot_count)


def create(path, size, slot_count, compartments):
    create_empty(path, size, slot_count)
    slot_count, file_size, data_offset, segment_len = read_header(path)
    header_bytes = _header_bytes(slot_count)

    for slot, (folder, password, name) in enumerate(compartments):
        folder_key = new_key()
        
        index_len = pack_folder(path, slot, folder, folder_key)

        payload = build_payload(folder_key, index_len, name)
        aad = safe_aad(header_bytes, slot)
        safe = wrap_safe(password, payload, aad)

        with open(path, "r+b") as f:
            f.seek(8 + 128 * slot)
            f.write(safe)

    return slot_count, file_size, data_offset, segment_len


def open_container(path, password):
    slot_count, file_size, data_offset, segment_len = read_header(path)
    header_bytes = _header_bytes(slot_count)

    results = []

    with open(path, "rb") as f:
        for slot in range(slot_count):
            f.seek(8 + 128 * slot)
            safe = f.read(128)

            aad = safe_aad(header_bytes, slot)
            opened = try_open_safe(password, safe, aad)

            if opened is None:
                continue

            folder_key, index_len, name = opened

            entries = read_index(path, slot, folder_key, index_len)

            results.append({
                "slot": slot,
                "name": name,
                "folder_key": folder_key,
                "index_len": index_len,
                "entries": entries,
            })

    return results

