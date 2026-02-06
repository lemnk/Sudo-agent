"""Async approval store implementations.

Native async stores that don't require thread pool wrapping.
For sync SQLiteApprovalStore, use SyncApprovalStoreAdapter instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    cap_expires_at,
    validate_nonempty_str,
    validate_state,
)

# Note: aiosqlite is optional dependency for true async SQLite
# If not available, use SyncApprovalStoreAdapter + SQLiteApprovalStore instead
try:
    import aiosqlite  # type: ignore[import-not-found]
    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False
    aiosqlite = None  # type: ignore


@dataclass
class AsyncSQLiteApprovalStore:
    """Native async SQLite approval store using aiosqlite.

    Features:
    - True async I/O (no thread pool, no thread holding)
    - WAL mode for concurrent access
    - TTL enforcement at store level
    - State transitions: pending -> approved/denied/expired/failed

    Requires: pip install aiosqlite

    Usage:
        store = AsyncSQLiteApprovalStore(Path("approvals.db"))
        await store.initialize()  # Create tables
        approver = PollingAsyncApprover(store)
        engine = AsyncSudoEngine(
            approval_store=store,
            approver=approver,
            agent_id="demo:async-store",
            ...
        )
    """

    path: Path
    default_ttl_seconds: int = field(default=DEFAULT_TTL_SECONDS)
    max_ttl_seconds: int = field(default=MAX_TTL_SECONDS)
    _initialized: bool = field(default=False, repr=False)
    _init_lock: asyncio.Lock | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not AIOSQLITE_AVAILABLE:
            raise ImportError(
                "aiosqlite is required for AsyncSQLiteApprovalStore. "
                "Install with: pip install aiosqlite"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create tables if they don't exist. Call once at startup."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=FULL")
            await db.execute(
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
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approvals_pending_expires
                ON approvals (state, expires_at)
                WHERE state = 'pending'
                """
            )
            await db.commit()
        self._initialized = True

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            await self.initialize()

    async def create_pending(
        self,
        *,
        request_id: str,
        policy_hash: str,
        decision_hash: str,
        expires_at: datetime | None,
    ) -> None:
        """Create a pending approval with TTL enforcement."""
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

        await self._ensure_initialized()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO approvals
                (request_id, policy_hash, decision_hash, state, approver_id, expires_at, created_at, resolved_at)
                VALUES (?, ?, ?, 'pending', NULL, ?, ?, NULL)
                ON CONFLICT(request_id) DO UPDATE SET
                    policy_hash=excluded.policy_hash,
                    decision_hash=excluded.decision_hash,
                    expires_at=excluded.expires_at
                WHERE approvals.state = 'pending'
                  AND approvals.policy_hash = excluded.policy_hash
                  AND approvals.decision_hash = excluded.decision_hash
                """,
                (
                    request_id,
                    policy_hash,
                    decision_hash,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            async with db.execute(
                """
                SELECT request_id, policy_hash, decision_hash, state
                FROM approvals WHERE request_id = ?
                """,
                (request_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("failed to create pending approval")
                if row["state"] != "pending":
                    return
                if row["policy_hash"] != policy_hash or row["decision_hash"] != decision_hash:
                    raise ValueError("policy_hash/decision_hash mismatch for existing request_id")
            await db.commit()

    async def resolve(
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
        await self._ensure_initialized()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE approvals
                SET state = ?, approver_id = ?, resolved_at = ?
                WHERE request_id = ?
                """,
                (state, approver_id, resolved_at.isoformat(), request_id),
            )
            await db.commit()

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        """Fetch approval record by request_id. Returns None if not found."""
        validate_nonempty_str("request_id", request_id)
        await self._ensure_initialized()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT request_id, policy_hash, decision_hash, state,
                       approver_id, expires_at, created_at, resolved_at
                FROM approvals
                WHERE request_id = ?
                """,
                (request_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                record = dict(row)
                if record.get("state") == "pending" and record.get("expires_at"):
                    expires_at = datetime.fromisoformat(record["expires_at"])
                    if expires_at < datetime.now(timezone.utc):
                        now = datetime.now(timezone.utc).isoformat()
                        await db.execute(
                            """
                            UPDATE approvals
                            SET state = 'expired', resolved_at = ?
                            WHERE request_id = ?
                            """,
                            (now, request_id),
                        )
                        await db.commit()
                        record["state"] = "expired"
                        record["resolved_at"] = now
                return record

    async def expire_expired(self) -> int:
        """Mark all expired pending approvals as 'expired'. Returns count."""
        await self._ensure_initialized()
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                UPDATE approvals
                SET state = 'expired', resolved_at = ?
                WHERE state = 'pending' AND expires_at IS NOT NULL AND expires_at < ?
                """,
                (now, now),
            )
            await db.commit()
            return cursor.rowcount
