"""Canonical JSON encoding and hashing for ledger entries."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class CanonicalizationError(ValueError):
    """Raised when data cannot be canonicalized."""


@dataclass(frozen=True)
class _Number:
    text: str


def canonical_dumps(value: object) -> str:
    """Return canonical JSON string for already-redacted data."""
    canonical_value = _canonicalize(value)
    return _render(canonical_value)


def canonical_sha256_hex(value: object) -> str:
    """Return SHA-256 hex digest of canonical JSON for already-redacted data."""
    payload = canonical_dumps(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonicalize(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _Number(str(value))
    if isinstance(value, float):
        raise CanonicalizationError("float values are not permitted; use Decimal for exact numbers")
    if isinstance(value, Decimal):
        return _Number(_format_decimal(value))
    if isinstance(value, str):
        return _canonicalize_string(value)
    if isinstance(value, datetime):
        return _canonicalize_datetime(value)
    if isinstance(value, Mapping):
        return _canonicalize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonicalize(item) for item in value]
    raise CanonicalizationError(f"Unsupported type for canonicalization: {type(value)!r}")


def _canonicalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _canonicalize_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalizationError("datetime values must be timezone-aware and UTC")
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonicalize_mapping(mapping: Mapping[str, Any]) -> dict[str, object]:
    normalized_items: list[tuple[str, object]] = []
    for raw_key, raw_value in mapping.items():
        if not isinstance(raw_key, str):
            raise CanonicalizationError("object keys must be strings")
        normalized_key = _canonicalize_string(raw_key)
        normalized_value = _canonicalize(raw_value)
        normalized_items.append((normalized_key, normalized_value))

    normalized_items.sort(key=lambda item: item[0])

    result: dict[str, object] = {}
    for key, value in normalized_items:
        if key in result:
            raise CanonicalizationError("duplicate key after normalization")
        result[key] = value
    return result


def _format_decimal(value: Decimal) -> str:
    if value.is_nan() or value.is_infinite():
        raise CanonicalizationError("NaN or infinite numbers are not permitted")
    try:
        normalized = value.normalize()
    except InvalidOperation as exc:
        raise CanonicalizationError("Invalid decimal value") from exc

    if normalized == 0:
        return "0"

    text = format(normalized, "f")

    if text.startswith("+"):
        text = text[1:]
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "+0"):
        text = "0"
    return text


def _render(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, _Number):
        return value.text
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_render(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            key_text = json.dumps(key, ensure_ascii=False)
            parts.append(f"{key_text}:{_render(item)}")
        return "{" + ",".join(parts) + "}"
    raise CanonicalizationError(f"Unsupported canonical form: {type(value)!r}")
