"""Shared approval store constants and validators."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_TTL_SECONDS: int = 300  # 5 minutes default
MAX_TTL_SECONDS: int = 3600  # 1 hour hard cap (no approval can be pending longer)
ALLOWED_STATES: set[str] = {"pending", "approved", "denied", "expired", "failed"}


def validate_nonempty_str(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def validate_state(state: str) -> None:
    if state not in ALLOWED_STATES:
        raise ValueError(f"state must be one of {sorted(ALLOWED_STATES)}")


def cap_expires_at(
    *,
    expires_at: datetime | None,
    now: datetime | None = None,
    default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    max_ttl_seconds: int = MAX_TTL_SECONDS,
) -> datetime:
    """Return a capped expiration time using defaults and hard limits."""
    now = now or datetime.now(timezone.utc)
    max_expiry = now + timedelta(seconds=max_ttl_seconds)

    if expires_at is None:
        expires_at = now + timedelta(seconds=default_ttl_seconds)
    elif expires_at > max_expiry:
        expires_at = max_expiry

    return expires_at
