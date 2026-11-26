import os, json, math
from valt.crypto import unlock, u32, u64
from valt.container import FormatError

CHUNK = 65536


def read_index(container_path, segment_offset, segment_len, folder_key, index_len):
    with open(container_path, "rb") as f:
        f.seek(segment_offset)
        blob = f.read(index_len)

    if len(blob) != index_len:
        raise FormatError("Invalid or corrupted container")

    nonce = blob[:12]
    ct = blob[12:]

    try:
        entries = json.loads(unlock(folder_key, nonce, ct))
    except Exception:
        raise FormatError("Invalid or corrupted container")

    if not isinstance(entries, list):
        raise FormatError("Invalid or corrupted container")

    data_area = segment_len - index_len

    for entry in entries:
        if not isinstance(entry, dict) or set(entry.keys()) != {"name", "start", "size"}:
            raise FormatError("Invalid or corrupted container")

        name = entry["name"]
        start = entry["start"]
        size = entry["size"]

        if not isinstance(name, str) or not isinstance(start, int) or not isinstance(size, int):
            raise FormatError("Invalid or corrupted container")
        if start < 0 or size < 0:
            raise FormatError("Invalid or corrupted container")
        if len(name.encode("utf-8")) > 1024:
            raise FormatError("Invalid or corrupted container")
        if ".." in name.split("/") or name.startswith("/") or "\\" in name:
            raise FormatError("Invalid or corrupted container")

        chunks = math.ceil(size / CHUNK) if size > 0 else 0
        if start + size + 16 * chunks > data_area:
            raise FormatError("Invalid or corrupted container")

    return entries


def extract_file(container_path, segment_offset, segment_len, folder_key, index_len,
                 file_number, entry, dest_dir):
    data_base = segment_offset + index_len

    name = entry["name"]
    size = entry["size"]
    start = entry["start"]

    dest_path = os.path.realpath(os.path.join(dest_dir, name.replace("/", os.sep)))
    dest_dir_real = os.path.realpath(dest_dir)
    if not dest_path.startswith(dest_dir_real + os.sep) and dest_path != dest_dir_real:
        raise FormatError("Invalid or corrupted container")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    chunk_count = math.ceil(size / CHUNK) if size > 0 else 0
    stride = CHUNK + 16

    try:
        with open(dest_path, "wb") as out, open(container_path, "rb") as f:
            for c in range(chunk_count):
                plain_len = min(CHUNK, size - c * CHUNK)
                read_len = plain_len + 16

                f.seek(data_base + start + c * stride)
                ct = f.read(read_len)

                if len(ct) != read_len:
                    raise FormatError("Invalid or corrupted container")

                nonce = u32(file_number) + u64(c)
                out.write(unlock(folder_key, nonce, ct))

        if os.path.getsize(dest_path) != size:
            raise FormatError("Invalid or corrupted container")

    except Exception:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise


def extract_all(container_path, segment_offset, segment_len, folder_key, index_len, dest_dir):
    entries = read_index(container_path, segment_offset, segment_len, folder_key, index_len)
    for file_number, entry in enumerate(entries):
        extract_file(container_path, segment_offset, segment_len, folder_key, index_len,
                     file_number, entry, dest_dir)
