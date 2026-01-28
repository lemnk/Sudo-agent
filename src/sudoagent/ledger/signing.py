"""Ed25519 signing utilities for ledger entries."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Optional dependency. Keep the import in TYPE_CHECKING for better editor
    # support when installed, but don't require it for type-checking the repo.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

_ed25519: Any | None = None
_serialization: Any | None = None

try:
    from cryptography.hazmat.primitives import serialization as _serialization_mod  # type: ignore[import-not-found]
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519_mod  # type: ignore[import-not-found]

    _serialization = _serialization_mod
    _ed25519 = _ed25519_mod
except ModuleNotFoundError:
    pass

CRYPTO_AVAILABLE = _serialization is not None and _ed25519 is not None


def _crypto_modules() -> tuple[Any, Any]:
    """Return runtime crypto modules or raise with a friendly message."""
    if _serialization is None or _ed25519 is None:
        raise RuntimeError('cryptography is required for Ed25519 signing (install "sudoagent[crypto]")')
    return _serialization, _ed25519


def generate_keypair() -> tuple[bytes, bytes]:
    serialization, ed25519 = _crypto_modules()
    private_key = ed25519.Ed25519PrivateKey.generate()
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


def load_private_key(data: bytes) -> "Ed25519PrivateKey":
    serialization, ed25519 = _crypto_modules()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError("unsupported private key type")
    return key  # type: ignore[return-value]


def load_public_key(data: bytes) -> "Ed25519PublicKey":
    serialization, ed25519 = _crypto_modules()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError("unsupported public key type")
    return key  # type: ignore[return-value]


def sign_entry_hash(private_key: "Ed25519PrivateKey", entry_hash: str) -> str:
    _crypto_modules()
    signature = private_key.sign(entry_hash.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def verify_entry_hash(public_key: "Ed25519PublicKey", entry_hash: str, signature_b64: str) -> bool:
    _crypto_modules()
    try:
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, entry_hash.encode("utf-8"))
        return True
    except Exception:
        return False
