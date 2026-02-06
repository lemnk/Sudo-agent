from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Iterator, cast

from .jcs import canonical_bytes
from .signing import sign_entry_hash
from .errors import (
    LedgerError,
    LedgerWriteError,
    LedgerVerificationError,
    sanitize_exception,
)
from .types import JSONValue, SigningKey, VerifyKey
from .common import prepare_entry
from .validation import ParsedEntry, validate_parsed_entries
from sudoagent.types import LedgerEntry


@dataclass(frozen=True)
class SQLiteLedger:
    path: Path
    signing_key: SigningKey | None = None

    def append(self, entry: LedgerEntry) -> str:
        """Append an entry, computing chain hashes atomically."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(self.path) as conn:
                _ensure_schema(conn)
                conn.execute("BEGIN IMMEDIATE")
                prev_hash = _read_last_entry_hash(conn)
                prepared = prepare_entry(cast(dict[str, JSONValue], entry), prev_hash)
                entry_hash = prepared.get("entry_hash")
                if not isinstance(entry_hash, str):
                    raise LedgerWriteError("entry_hash missing after preparation")
                if self.signing_key is not None:
                    prepared["entry_signature"] = sign_entry_hash(self.signing_key, entry_hash)
                entry_json = canonical_bytes(prepared).decode("utf-8")
                conn.execute(
                    "INSERT INTO ledger (entry_json, entry_hash, prev_entry_hash) VALUES (?, ?, ?)",
                    (entry_json, entry_hash, prev_hash),
                )
                conn.commit()
                return entry_hash
        except (sqlite3.Error, LedgerError) as exc:
            raise LedgerWriteError(sanitize_exception(exc)) from exc

    def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify the entire ledger, failing on any tamper, gap, or reordering."""
        try:
            if not self.path.exists():
                return
            with _connect(self.path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(
                    "SELECT entry_json, entry_hash, prev_entry_hash FROM ledger ORDER BY id ASC"
                )
                _verify_rows(rows, public_key=public_key)
        except (sqlite3.Error, LedgerError, json.JSONDecodeError) as exc:
            raise LedgerVerificationError(sanitize_exception(exc)) from exc


# Thread-safe WAL initialization cache (matches approvals_store.py pattern)
_WAL_INITIALIZED: dict[Path, bool] = {}
_WAL_LOCK = threading.Lock()


def _ensure_wal_mode(path: Path) -> None:
    """Ensure WAL mode is set exactly once per database file. Thread-safe."""
    with _WAL_LOCK:
        if path in _WAL_INITIALIZED:
            return
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            _WAL_INITIALIZED[path] = True
        finally:
            conn.close()


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Get connection. WAL mode cached per database file. Always closes."""
    _ensure_wal_mode(path)
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


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


def _read_last_entry_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT entry_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    entry_hash = row[0]
    if not isinstance(entry_hash, str):
        raise LedgerVerificationError("entry_hash missing or invalid")
    return entry_hash


def _verify_rows(
    rows: Iterable[tuple[str, str | None, str | None]], *, public_key: VerifyKey | None = None
) -> None:
    def _iter_parsed() -> Iterator[ParsedEntry]:
        row_number = 0
        for entry_json, row_entry_hash, row_prev_hash in rows:
            row_number += 1
            if not entry_json:
                raise LedgerVerificationError(f"empty entry_json at row {row_number}")
            if not isinstance(entry_json, str):
                raise LedgerVerificationError(f"entry_json invalid at row {row_number}")
            entry = json.loads(entry_json, parse_float=Decimal, parse_int=int)
            if not isinstance(entry, dict):
                raise LedgerVerificationError(f"row {row_number} is not an object")
            if canonical_bytes(entry).decode("utf-8") != entry_json:
                raise LedgerVerificationError(f"row {row_number} is not canonical")
            yield ParsedEntry(
                entry=entry,
                raw=entry_json,
                index=row_number,
                row_entry_hash=row_entry_hash,
                row_prev_hash=row_prev_hash,
            )

    validate_parsed_entries(_iter_parsed(), public_key=public_key)
