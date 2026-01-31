"""Approval store protocol and SQLite implementation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


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


@dataclass(frozen=True)
class SQLiteApprovalStore:
    """SQLite-backed approval store with simple pending/resolution tracking."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            conn.commit()

    def create_pending(
        self, *, request_id: str, policy_hash: str, decision_hash: str, expires_at: datetime | None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO approvals
                (request_id, policy_hash, decision_hash, state, approver_id, expires_at, created_at, resolved_at)
                VALUES (?, ?, ?, 'pending', NULL, ?, ?, NULL)
                """,
                (
                    request_id,
                    policy_hash,
                    decision_hash,
                    expires_at.isoformat() if expires_at else None,
                    now,
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
        resolved_at = resolved_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET state = ?, approver_id = ?, resolved_at = ?
                WHERE request_id = ?
                """,
                (state, approver_id, resolved_at.isoformat(), request_id),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn
