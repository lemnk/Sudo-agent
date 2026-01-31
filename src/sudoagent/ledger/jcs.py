"""RFC 8785 JSON Canonicalization Scheme (JCS) helpers."""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 bytes per RFC 8785 for the given JSON-serializable value."""
    # rfc8785.dumps returns bytes already
    return rfc8785.dumps(value)


def sha256_hex(value: Any) -> str:
    """Return SHA-256 hex digest of the canonical bytes."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
