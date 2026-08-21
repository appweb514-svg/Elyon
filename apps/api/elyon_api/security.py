from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def _encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _sign(secret: str, raw: str) -> str:
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


def new_session_token(secret: str, user_id: str, org_id: str | None, role: str, ttl: int) -> str:
    payload = {
        "uid": user_id,
        "org_id": org_id,
        "role": role,
        "exp": int(time.time()) + ttl,
    }
    raw = _encode(payload)
    return f"{raw}.{_sign(secret, raw)}"


def verify_session_token(secret: str, token: str) -> dict[str, Any] | None:
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(secret, raw), sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def new_csrf_token() -> str:
    return secrets.token_hex(32)


def new_short_code() -> str:
    return secrets.token_hex(3).upper()


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()