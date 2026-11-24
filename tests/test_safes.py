"""Stage 3 — automatic checks for valt/safes.py.

The heart of the whole format: locked, empty, and broken safes must all be
indistinguishable to the code (SPEC P2 / P4).
Run from the repo root:   .venv\\Scripts\\python -m pytest -v
"""
import pytest

from valt.crypto import new_key, random_bytes, u16, u64
from valt.safes import safe_aad, build_payload, parse_payload, wrap_safe, try_open_safe


# a stand-in for the real 8-byte header: "VALT" + version 1 + 8 slots
FAKE_HEADER = b"VALT" + u16(1) + u16(8)


def make_payload(name="my stuff"):
    return build_payload(new_key(), 123456, name)


def wrap_at_slot(payload, password, slot):
    return wrap_safe(password, payload, safe_aad(FAKE_HEADER, slot))


def open_at_slot(safe, password, slot):
    return try_open_safe(password, safe, safe_aad(FAKE_HEADER, slot))


# ---------- the happy path ----------

def test_wrap_returns_exactly_128_bytes():
    safe = wrap_at_slot(make_payload(), "correct horse", 0)
    assert len(safe) == 128


def test_right_password_opens_the_safe_intact():
    folder_key = new_key()
    payload = build_payload(folder_key, 123456, "my stuff")
    safe = wrap_at_slot(payload, "correct horse", 0)
    opened = open_at_slot(safe, "correct horse", 0)
    assert opened is not None
    out_key, out_len, out_name = opened
    assert out_key == folder_key
    assert out_len == 123456
    assert out_name == "my stuff"


# ---------- the privacy property: locked = empty = broken ----------

def test_wrong_password_returns_none():
    safe = wrap_at_slot(make_payload(), "correct horse", 0)
    assert open_at_slot(safe, "wrong horse", 0) is None


def test_128_random_bytes_returns_none():
    # an empty safe is pure random junk -- and must be indistinguishable
    assert open_at_slot(random_bytes(128), "correct horse", 0) is None


def test_tampered_nonce_region_returns_none():
    safe = bytearray(wrap_at_slot(make_payload(), "correct horse", 0))
    safe[20] ^= 1                            # inside the nonce (bytes 16..27)
    assert open_at_slot(bytes(safe), "correct horse", 0) is None


def test_tampered_locked_region_returns_none():
    safe = bytearray(wrap_at_slot(make_payload(), "correct horse", 0))
    safe[60] ^= 1                            # inside the locked payload
    assert open_at_slot(bytes(safe), "correct horse", 0) is None


def test_tampered_salt_region_returns_none():
    safe = bytearray(wrap_at_slot(make_payload(), "correct horse", 0))
    safe[3] ^= 1                             # inside the salt -- wrong key comes out
    assert open_at_slot(bytes(safe), "correct horse", 0) is None


def test_safe_moved_to_another_slot_returns_none():
    # the aad weld: this safe only opens in the slot it was wrapped for
    safe = wrap_at_slot(make_payload(), "correct horse", 0)
    assert open_at_slot(safe, "correct horse", 5) is None


# ---------- no patterns, no shortcuts ----------

def test_two_wraps_of_the_same_thing_look_nothing_alike():
    payload = make_payload()
    a = wrap_at_slot(payload, "correct horse", 0)
    b = wrap_at_slot(payload, "correct horse", 0)
    assert a != b                            # fresh salt + nonce every time


def test_malformed_payload_still_fails_closed():
    # a payload that unlocks fine but is not a real payload -> None, not a crash
    from valt.crypto import lock, password_to_key
    salt, nonce = random_bytes(16), random_bytes(12)
    key = password_to_key("correct horse", salt)
    fake = random_bytes(16) + nonce + lock(key, nonce, b"garbage")
    assert try_open_safe("correct horse", fake, safe_aad(FAKE_HEADER, 0)) is None


# ---------- the name budget (bytes, not characters) ----------

def test_name_of_43_bytes_round_trips():
    safe = wrap_at_slot(make_payload("a" * 43), "correct horse", 0)
    opened = open_at_slot(safe, "correct horse", 0)
    assert opened[2] == "a" * 43


def test_name_of_44_bytes_is_rejected():
    with pytest.raises(ValueError):
        make_payload("a" * 44)


def test_unicode_name_round_trips():
    safe = wrap_at_slot(make_payload("🔐 vault 🔐"), "correct horse", 0)
    opened = open_at_slot(safe, "correct horse", 0)
    assert opened[2] == "🔐 vault 🔐"


def test_empty_name_is_allowed():
    opened = open_at_slot(wrap_at_slot(make_payload(""), "correct horse", 0),
                          "correct horse", 0)
    assert opened[2] == ""
