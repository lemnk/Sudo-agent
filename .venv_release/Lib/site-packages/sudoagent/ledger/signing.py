from __future__ import annotations

import base64
from typing import Any

try:
    from cryptography.hazmat.primitives import serialization  # type: ignore[import-not-found]
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    CRYPTO_AVAILABLE = True
except ModuleNotFoundError:
    CRYPTO_AVAILABLE = False
    Ed25519PrivateKey = Any  # one-line justification: optional dependency at runtime
    Ed25519PublicKey = Any  # one-line justification: optional dependency at runtime
    serialization = None


def _require_crypto() -> None:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography is required for Ed25519 signing")


def generate_keypair() -> tuple[bytes, bytes]:
    _require_crypto()
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_bytes, public_bytes


def load_private_key(data: bytes) -> Ed25519PrivateKey:
    _require_crypto()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("unsupported private key type")
    return key


def load_public_key(data: bytes) -> Ed25519PublicKey:
    _require_crypto()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("unsupported public key type")
    return key


def sign_entry_hash(private_key: Ed25519PrivateKey, entry_hash: str) -> str:
    _require_crypto()
    signature = private_key.sign(entry_hash.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def verify_entry_hash(public_key: Ed25519PublicKey, entry_hash: str, signature_b64: str) -> bool:
    _require_crypto()
    try:
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, entry_hash.encode("utf-8"))
        return True
    except Exception:
        return False
