from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, TypeAlias

from .canonical import CanonicalizationError, canonical_dumps, canonical_sha256_hex
from .signing import sign_entry_hash, verify_entry_hash
from .versioning import LEDGER_VERSION, SCHEMA_VERSION

JSONPrimitive: TypeAlias = str | int | bool | None | Decimal
JSONNumber: TypeAlias = str | int | Decimal
JSONValue: TypeAlias = (
    JSONPrimitive | JSONNumber | dict[str, "JSONValue"] | list["JSONValue"]
)
SigningKey: TypeAlias = Any  # one-line justification: optional dependency at runtime
VerifyKey: TypeAlias = Any  # one-line justification: optional dependency at runtime


class LedgerError(RuntimeError):
    """Base class for ledger errors."""


class LedgerWriteError(LedgerError):
    """Raised when an append operation fails."""


class LedgerVerificationError(LedgerError):
    """Raised when ledger verification fails."""


@dataclass(frozen=True)
class SQLiteLedger:
    path: Path
    signing_key: SigningKey | None = None

    def append(self, entry: dict[str, JSONValue]) -> str:
        """Append an entry, computing chain hashes atomically."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(self.path) as conn:
                _ensure_schema(conn)
                conn.execute("BEGIN IMMEDIATE")
                prev_hash = _read_last_entry_hash(conn)
                prepared = _prepare_entry(entry, prev_hash)
                entry_hash = prepared.get("entry_hash")
                if not isinstance(entry_hash, str):
                    raise LedgerWriteError("entry_hash missing after preparation")
                if self.signing_key is not None:
                    prepared["entry_signature"] = sign_entry_hash(self.signing_key, entry_hash)
                entry_json = canonical_dumps(prepared)
                conn.execute(
                    "INSERT INTO ledger (entry_json, entry_hash, prev_entry_hash) VALUES (?, ?, ?)",
                    (entry_json, entry_hash, prev_hash),
                )
                conn.commit()
                return entry_hash
        except (sqlite3.Error, CanonicalizationError, LedgerError) as exc:
            raise LedgerWriteError(str(exc)) from exc

    def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify the entire ledger, failing on any tamper, gap, or reordering."""
        try:
            if not self.path.exists():
                return
            with _connect(self.path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(
                    "SELECT entry_json, entry_hash, prev_entry_hash FROM ledger ORDER BY id ASC"
                ).fetchall()
                _verify_rows(((row[0], row[1], row[2]) for row in rows), public_key=public_key)
        except (sqlite3.Error, CanonicalizationError, LedgerError, json.JSONDecodeError) as exc:
            raise LedgerVerificationError(str(exc)) from exc


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_json TEXT NOT NULL,
            entry_hash TEXT NOT NULL,
            prev_entry_hash TEXT
        )
        """
    )


def _prepare_entry(entry: dict[str, JSONValue], prev_hash: str | None) -> dict[str, JSONValue]:
    candidate = copy.deepcopy(entry)
    candidate["prev_entry_hash"] = prev_hash
    candidate["entry_hash"] = None
    entry_hash = canonical_sha256_hex(candidate)
    candidate["entry_hash"] = entry_hash
    return candidate


def _read_last_entry_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT entry_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    entry_hash = row[0]
    if not isinstance(entry_hash, str):
        raise LedgerVerificationError("entry_hash missing or invalid")
    return entry_hash


def _verify_rows(
    rows: Iterator[tuple[str, str | None, str | None]], *, public_key: VerifyKey | None = None
) -> None:
    expected_prev: str | None = None
    decision_hashes: dict[str, str] = {}
    line_number = 0
    for entry_json, row_entry_hash, row_prev_hash in rows:
        line_number += 1
        if not entry_json:
            raise LedgerVerificationError(f"empty entry_json at row {line_number}")
        if not isinstance(entry_json, str):
            raise LedgerVerificationError(f"entry_json invalid at row {line_number}")
        entry = json.loads(entry_json, parse_float=Decimal, parse_int=int)
        if not isinstance(entry, dict):
            raise LedgerVerificationError(f"row {line_number} is not an object")
        if canonical_dumps(entry) != entry_json:
            raise LedgerVerificationError(f"row {line_number} is not canonical")

        schema_version = entry.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise LedgerVerificationError(f"schema_version mismatch at row {line_number}")
        ledger_version = entry.get("ledger_version")
        if ledger_version != LEDGER_VERSION:
            raise LedgerVerificationError(f"ledger_version mismatch at row {line_number}")

        request_id = entry.get("request_id")
        if not isinstance(request_id, str):
            raise LedgerVerificationError(f"request_id missing at row {line_number}")
        event = entry.get("event")
        if event not in ("decision", "outcome"):
            raise LedgerVerificationError(f"event type invalid at row {line_number}")
        decision_block = entry.get("decision")
        if not isinstance(decision_block, dict):
            raise LedgerVerificationError(f"decision block missing at row {line_number}")
        decision_hash_value = decision_block.get("decision_hash")
        if event == "decision":
            if not isinstance(decision_hash_value, str):
                raise LedgerVerificationError(f"decision_hash missing at row {line_number}")
            if decision_hash_value in decision_hashes:
                raise LedgerVerificationError(f"duplicate decision_hash at row {line_number}")
            decision_hashes[decision_hash_value] = request_id
        else:
            if not isinstance(decision_hash_value, str):
                raise LedgerVerificationError(f"decision_hash missing at row {line_number}")
            if decision_hash_value not in decision_hashes:
                raise LedgerVerificationError(f"decision_hash unknown at row {line_number}")
            if decision_hashes[decision_hash_value] != request_id:
                raise LedgerVerificationError(f"decision_hash mismatch at row {line_number}")

        prev_hash = entry.get("prev_entry_hash")
        if prev_hash is not None and not isinstance(prev_hash, str):
            raise LedgerVerificationError(f"prev_entry_hash type invalid at row {line_number}")
        if prev_hash != expected_prev:
            raise LedgerVerificationError(f"prev_entry_hash mismatch at row {line_number}")

        entry_with_null = copy.deepcopy(entry)
        entry_with_null["entry_hash"] = None
        if "entry_signature" in entry_with_null:
            entry_with_null["entry_signature"] = None
        calculated_hash = canonical_sha256_hex(entry_with_null)

        actual_hash = entry.get("entry_hash")
        if not isinstance(actual_hash, str):
            raise LedgerVerificationError(f"entry_hash missing at row {line_number}")
        if calculated_hash != actual_hash:
            raise LedgerVerificationError(f"entry_hash mismatch at row {line_number}")

        if not isinstance(row_entry_hash, str):
            raise LedgerVerificationError(f"entry_hash column missing at row {line_number}")
        if row_prev_hash is not None and not isinstance(row_prev_hash, str):
            raise LedgerVerificationError(f"prev_entry_hash column type invalid at row {line_number}")
        if actual_hash != row_entry_hash:
            raise LedgerVerificationError(f"entry_hash column mismatch at row {line_number}")
        if prev_hash != row_prev_hash:
            raise LedgerVerificationError(f"prev_entry_hash column mismatch at row {line_number}")

        if public_key is not None:
            signature = entry.get("entry_signature")
            if not isinstance(signature, str):
                raise LedgerVerificationError(f"entry_signature missing at row {line_number}")
            if not verify_entry_hash(public_key, actual_hash, signature):
                raise LedgerVerificationError(f"entry_signature invalid at row {line_number}")

        expected_prev = actual_hash
