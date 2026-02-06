"""Shared ledger verification logic for JSONL and SQLite backends."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable, cast

from .errors import LedgerVerificationError
from .jcs import canonical_bytes, sha256_hex
from .signing import verify_entry_hash
from .types import JSONValue, VerifyKey
from .versioning import LEDGER_VERSION, SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    entry: dict[str, JSONValue]
    raw: str | None
    index: int
    row_entry_hash: str | None = None
    row_prev_hash: str | None = None


def validate_parsed_entries(
    entries: Iterable[ParsedEntry], *, public_key: VerifyKey | None = None
) -> None:
    """Validate a stream of already-parsed ledger entries."""
    expected_prev: str | None = None
    decision_hashes: dict[str, str] = {}

    for parsed in entries:
        idx = parsed.index
        entry = parsed.entry
        if not isinstance(entry, dict):
            raise LedgerVerificationError(f"entry {idx} is not an object")

        if parsed.raw is not None:
            if canonical_bytes(entry).decode("utf-8") != parsed.raw:
                raise LedgerVerificationError(f"entry {idx} is not canonical")

        if entry.get("schema_version") != SCHEMA_VERSION:
            raise LedgerVerificationError(f"schema_version mismatch at entry {idx}")
        if entry.get("ledger_version") != LEDGER_VERSION:
            raise LedgerVerificationError(f"ledger_version mismatch at entry {idx}")

        event = entry.get("event")
        if event not in ("decision", "outcome", "checkpoint"):
            raise LedgerVerificationError(f"event type invalid at entry {idx}")

        request_id = entry.get("request_id")
        if event != "checkpoint":
            if not isinstance(request_id, str):
                raise LedgerVerificationError(f"request_id missing at entry {idx}")
        else:
            if request_id is not None and not isinstance(request_id, str):
                raise LedgerVerificationError(f"request_id type invalid at entry {idx}")

        decision_block = entry.get("decision") if event != "checkpoint" else entry.get("decision", {})
        if event != "checkpoint":
            if not isinstance(decision_block, dict):
                raise LedgerVerificationError(f"decision block missing at entry {idx}")
            decision_hash_value = decision_block.get("decision_hash")
            if not isinstance(decision_hash_value, str):
                raise LedgerVerificationError(f"decision_hash missing at entry {idx}")
            request_id_str = cast(str, request_id)
            if event == "decision":
                if decision_hash_value in decision_hashes:
                    raise LedgerVerificationError(f"duplicate decision_hash at entry {idx}")
                decision_hashes[decision_hash_value] = request_id_str
            else:
                if decision_hash_value not in decision_hashes:
                    raise LedgerVerificationError(f"decision_hash unknown at entry {idx}")
                if decision_hashes[decision_hash_value] != request_id_str:
                    raise LedgerVerificationError(f"decision_hash mismatch at entry {idx}")

        prev_hash = entry.get("prev_entry_hash")
        if prev_hash is not None and not isinstance(prev_hash, str):
            raise LedgerVerificationError(f"prev_entry_hash type invalid at entry {idx}")
        if prev_hash != expected_prev:
            raise LedgerVerificationError(f"prev_entry_hash mismatch at entry {idx}")

        entry_with_null = copy.deepcopy(entry)
        entry_with_null["entry_hash"] = None
        entry_with_null.pop("entry_signature", None)
        calculated_hash = sha256_hex(entry_with_null)

        actual_hash = entry.get("entry_hash")
        if not isinstance(actual_hash, str):
            raise LedgerVerificationError(f"entry_hash missing at entry {idx}")
        if calculated_hash != actual_hash:
            raise LedgerVerificationError(f"entry_hash mismatch at entry {idx}")

        if parsed.row_entry_hash is not None:
            if not isinstance(parsed.row_entry_hash, str):
                raise LedgerVerificationError(f"entry_hash column invalid at entry {idx}")
            if parsed.row_entry_hash != actual_hash:
                raise LedgerVerificationError(f"entry_hash column mismatch at entry {idx}")
        if parsed.row_prev_hash is not None:
            if parsed.row_prev_hash != prev_hash:
                raise LedgerVerificationError(f"prev_entry_hash column mismatch at entry {idx}")

        if public_key is not None:
            signature = entry.get("entry_signature")
            if not isinstance(signature, str):
                raise LedgerVerificationError(f"entry_signature missing at entry {idx}")
            if not verify_entry_hash(public_key, actual_hash, signature):
                raise LedgerVerificationError(f"entry_signature invalid at entry {idx}")

        expected_prev = actual_hash
