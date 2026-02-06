"""PollingAsyncApprover demo.

This example shows how to wait for approvals without holding threads:
- AsyncSudoEngine persists a pending approval record
- PollingAsyncApprover yields to the event loop between polls
- A simulated "human" resolves the approval after a delay
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sudoagent import AsyncSudoEngine, Context, Decision, PolicyResult
from sudoagent.adapters.sync_to_async import SyncAuditLoggerAdapter, SyncLedgerAdapter
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.loggers.jsonl import JsonlAuditLogger
from sudoagent.notifiers.async_approvers import PollingAsyncApprover


class RequireApprovalPolicy:
    """Policy that always requires approval (for demo)."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="demo: requires approval")


class InMemoryAsyncApprovalStore:
    """In-memory AsyncApprovalStore for demos/tests (no external dependencies)."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._pending_event = asyncio.Event()
        self._last_request_id: str | None = None

    async def create_pending(
        self,
        *,
        request_id: str,
        policy_hash: str,
        decision_hash: str,
        expires_at: datetime | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._records[request_id] = {
            "request_id": request_id,
            "policy_hash": policy_hash,
            "decision_hash": decision_hash,
            "state": "pending",
            "approver_id": None,
            "created_at": now,
            "resolved_at": None,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
        }
        self._last_request_id = request_id
        self._pending_event.set()

    async def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        record = self._records.get(request_id)
        if record is None:
            return
        record["state"] = state
        record["approver_id"] = approver_id
        record["resolved_at"] = (resolved_at or datetime.now(timezone.utc)).isoformat()

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        return self._records.get(request_id)

    async def expire_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired = 0
        for record in self._records.values():
            if record.get("state") != "pending":
                continue
            expires_at = record.get("expires_at")
            if not expires_at:
                continue
            if datetime.fromisoformat(expires_at) <= now:
                record["state"] = "expired"
                record["resolved_at"] = now.isoformat()
                expired += 1
        return expired

    async def wait_for_pending_request_id(self) -> str:
        await self._pending_event.wait()
        if self._last_request_id is None:
            raise RuntimeError("pending request_id missing")
        return self._last_request_id


async def simulate_human_approver(store: InMemoryAsyncApprovalStore, *, delay_s: float) -> None:
    request_id = await store.wait_for_pending_request_id()
    await asyncio.sleep(delay_s)
    await store.resolve(request_id=request_id, state="approved", approver_id="demo-approver")
    print(f"[simulated approver] approved request_id={request_id} after {delay_s:.1f}s")


async def ticker(stop: asyncio.Event) -> None:
    i = 0
    while not stop.is_set():
        print(f"[tick {i}] event loop is free while waiting for approval")
        i += 1
        await asyncio.sleep(0.2)


async def main() -> None:
    ledger_path = Path("demo_async_ledger.jsonl")
    audit_path = Path("demo_async_audit.jsonl")

    store = InMemoryAsyncApprovalStore()
    approver = PollingAsyncApprover(store=store, poll_interval=0.1, timeout=5.0)

    ledger = SyncLedgerAdapter(JSONLLedger(ledger_path))
    logger = SyncAuditLoggerAdapter(JsonlAuditLogger(str(audit_path)))

    engine = AsyncSudoEngine(
        policy=RequireApprovalPolicy(),
        approver=approver,
        logger=logger,
        ledger=ledger,
        approval_store=store,
        agent_id="demo:async-approver",
    )

    async def guarded_call(x: int) -> int:
        await asyncio.sleep(0.1)
        return x * 2

    stop = asyncio.Event()
    tick_task = asyncio.create_task(ticker(stop))
    approver_task = asyncio.create_task(simulate_human_approver(store, delay_s=1.0))

    try:
        result = await engine.execute(guarded_call, 5)
    finally:
        stop.set()
        await tick_task
        await approver_task

    print(f"Result: {result}")
    print(f"Ledger: {ledger_path}")
    print(f"Audit:  {audit_path}")
    print(f"Verify: sudoagent verify {ledger_path}")


if __name__ == "__main__":
    asyncio.run(main())
