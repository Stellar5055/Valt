"""Stage 2 — automatic checks for valt/crypto.py.

Each test guards one promise from SPEC.md section 1.
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import time

import pytest
from cryptography.exceptions import InvalidTag

from valt.crypto import (
    new_key,
    random_bytes,
    password_to_key,
    lock,
    unlock,
    u16, u32, u64,
    read_u16, read_u32, read_u64,
)


# ---------- keys and randomness ----------

def test_new_key_is_32_random_bytes():
    k1 = new_key()
    k2 = new_key()
    assert len(k1) == 32
    assert k1 != k2                       # two keys are never the same


def test_random_bytes_gives_the_right_amount():
    assert len(random_bytes(1)) == 1
    assert len(random_bytes(12)) == 12    # a nonce
    assert len(random_bytes(16)) == 16    # a salt
    assert random_bytes(32) != random_bytes(32)


# ---------- password -> key (Argon2id, the slow cooker) ----------

def test_same_password_and_salt_give_the_same_key():
    salt = random_bytes(16)
    assert password_to_key("hello", salt) == password_to_key("hello", salt)


def test_different_salt_gives_a_different_key():
    # every safe has its own salt, so the same password makes a different
    # key per safe -- this is why the app must try every safe (SPEC P2)
    k1 = password_to_key("hello", random_bytes(16))
    k2 = password_to_key("hello", random_bytes(16))
    assert k1 != k2


def test_different_password_gives_a_different_key():
    salt = random_bytes(16)
    assert password_to_key("hello", salt) != password_to_key("hunter2", salt)


def test_password_key_is_32_bytes_and_slow_on_purpose():
    t0 = time.monotonic()
    key = password_to_key("correct horse battery staple", random_bytes(16))
    elapsed = time.monotonic() - t0
    assert len(key) == 32
    assert elapsed > 0.05                 # never instant (SPEC P6: guessing is expensive)


# ---------- lock / unlock (AEAD: scramble AND seal) ----------

def test_round_trip():
    key, nonce = new_key(), random_bytes(12)
    ct = lock(key, nonce, b"hello valt")
    assert ct != b"hello valt"            # locked text is not the text
    assert unlock(key, nonce, ct) == b"hello valt"


def test_empty_data_round_trips():
    key, nonce = new_key(), random_bytes(12)
    assert unlock(key, nonce, lock(key, nonce, b"")) == b""


def test_big_data_round_trips():
    key, nonce = new_key(), random_bytes(12)
    big = random_bytes(3 * 64 * 1024 + 7)  # 3 chunks and a bit
    assert unlock(key, nonce, lock(key, nonce, big)) == big


def test_wrong_key_is_rejected():
    key, nonce = new_key(), random_bytes(12)
    ct = lock(key, nonce, b"secret")
    with pytest.raises(InvalidTag):
        unlock(new_key(), nonce, ct)       # SPEC P1: no way in without the key


def test_tampered_ciphertext_is_rejected():
    key, nonce = new_key(), random_bytes(12)
    ct = bytearray(lock(key, nonce, b"secret"))
    ct[0] ^= 1                             # flip one bit of the locked text
    with pytest.raises(InvalidTag):
        unlock(key, nonce, bytes(ct))      # SPEC P5: tampering never yields data


def test_tampered_seal_is_rejected():
    key, nonce = new_key(), random_bytes(12)
    ct = bytearray(lock(key, nonce, b"secret"))
    ct[-1] ^= 1                            # the last 16 bytes are the seal
    with pytest.raises(InvalidTag):
        unlock(key, nonce, bytes(ct))


def test_aad_mismatch_is_rejected():
    # the aad is extra context welded into the seal (used by safes in Stage 3)
    key, nonce = new_key(), random_bytes(12)
    ct = lock(key, nonce, b"secret", aad=b"VALT")
    with pytest.raises(InvalidTag):
        unlock(key, nonce, ct, aad=b"valt")


def test_password_key_works_as_an_aead_key():
    # the two tools compose: boil a password, use the result as a lock key
    salt, nonce = random_bytes(16), random_bytes(12)
    key = password_to_key("my password", salt)
    ct = lock(key, nonce, b"it all fits together")
    assert unlock(key, nonce, ct) == b"it all fits together"
    with pytest.raises(InvalidTag):
        unlock(password_to_key("wrong password", salt), nonce, ct)


# ---------- the traps (these MUST stay errors) ----------

def test_nonce_must_be_exactly_12_bytes():
    key = new_key()
    with pytest.raises(ValueError):
        lock(key, random_bytes(8), b"oops")
    with pytest.raises(ValueError):
        lock(key, random_bytes(16), b"oops")


def test_key_must_be_exactly_32_bytes():
    with pytest.raises(ValueError):
        lock(random_bytes(16), random_bytes(12), b"oops")


# ---------- the number boxes ----------

def test_int_boxes_round_trip():
    for pack, read, value in (
        (u16, read_u16, 5),
        (u32, read_u32, 70_000),
        (u64, read_u64, 2**40 + 3),
    ):
        assert read(pack(value)) == value


def test_boxes_are_little_endian_with_fixed_width():
    assert u16(1) == b"\x01\x00"
    assert u32(1) == b"\x01\x00\x00\x00"
    assert u64(1) == b"\x01\x00\x00\x00\x00\x00\x00\x00"


# ---------- the official proof (RFC 8439 section 2.8.2) ----------
# This is the published example from the document that DEFINES
# ChaCha20-Poly1305. If our lock() reproduces the official ciphertext and
# seal byte for byte, we are using the real algorithm -- not a lookalike.

def test_lock_matches_the_official_rfc_8439_test_vector():
    key = bytes.fromhex(
        "808182838485868788898a8b8c8d8e8f"
        "909192939495969798999a9b9c9d9e9f"
    )
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you "
        b"only one tip for the future, sunscreen would be it."
    )
    ct = lock(key, nonce, plaintext, aad=aad)
    assert ct[:16].hex() == "d31a8d34648e60db7b86afbc53ef7ec2"  # official start
    assert ct[-16:].hex() == "1ae10b594f09e26a7e902ecbd0600691"  # official seal
    assert unlock(key, nonce, ct, aad=aad) == plaintext
