from __future__ import annotations

from decimal import Decimal
from typing import Any

from .ledger.types import JSONValue

_SENSITIVE_KEY_TERMS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "bearer",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "credential",
    "session",
    "jwt",
    "auth",
)

_SENSITIVE_VALUE_PREFIXES = (
    "sk-",
    "rk-",
    "ghp_",
    "github_pat_",
    "xoxb-",
    "xoxa-",
)


def safe_repr(obj: Any, max_length: int = 200) -> str:
    try:
        r = repr(obj)
        if len(r) > max_length:
            return r[:max_length] + "..."
        return r
    except Exception:
        return "<repr failed>"


def is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(term in key_lower for term in _SENSITIVE_KEY_TERMS)


def is_sensitive_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if s.count(".") == 2 and len(s) >= 24:
        return True
    if s.lower().startswith("bearer "):
        return True
    for prefix in _SENSITIVE_VALUE_PREFIXES:
        if s.startswith(prefix):
            return True
    if "-----BEGIN" in s:
        return True
    return False


def _non_json_placeholder(value: Any) -> str:
    """Return a deterministic, non-leaky placeholder for non-JSON values."""
    t = type(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes:{len(value)}>"
    return f"<{t.__name__}>"


def redact_value(key: str | None, value: Any) -> JSONValue:
    """Redact a value while preserving safe primitive types.

    This function is used before policy evaluation and hashing. It must be:
    - deterministic
    - JSON-serializable (via sudoagent's canonical JSON rules)
    - type-preserving for safe primitives so policies can do numeric comparisons
    """
    # Idempotence for already-redacted markers.
    if value == "[redacted]":
        return "[redacted]"

    if key is not None and is_sensitive_key(key):
        return "[redacted]"

    # Strings: keep safe strings as-is; redact secret-like strings by value.
    if isinstance(value, str):
        if is_sensitive_value(value):
            return "[redacted]"
        return value

    # Primitives
    if value is None:
        return None
    if value is True:
        return True
    if value is False:
        return False
    # NOTE: bool is a subclass of int, so check bool before int.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise ValueError("floats are rejected; use Decimal for exact numbers")
    if isinstance(value, Decimal):
        return value

    # Arrays
    if isinstance(value, (list, tuple)):
        return [redact_value(None, v) for v in value]

    # Objects
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value.keys()):
            return {k: redact_value(k, v) for k, v in value.items()}
        return _non_json_placeholder(value)

    return _non_json_placeholder(value)


def redact_args(args: tuple[Any, ...]) -> list[JSONValue]:
    return [redact_value(None, arg) for arg in args]


def redact_kwargs(kwargs: dict[str, Any]) -> dict[str, JSONValue]:
    return {k: redact_value(k, v) for k, v in kwargs.items()}
