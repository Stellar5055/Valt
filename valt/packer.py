import os, json, math
from valt.crypto import random_bytes, lock, u32, u64

CHUNK = 65536


def collect_files(folder):
    if not os.path.isdir(folder):
        raise ValueError(f"not a folder: {folder}")

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
        chunk_count = math.ceil(size / CHUNK)
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


def pack_folder(container_path, folder, folder_key, progress=None, label=None):
    """Append one compartment at end-of-file. No fits-check: the folder
    defines its own segment. Returns (segment_offset, segment_len, index_len).

    progress(done, total) fires as ciphertext is written, if provided."""
    if label is None:
        label = os.path.basename(os.path.normpath(folder))
    entries = collect_files(folder)
    planned, total_ct = plan_starts(entries)
    index_blob, index_len = build_index(planned, folder_key)
    segment_len = index_len + total_ct

    with open(container_path, "r+b") as f:
        f.seek(0, os.SEEK_END)
        segment_offset = f.tell()

        done = 0
        if progress:
            progress(done, segment_len, label)

        f.write(index_blob)
        done += index_len
        if progress:
            progress(done, segment_len)

        for file_number, entry in enumerate(planned):
            if entry["size"] == 0:
                continue

            full_path = os.path.join(folder, entry["name"].replace("/", os.sep))
            with open(full_path, "rb") as src:
                chunk_number = 0
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    nonce = u32(file_number) + u64(chunk_number)
                    ct = lock(folder_key, nonce, chunk)
                    f.write(ct)
                    done += len(ct)
                    if progress:
                        progress(done, segment_len)
                    chunk_number += 1

    return segment_offset, segment_len, index_len
