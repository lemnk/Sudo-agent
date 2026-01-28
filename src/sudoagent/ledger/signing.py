"""Ed25519 signing utilities for ledger entries."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

# Runtime availability flag and module reference
CRYPTO_AVAILABLE = False
_serialization: Any | None = None
_ed25519: Any | None = None

try:
    from cryptography.hazmat.primitives import serialization as _serialization  # type: ignore[import-not-found]
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519  # type: ignore[import-not-found]
    CRYPTO_AVAILABLE = True
except ModuleNotFoundError:
    _serialization = None
    _ed25519 = None


def _require_crypto() -> None:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography is required for Ed25519 signing")


def generate_keypair() -> tuple[bytes, bytes]:
    _require_crypto()
    private_key = _ed25519.Ed25519PrivateKey.generate()  # type: ignore[union-attr]
    private_bytes = private_key.private_bytes(
        encoding=_serialization.Encoding.PEM,  # type: ignore[union-attr]
        format=_serialization.PrivateFormat.PKCS8,  # type: ignore[union-attr]
        encryption_algorithm=_serialization.NoEncryption(),  # type: ignore[union-attr]
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=_serialization.Encoding.PEM,  # type: ignore[union-attr]
        format=_serialization.PublicFormat.SubjectPublicKeyInfo,  # type: ignore[union-attr]
    )
    return private_bytes, public_bytes


def load_private_key(data: bytes) -> "Ed25519PrivateKey":
    _require_crypto()
    key = _serialization.load_pem_private_key(data, password=None)  # type: ignore[union-attr]
    if not isinstance(key, _ed25519.Ed25519PrivateKey):
        raise ValueError("unsupported private key type")
    return key  # type: ignore[return-value]


def load_public_key(data: bytes) -> "Ed25519PublicKey":
    _require_crypto()
    key = _serialization.load_pem_public_key(data)  # type: ignore[union-attr]
    if not isinstance(key, _ed25519.Ed25519PublicKey):
        raise ValueError("unsupported public key type")
    return key  # type: ignore[return-value]


def sign_entry_hash(private_key: "Ed25519PrivateKey", entry_hash: str) -> str:
    _require_crypto()
    signature = private_key.sign(entry_hash.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def verify_entry_hash(public_key: "Ed25519PublicKey", entry_hash: str, signature_b64: str) -> bool:
    _require_crypto()
    try:
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, entry_hash.encode("utf-8"))
        return True
    except Exception:
        return False
