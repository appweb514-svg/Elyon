from __future__ import annotations

from elyon_api.security import (
    hash_code,
    hash_password,
    hash_token,
    new_session_token,
    new_short_code,
    verify_password,
    verify_session_token,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-long-pass")
    assert hashed != "s3cret-long-pass"
    assert verify_password("s3cret-long-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_session_token_roundtrip():
    token = new_session_token("secret", "u1", "o1", "org_admin", 3600)
    payload = verify_session_token("secret", token)
    assert payload["uid"] == "u1"
    assert payload["org_id"] == "o1"
    assert payload["role"] == "org_admin"


def test_session_token_tampered():
    token = new_session_token("secret", "u1", None, "viewer", 3600)
    assert verify_session_token("secret", token + "x") is None
    assert verify_session_token("autre-secret", token) is None


def test_short_code_and_hashes():
    code = new_short_code()
    assert len(code) == 6
    assert code == code.upper()
    assert hash_code(code) == hash_code(code.upper())
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")