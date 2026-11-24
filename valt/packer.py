import os, json, math
from valt.crypto import random_bytes, lock, u32, u64
from valt.container import read_header, FormatError


def collect_files(folder):
    entries = []

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for filename in files:
            full_path = os.path.join(root, filename)
            
            if os.path.islink(full_path):
                continue

            rel = os.path.relpath(full_path, folder)
            rel = rel.replace("\\", "/")

            if ".." in rel.split("/"):
                raise ValueError(f"bad path: {rel}")
            if rel.startswith("/"):
                raise ValueError(f"bad path: {rel}")
            if len(rel.encode("utf-8")) > 1024:
                raise ValueError(f"name too long: {rel}")

            size = os.path.getsize(full_path)
            entries.append((rel, size))

    entries.sort()
    return entries


def plan_starts(entries):
    planned = []
    running = 0

    for name, size in entries:
        chunk_count = math.ceil(size / 65536) if size > 0 else 0
        ct_len = size + 16 * chunk_count
        planned.append({"name": name, "size": size, "start": running})
        running += ct_len
    return planned, running


def build_index(planned, folder_key):
    json_bytes = json.dumps(planned).encode("utf-8")
    nonce = random_bytes(12)
    ct = lock(folder_key, nonce, json_bytes)
    blob = nonce + ct
    return blob, len(blob)


def pack_folder(container_path, slot, folder, folder_key):
    slot_count, file_size, data_offset, segment_len = read_header(container_path)

    if slot <0 or slot >= slot_count:
        raise ValueError(f"slot {slot} is out of range 0..{slot_count - 1}")

    segment_start = data_offset + slot * segment_len

    entries = collect_files(folder)
    planned, total_ct = plan_starts(entries)
    index_blob, index_len = build_index(planned, folder_key)

    if index_len + total_ct > segment_len:
        raise ValueError("folder is too large to fit in this segment")

    with open(container_path, "r+b") as f:
        f.seek(segment_start)
        f.write(index_blob)

        for file_number, entry in enumerate(planned):
            name   = entry["name"]
            size   = entry["size"]
            start  = entry["start"]
            full_path = os.path.join(folder, name.replace("/", os.sep))

            if size == 0:
                continue

            f.seek(segment_start + index_len + start)
            with open(full_path, "rb") as src:
                chunk_number = 0
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    nonce = u32(file_number) + u64(chunk_number)
                    ct = lock(folder_key, nonce, chunk)
                    f.write(ct)
                    chunk_number += 1
    return index_len
   
                