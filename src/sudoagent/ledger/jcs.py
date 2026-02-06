"""Strict canonical JSON helpers for hashing and ledger integrity.

This module intentionally goes beyond RFC 8785 to match SudoAgent's v2 spec:
- NFC normalization for object keys and string values
- Duplicate key rejection after NFC normalization
- Fixed-point decimal encoding (no exponent)
- Rejection of binary floats (use Decimal for exact numbers)

See: docs/v2_spec.md
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from decimal import Decimal
from typing import Any

_JSON_SEPARATORS = (",", ":")


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented in SudoAgent's canonical JSON."""


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 bytes for the given JSON-serializable value."""
    return _canonical_json(value).encode("utf-8")


def _canonical_json(value: Any) -> str:
    # Primitives
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"

    # Numbers
    # NOTE: bool is a subclass of int, so check bool before int.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        raise CanonicalizationError("floats are rejected; use Decimal for exact numbers")
    if isinstance(value, Decimal):
        return _canonical_decimal(value)

    # Strings
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        return json.dumps(normalized, ensure_ascii=False, separators=_JSON_SEPARATORS)

    # Arrays
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(v) for v in value) + "]"

    # Objects
    if isinstance(value, dict):
        normalized_items: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalizationError("object keys must be strings")
            nk = unicodedata.normalize("NFC", k)
            if nk in normalized_items:
                raise CanonicalizationError(
                    f"duplicate key after NFC normalization: {nk!r}"
                )
            normalized_items[nk] = v

        parts: list[str] = []
        for k in sorted(normalized_items.keys()):
            parts.append(
                json.dumps(k, ensure_ascii=False, separators=_JSON_SEPARATORS)
                + ":"
                + _canonical_json(normalized_items[k])
            )
        return "{" + ",".join(parts) + "}"

    raise CanonicalizationError(f"type {type(value).__name__} is not JSON-serializable")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalizationError("NaN/Infinity are rejected")

    # JSON has no "-0"; normalize any signed zero to "0".
    if value == 0:
        return "0"

    # Fixed-point, no exponent.
    # format(..., "f") never uses exponent notation.
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s == "-0":
        return "0"
    return s


def sha256_hex(value: Any) -> str:
    """Return SHA-256 hex digest of the canonical bytes."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
