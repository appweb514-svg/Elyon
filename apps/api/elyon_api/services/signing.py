from __future__ import annotations

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from elyon_api.config import Settings


def load_or_create_signing_key(settings: Settings) -> Ed25519PrivateKey:
    key_file = settings.signing_key_file
    if key_file.exists():
        return serialization.load_pem_private_key(key_file.read_bytes(), password=None)  # type: ignore[return-value]
    private_key = Ed25519PrivateKey.generate()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return private_key


def public_key_pem(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def sign_json(payload: dict, private_key: Ed25519PrivateKey) -> tuple[str, str]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    signature = private_key.sign(raw)
    return raw.decode(), base64.b64encode(signature).decode()


def verify_signature(payload_json: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(
            base64.b64decode(signature_b64), payload_json.encode()
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False