"""Shared ledger helpers used across backends."""

from __future__ import annotations

import copy

from .jcs import sha256_hex
from .types import JSONValue


def prepare_entry(entry: dict[str, JSONValue], prev_hash: str | None) -> dict[str, JSONValue]:
    """Return a new entry with chain hashes computed.

    This is the single source of truth for ledger chain hashing.
    """
    candidate = copy.deepcopy(entry)
    candidate["prev_entry_hash"] = prev_hash
    candidate["entry_hash"] = None
    entry_hash = sha256_hex(candidate)
    candidate["entry_hash"] = entry_hash
    return candidate
