import os, struct
from valt.crypto import random_bytes, password_to_key, unlock, lock, u64, u32, read_u64, read_u32
from cryptography.exceptions import InvalidTag


def safe_aad(header_bytes, slot_index):
    return header_bytes + struct.pack("<H", slot_index)


def build_payload(folder_key, segment_offset, segment_len, index_len, name):
    name_bytes = name.encode("utf-8")

    if len(folder_key) != 32:
        raise ValueError("folder_key must be 32 bytes")

    if len(name_bytes) > 31:
        raise ValueError("Name too long. max 31 bytes")

    payload = (folder_key
               + u64(segment_offset)
               + u64(segment_len)
               + u32(index_len)
               + bytes([len(name_bytes)])
               + name_bytes)
    payload += random_bytes(84 - len(payload))   # pad to the 84-byte budget
    return payload


def parse_payload(payload):
    folder_key = payload[0:32]
    segment_offset = read_u64(payload[32:40])
    segment_len = read_u64(payload[40:48])
    index_len = read_u32(payload[48:52])
    name_len = payload[52]
    name = payload[53: 53 + name_len]

    if 53 + name_len > len(payload):
        raise ValueError("payload length mismatch")

    return folder_key, segment_offset, segment_len, index_len, name.decode("utf-8")


def resolve_label(folder, name):
    """Empty label -> the folder's basename. Too long -> trimmed to fit the
    31-byte budget on a character boundary (never mid-emoji)."""
    if not name:
        name = os.path.basename(os.path.normpath(folder))
    raw = name.encode("utf-8")
    if len(raw) > 31:
        raw = raw[:31]
        name = raw.decode("utf-8", errors="ignore")
    return name


def wrap_safe(password, payload, aad):
    salt = random_bytes(16)
    nonce = random_bytes(12)
    key = password_to_key(password, salt)
    ct = lock(key, nonce, payload, aad)

    return salt + nonce + ct

def try_open_safe(password, safe, aad):
    if len(safe) != 128:
        return None

    salt = safe[0:16]
    nonce = safe[16:28]
    ct = safe[28:128]

    try:
        key = password_to_key(password, salt)
        payload = unlock(key, nonce, ct, aad)
        return parse_payload(payload)
    
    except (InvalidTag, ValueError):
        return None
