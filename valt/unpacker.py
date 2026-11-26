import os, json, math
from cryptography.exceptions import InvalidTag
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
                 file_number, entry, dest_dir, progress=None):
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
    file_total = size + 16 * chunk_count
    done = 0
    if progress:
        progress(0, file_total)

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
                done += read_len
                if progress:
                    progress(done, file_total)

        if os.path.getsize(dest_path) != size:
            raise FormatError("Invalid or corrupted container")

    except Exception:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise


def extract_all(container_path, segment_offset, segment_len, folder_key, index_len, dest_dir,
                progress=None, label=None):
    entries = read_index(container_path, segment_offset, segment_len, folder_key, index_len)

    spans = []
    for e in entries:
        chunks = math.ceil(e["size"] / CHUNK) if e["size"] else 0
        spans.append(e["size"] + 16 * chunks)
    total = sum(spans)

    done = 0
    for file_number, entry in enumerate(entries):
        shifted = None
        if progress:
            def shifted(file_done, file_total, _base=done, _total=total, _label=label):
                if file_done == 0:
                    progress(_base, _total, _label)
                else:
                    progress(_base + file_done, _total)

        extract_file(container_path, segment_offset, segment_len, folder_key, index_len,
                     file_number, entry, dest_dir, progress=shifted)
        done += spans[file_number]


def verify_compartment(container_path, segment_offset, segment_len, folder_key, index_len,
                       progress=None, label=None):
    """Re-decrypt every chunk and discard the plaintext.
    Returns (True, None) or (False, first corrupted file name)."""
    entries = read_index(container_path, segment_offset, segment_len, folder_key, index_len)
    data_base = segment_offset + index_len

    spans = []
    for e in entries:
        chunks = math.ceil(e["size"] / CHUNK) if e["size"] else 0
        spans.append(e["size"] + 16 * chunks)
    total = sum(spans)
    done = 0
    if progress:
        progress(0, total, label)

    with open(container_path, "rb") as f:
        for file_number, e in enumerate(entries):
            chunks = math.ceil(e["size"] / CHUNK) if e["size"] else 0
            for c in range(chunks):
                plain_len = min(CHUNK, e["size"] - c * CHUNK)
                f.seek(data_base + e["start"] + c * (CHUNK + 16))
                ct = f.read(plain_len + 16)

                if len(ct) != plain_len + 16:
                    return False, e["name"]

                try:
                    unlock(folder_key, u32(file_number) + u64(c), ct)
                except InvalidTag:
                    return False, e["name"]

                done += plain_len + 16
                if progress:
                    progress(done, total)

    return True, None
