import secrets, struct
from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

def new_key():
    return secrets.token_bytes(32)


def random_bytes(n):
    return secrets.token_bytes(n)


def password_to_key(password, salt):
    return hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    )


def lock(key, nonce, data, aad=None):
    return ChaCha20Poly1305(key).encrypt(nonce, data, aad)


def unlock(key, nonce, data, aad=None):
    return ChaCha20Poly1305(key).decrypt(nonce, data, aad)


def u16(n): return struct.pack("<H", n)
def u32(n): return struct.pack("<I", n)
def u64(n): return struct.pack("<Q", n)


def read_u16(b): return struct.unpack("<H", b)[0]
def read_u32(b): return struct.unpack("<I", b)[0]
def read_u64(b): return struct.unpack("<Q", b)[0]

