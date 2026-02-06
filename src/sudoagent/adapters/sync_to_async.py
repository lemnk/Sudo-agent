"""Sync-to-async adapters for SudoAgent protocols.

These adapters wrap synchronous implementations to conform to async protocols.
Use asyncio.to_thread() for blocking I/O operations.

Design notes:
- Adapters are explicit: users construct them, not the engine
- Each adapter wraps exactly one sync implementation
- to_thread() is used only for I/O-bound operations
- CPU-bound operations (policy eval, hashing) stay on the event loop
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ..policies import PolicyResult
    from ..types import AuditEntry, Context, LedgerEntry

# Runtime type aliases (avoid circular imports)
VerifyKey = Any  # optional nacl dependency



@dataclass(frozen=True, slots=True)
class SyncLedgerAdapter:
    """Wraps a sync Ledger to provide AsyncLedger interface.

    Usage:
        sync_ledger = JSONLLedger(path)
        async_ledger = SyncLedgerAdapter(sync_ledger)
        engine = AsyncSudoEngine(ledger=async_ledger, agent_id="demo:sync-to-async", ...)
    """

    _ledger: Any  # Ledger protocol

    async def append(self, entry: LedgerEntry) -> str:
        """Append entry in thread pool (file I/O is blocking)."""
        return await asyncio.to_thread(self._ledger.append, entry)

    async def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify ledger in thread pool (file I/O is blocking)."""
        await asyncio.to_thread(self._ledger.verify, public_key=public_key)


@dataclass(frozen=True, slots=True)
class SyncAuditLoggerAdapter:
    """Wraps a sync AuditLogger to provide AsyncAuditLogger interface.

    Usage:
        sync_logger = JsonlAuditLogger()
        async_logger = SyncAuditLoggerAdapter(sync_logger)
    """

    _logger: Any  # AuditLogger protocol

    async def log(self, entry: AuditEntry) -> None:
        """Log entry in thread pool (file I/O is blocking)."""
        await asyncio.to_thread(self._logger.log, entry)


@dataclass(frozen=True, slots=True)
class SyncApproverAdapter:
    """Wraps a sync Approver to provide AsyncApprover interface.

    WARNING: This holds a thread during approval wait.
    Use only for dev/testing. Production SaaS should use native async approvers.

    Usage:
        sync_approver = InteractiveApprover()
        async_approver = SyncApproverAdapter(sync_approver)
    """

    _approver: Any  # Approver protocol

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        """Approve in thread pool. WARNING: Holds thread during wait."""
        return await asyncio.to_thread(
            self._approver.approve, ctx, result, request_id
        )


@dataclass(frozen=True, slots=True)
class SyncApprovalStoreAdapter:
    """Wraps a sync ApprovalStore to provide AsyncApprovalStore interface.

    Usage:
        sync_store = SQLiteApprovalStore(path)
        async_store = SyncApprovalStoreAdapter(sync_store)
    """

    _store: Any  # ApprovalStore protocol

    async def create_pending(
        self,
        *,
        request_id: str,
        policy_hash: str,
        decision_hash: str,
        expires_at: datetime | None,
    ) -> None:
        """Create pending record in thread pool (SQLite I/O is blocking)."""
        await asyncio.to_thread(
            self._store.create_pending,
            request_id=request_id,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            expires_at=expires_at,
        )

    async def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        """Resolve approval in thread pool."""
        await asyncio.to_thread(
            self._store.resolve,
            request_id=request_id,
            state=state,
            approver_id=approver_id,
            resolved_at=resolved_at,
        )

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        """Fetch approval record in thread pool."""
        # Check if sync store has fetch method
        if hasattr(self._store, "fetch"):
            return await asyncio.to_thread(self._store.fetch, request_id)
        return None

    async def expire_expired(self) -> int:
        """Expire stale approvals in thread pool."""
        if hasattr(self._store, "expire_expired"):
            return await asyncio.to_thread(self._store.expire_expired)
        return 0


@dataclass(frozen=True, slots=True)
class SyncBudgetManagerAdapter:
    """Wraps a sync BudgetManager to provide AsyncBudgetManager interface.

    Usage:
        sync_budget = BudgetManager(agent_limit=100, tool_limit=10, window_seconds=3600)
        async_budget = SyncBudgetManagerAdapter(sync_budget)
    """

    _manager: Any  # BudgetManager

    async def check(
        self, request_id: str, agent: str, tool: str, cost: int
    ) -> Any:
        """Check budget. In-memory managers are fast; thread for SQLite-backed."""
        # In-memory budget check is CPU-bound and fast, no thread needed
        # But SQLite-backed budgets need thread. Check for connection attribute.
        if hasattr(self._manager, "_connect"):
            return await asyncio.to_thread(
                self._manager.check, request_id, agent, tool, cost
            )
        return self._manager.check(request_id, agent, tool, cost)

    async def commit(self, request_id: str) -> None:
        """Commit budget. In-memory is fast; thread for SQLite-backed."""
        if hasattr(self._manager, "_connect"):
            await asyncio.to_thread(self._manager.commit, request_id)
        else:
            self._manager.commit(request_id)
