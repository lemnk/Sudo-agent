"""Native async approvers for SudoAgent.

These approvers don't hold threads during approval waits. They poll a durable
approval store and yield to the event loop between polls.

Design notes:
- PollingAsyncApprover: Polls store at configurable interval, no thread holding
- WebhookAsyncApprover: Awaits external webhook callback (future)
- For dev/testing: Use SyncApproverAdapter (holds thread, not for production SaaS)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from ..policies import PolicyResult
from ..protocols import AsyncApprovalStore
from ..types import Context

_logger = logging.getLogger(__name__)


class ApprovalTimeoutError(Exception):
    """Raised when approval wait exceeds timeout."""
    pass


@dataclass
class PollingAsyncApprover:
    """Async approver that polls a durable store. No thread holding.

    This is the SaaS-grade approver. When awaiting approval:
    - Persists pending state to store
    - Yields to event loop between polls (other requests keep flowing)
    - Returns when store shows approved/denied/expired
    - Raises ApprovalTimeoutError if local timeout exceeded

    Usage:
        store = AsyncSQLiteApprovalStore(path)  # or any AsyncApprovalStore
        approver = PollingAsyncApprover(store, poll_interval=2.0, timeout=300.0)
        engine = AsyncSudoEngine(approver=approver, agent_id="demo:async-approver", ...)

    Thread behavior:
        - Zero threads held during approval wait
        - ~1000 concurrent approvals = ~0 held threads (event loop handles all)
    """

    store: AsyncApprovalStore
    poll_interval: float = field(default=2.0)  # seconds between polls
    timeout: float = field(default=300.0)  # max wait time (5 min default)
    _notify_callback: Any = field(default=None, repr=False)  # optional notification

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        """Poll store until approval resolved. No thread holding.

        Args:
            ctx: Execution context
            result: Policy result requiring approval
            request_id: Unique request identifier (already persisted as pending)

        Returns:
            True if approved, False if denied
            Or a mapping with binding details

        Raises:
            ApprovalTimeoutError: If local timeout exceeded
        """
        start = datetime.now(timezone.utc)
        deadline = start + timedelta(seconds=self.timeout)

        # Optional: send notification to approver (Slack, email, etc.)
        if self._notify_callback is not None:
            try:
                await self._maybe_notify(ctx, result, request_id)
            except Exception as exc:
                _logger.debug("Notification failed for request %s: %s", request_id, exc)

        while datetime.now(timezone.utc) < deadline:
            record = await self.store.fetch(request_id)

            if record is None:
                # Record doesn't exist - treat as denied
                return False

            state = record.get("state")
            if state == "approved":
                return {
                    "approved": True,
                    "approver_id": record.get("approver_id"),
                    "binding": {
                        "request_id": request_id,
                        "policy_hash": record.get("policy_hash"),
                        "decision_hash": record.get("decision_hash"),
                    },
                }
            elif state == "denied":
                return False
            elif state == "expired":
                return False
            elif state == "pending":
                # Still pending - yield to event loop, then poll again
                await asyncio.sleep(self.poll_interval)
            else:
                # Unknown state - treat as denied
                return False

        # Timeout exceeded
        raise ApprovalTimeoutError(
            f"Approval wait exceeded {self.timeout}s for request {request_id}"
        )

    async def _maybe_notify(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> None:
        """Send notification if callback configured."""
        if self._notify_callback is not None:
            if asyncio.iscoroutinefunction(self._notify_callback):
                await self._notify_callback(ctx, result, request_id)
            else:
                self._notify_callback(ctx, result, request_id)


@dataclass
class ImmediateAsyncApprover:
    """Async approver that immediately approves/denies. For testing only.

    Usage:
        approver = ImmediateAsyncApprover(approved=True)  # Always approve
        engine = AsyncSudoEngine(approver=approver, agent_id="demo:async-approver", ...)
    """

    approved: bool = True
    approver_id: str | None = None

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        """Immediately return configured approval status."""
        if self.approved:
            return {
                "approved": True,
                "approver_id": self.approver_id,
            }
        return False
