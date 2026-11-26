import os, json, math
from valt.crypto import unlock, u32, u64
from valt.container import read_header, FormatError


def read_index(container_path, slot, folder_key, index_len):
    slot_count, file_size, data_offset, segment_len = read_header(container_path)

    if slot < 0 or slot >= slot_count:
        raise FormatError("invalid or corrupted container")

    segment_start = data_offset + slot * segment_len

    with open(container_path, "rb") as f:
        f.seek(segment_start)
        blob = f.read(index_len)

    if len(blob) != index_len:
        raise FormatError("invalid or corrupted container")

    nonce = blob[:12]
    ct = blob[12:]

    try:
        json_bytes = unlock(folder_key, nonce, ct)
        entries = json.loads(json_bytes)
    except Exception:
        raise FormatError("invalid or corrupted container")

    if not isinstance(entries, list):
        raise FormatError("invalid or corrupted container")

    for entry in entries:
        if set(entry.keys()) != {"name", "start", "size"}:
            raise FormatError("invalid or corrupted container")

        name = entry["name"]
        start = entry["start"]
        size = entry["size"]

        if not isinstance(name, str) or not isinstance(start, int) or not isinstance(size, int):            raise FormatError("invalid or corrupted container")
        if start < 0 or size < 0:
            raise FormatError("invalid or corrupted container")
        if len(name.encode("utf-8")) > 1024:
            raise FormatError("invalid or corrupted container")
        if ".." in name.split("/") or name.startswith("/") or "\\" in name:
            raise FormatError("invalid or corrupted container")

    return entries


def extract_file(container_path, geometry, folder_key, index_len, file_number, entry, dest_dir):
    slot_count, file_size, data_offset, segment_len = geometry
    slot = entry.get("_slot", 0)
    segment_start = data_offset + slot * segment_len
    data_base = segment_start + index_len

    name = entry["name"]
    size = entry["size"]
    start = entry["start"]

    dest_path = os.path.realpath(os.path.join(dest_dir, name.replace("/", os.sep)))
    dest_dir_real = os.path.realpath(dest_dir)
    if not dest_path.startswith(dest_dir_real + os.sep) and dest_path != dest_dir_real:
        raise FormatError("invalid or corrupted container")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    chunk_count = math.ceil(size / 65536) if size > 0 else 0
    stride = 65536 + 16

    try:
        with open(dest_path, "wb") as out:
            if size == 0:
                pass
            else:
                with open(container_path, "rb") as f:
                    for c in range(chunk_count):
                        plain_len = min(65536, size - c * 65536)
                        read_len = plain_len + 16

                        f.seek(data_base + start + c * stride)
                        ct = f.read(read_len)

                        if len(ct) != read_len:
                            raise FormatError("invalid or corrupted container")

                        nonce = u32(file_number) + u64(c)
                        plain = unlock(folder_key, nonce, ct)
                        out.write(plain)

        if os.path.getsize(dest_path) != size:
            raise FormatError("invalid or corrupted container")

    except Exception:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise


def extract_all(container_path, slot, folder_key, index_len, dest_dir):
    slot_count, file_size,  data_offset, segment_len = read_header(container_path)
    geometry = (slot_count, file_size, data_offset, segment_len)

    entries = read_index(container_path, slot, folder_key, index_len)

    for file_number, entry in enumerate(entries):
        entry["_slot"] = slot
        extract_file(container_path, geometry, folder_key, index_len, file_number, entry, dest_dir)