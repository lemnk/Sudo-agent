"""Async protocol definitions for SudoAgent.

These protocols define the async interface contract for all I/O boundaries.
Use explicit adapters (see adapters/sync_to_async.py) to wrap sync implementations.

Design notes:
- All I/O operations are async to enable event-loop-native waits
- @runtime_checkable is for debugging/logging convenience only, not dispatch
- Adapters wrap sync implementations with asyncio.to_thread for blocking I/O
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

from .policies import PolicyResult
from .types import AuditEntry, Context, LedgerEntry

# Type alias for optional dependency at runtime (nacl signing keys)
VerifyKey = Any


@runtime_checkable
class AsyncLedger(Protocol):
    """Async ledger for tamper-evident evidence storage.

    Implementations must:
    - Append entries atomically with chain hashing
    - Support full-ledger verification
    - Handle concurrent appends safely (file locking, WAL, etc.)
    """

    async def append(self, entry: LedgerEntry) -> str:
        """Append entry and return its chain hash. Fail-closed on error."""
        ...

    async def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify ledger integrity and optionally signatures."""
        ...


@runtime_checkable
class AsyncAuditLogger(Protocol):
    """Async audit logger for operational records.

    Unlike the ledger, audit logs are not tamper-evident.
    Used for debugging and operational visibility.
    """

    async def log(self, entry: AuditEntry) -> None:
        """Write an audit entry."""
        ...


@runtime_checkable
class AsyncApprover(Protocol):
    """Async approver for human-in-the-loop authorization.

    This is the critical interface for SaaS: approval waits must not hold threads.
    Implementations should:
    - Return quickly if approval is cached/pre-authorized
    - Await external systems (Slack, UI) without blocking threads
    - Support timeout/cancellation via asyncio
    """

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        """Request approval. Returns True/False or mapping with binding details."""
        ...


@runtime_checkable
class AsyncApprovalStore(Protocol):
    """Async durable approval state store.

    Critical for SaaS reliability:
    - Pending approvals survive process restarts
    - TTL enforcement prevents "pending forever" states
    - State transitions are atomic and durable
    """

    async def create_pending(
        self,
        *,
        request_id: str,
        policy_hash: str,
        decision_hash: str,
        expires_at: datetime | None,
    ) -> None:
        """Create a pending approval record. Must be durable before returning."""
        ...

    async def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        """Resolve a pending approval (approved/denied/expired/failed)."""
        ...

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        """Fetch approval record by request_id. Returns None if not found."""
        ...

    async def expire_expired(self) -> int:
        """Mark all expired pending approvals as 'expired'. Returns count."""
        ...


@runtime_checkable
class AsyncBudgetManager(Protocol):
    """Async budget manager for rate limiting.

    Semantics:
    - check() reserves budget, idempotent by request_id
    - commit() finalizes the reservation
    - Failures are fail-closed (deny execution)
    """

    async def check(
        self, request_id: str, agent: str, tool: str, cost: int
    ) -> Any:
        """Check if budget allows this cost. Raises BudgetExceeded if not."""
        ...

    async def commit(self, request_id: str) -> None:
        """Commit a previously checked budget reservation."""
        ...
