from __future__ import annotations

from typing import Any

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


def redact_value(key: str | None, value: Any) -> str:
    if isinstance(value, str):
        if value == "[redacted]":
            return value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return value
    if key is not None and is_sensitive_key(key):
        return "[redacted]"
    if is_sensitive_value(value):
        return "[redacted]"
    return safe_repr(value)


def redact_args(args: tuple[Any, ...]) -> list[str]:
    return [redact_value(None, arg) for arg in args]


def redact_kwargs(kwargs: dict[str, Any]) -> dict[str, str]:
    return {k: redact_value(k, v) for k, v in kwargs.items()}
