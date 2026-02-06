"""Approval store protocol and SQLite implementation.

Design notes:
- TTL enforcement happens at the store level, not the engine
- MAX_TTL_SECONDS caps all expirations to prevent "pending forever" states
- expire_expired() is called before creating new pendings, not on timers
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from .approvals.common import (
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    cap_expires_at,
    validate_nonempty_str,
    validate_state,
)


class ApprovalStore(Protocol):
    """Protocol for durable approval state."""

    def create_pending(
        self, *, request_id: str, policy_hash: str, decision_hash: str, expires_at: datetime | None
    ) -> None:
        ...

    def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        ...


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


@dataclass
class SQLiteApprovalStore:
    """SQLite-backed approval store with TTL enforcement.

    Features:
    - All pending approvals have a TTL (capped at MAX_TTL_SECONDS)
    - expire_expired() marks stale pendings as 'expired'
    - fetch() retrieves approval state by request_id
    - WAL mode initialized once per database (thread-safe)
    """

    path: Path
    default_ttl_seconds: int = field(default=DEFAULT_TTL_SECONDS)
    max_ttl_seconds: int = field(default=MAX_TTL_SECONDS)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_wal_mode(self.path)  # Thread-safe, cached
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY,
                    policy_hash TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    approver_id TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            # Index for efficient expire_expired() queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approvals_pending_expires
                ON approvals (state, expires_at)
                WHERE state = 'pending'
                """
            )
            conn.commit()

    def create_pending(
        self, *, request_id: str, policy_hash: str, decision_hash: str, expires_at: datetime | None
    ) -> None:
        """Create a pending approval with TTL enforcement.

        If expires_at is None, uses default_ttl_seconds.
        All expirations are capped at max_ttl_seconds from now.
        """
        validate_nonempty_str("request_id", request_id)
        validate_nonempty_str("policy_hash", policy_hash)
        validate_nonempty_str("decision_hash", decision_hash)

        now = datetime.now(timezone.utc)
        expires_at = cap_expires_at(
            expires_at=expires_at,
            now=now,
            default_ttl_seconds=self.default_ttl_seconds,
            max_ttl_seconds=self.max_ttl_seconds,
        )

        with self._connect() as conn:
            # Expire any stale pending approvals before inserting new ones.
            self._expire_expired_with_conn(conn, now)

            # Idempotency: if already exists, only allow refreshing pending records.
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT request_id, policy_hash, decision_hash, state
                FROM approvals WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if existing is not None:
                if existing["state"] != "pending":
                    return
                if (
                    existing["policy_hash"] != policy_hash
                    or existing["decision_hash"] != decision_hash
                ):
                    raise ValueError("policy_hash/decision_hash mismatch for existing request_id")

            conn.execute(
                """
                INSERT INTO approvals
                (request_id, policy_hash, decision_hash, state, approver_id, expires_at, created_at, resolved_at)
                VALUES (?, ?, ?, 'pending', NULL, ?, ?, NULL)
                ON CONFLICT(request_id) DO UPDATE SET
                    policy_hash=excluded.policy_hash,
                    decision_hash=excluded.decision_hash,
                    expires_at=excluded.expires_at
                WHERE approvals.state = 'pending'
                """,
                (
                    request_id,
                    policy_hash,
                    decision_hash,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

    def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        """Resolve a pending approval (approved/denied/expired/failed)."""
        validate_nonempty_str("request_id", request_id)
        validate_state(state)
        resolved_at = resolved_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET state = ?, approver_id = ?, resolved_at = ?
                WHERE request_id = ? AND state = 'pending'
                """,
                (state, approver_id, resolved_at.isoformat(), request_id),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT state FROM approvals WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("request_id not found")
                existing_state = row[0]
                if existing_state == state:
                    conn.commit()
                    return
                raise ValueError(
                    f"invalid approval state transition: {existing_state} -> {state}"
                )
            conn.commit()

    def fetch(self, request_id: str) -> dict[str, Any] | None:
        """Fetch approval record by request_id. Returns None if not found."""
        validate_nonempty_str("request_id", request_id)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT request_id, policy_hash, decision_hash, state,
                       approver_id, expires_at, created_at, resolved_at
                FROM approvals
                WHERE request_id = ?
                """,
                (request_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            record = dict(row)
            # Auto-expire if stale and still pending.
            if record.get("state") == "pending" and record.get("expires_at"):
                expires_at = datetime.fromisoformat(record["expires_at"])
                if expires_at < datetime.now(timezone.utc):
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        UPDATE approvals
                        SET state = 'expired', resolved_at = ?
                        WHERE request_id = ?
                        """,
                        (now, request_id),
                    )
                    conn.commit()
                    record["state"] = "expired"
                    record["resolved_at"] = now
            return record

    def expire_expired(self) -> int:
        """Mark all expired pending approvals as 'expired'. Returns count."""
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            return self._expire_expired_with_conn(conn, now)

    def _expire_expired_with_conn(self, conn: sqlite3.Connection, now: datetime) -> int:
        now_iso = now.isoformat()
        cursor = conn.execute(
            """
            UPDATE approvals
            SET state = 'expired', resolved_at = ?
            WHERE state = 'pending' AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (now_iso, now_iso),
        )
        conn.commit()
        return cursor.rowcount

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Get connection. WAL already initialized in __post_init__. Always closes."""
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

