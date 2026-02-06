from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from sudoagent.async_engine import AsyncSudoEngine
from sudoagent.errors import ApprovalDenied
from sudoagent.policies import PolicyResult
from sudoagent.types import AuditEntry, Context, Decision


class RequireApprovalPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")


@dataclass
class InMemoryAsyncLedger:
    entries: list[dict[str, Any]] = field(default_factory=list)

    async def append(self, entry: dict[str, Any]) -> str:
        self.entries.append(entry)
        return f"entry-{len(self.entries)}"

    async def verify(self, *, public_key: Any | None = None) -> None:
        return None


@dataclass
class InMemoryAsyncAuditLogger:
    entries: list[AuditEntry] = field(default_factory=list)

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


@dataclass
class InMemoryAsyncApprovalStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def create_pending(
        self,
        *,
        request_id: str,
        policy_hash: str,
        decision_hash: str,
        expires_at: datetime | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.records[request_id] = {
            "request_id": request_id,
            "policy_hash": policy_hash,
            "decision_hash": decision_hash,
            "state": "pending",
            "approver_id": None,
            "created_at": now,
            "resolved_at": None,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "approval_id": request_id,
        }

    async def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        record = self.records.get(request_id)
        if record is None:
            return
        record["state"] = state
        record["approver_id"] = approver_id
        record["resolved_at"] = (
            (resolved_at or datetime.now(timezone.utc)).isoformat()
        )

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        return self.records.get(request_id)

    async def expire_expired(self) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for record in self.records.values():
            if record.get("state") != "pending":
                continue
            expires_at = record.get("expires_at")
            if not expires_at:
                continue
            if datetime.fromisoformat(expires_at) < now:
                record["state"] = "expired"
                record["resolved_at"] = now.isoformat()
                count += 1
        return count


@dataclass
class DelayedApproveApprover:
    delay_seconds: float = 0.05

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        await asyncio.sleep(self.delay_seconds)
        return {"approved": True, "approver_id": "human"}


@dataclass
class StoreCheckingApprover:
    store: InMemoryAsyncApprovalStore

    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        record = await self.store.fetch(request_id)
        assert record is not None
        assert record["state"] == "pending"
        return {"approved": True, "approver_id": "human"}


@dataclass
class MismatchedBindingApprover:
    async def approve(
        self, ctx: Context, result: PolicyResult, request_id: str
    ) -> bool | Mapping[str, object]:
        return {
            "approved": True,
            "approver_id": "human",
            "binding": {
                "request_id": request_id,
                "policy_hash": "wrong-policy",
                "decision_hash": "wrong-decision",
            },
        }


async def _run_batch(engine: AsyncSudoEngine, count: int) -> list[int]:
    async def _work(n: int) -> int:
        return n

    tasks = [engine.execute(_work, i) for i in range(count)]
    return await asyncio.gather(*tasks)


def test_async_engine_handles_concurrent_approval_waits() -> None:
    async def _run() -> None:
        engine = AsyncSudoEngine(
            policy=RequireApprovalPolicy(),
            approver=DelayedApproveApprover(delay_seconds=0.05),
            logger=InMemoryAsyncAuditLogger(),
            ledger=InMemoryAsyncLedger(),
            approval_store=InMemoryAsyncApprovalStore(),
            agent_id="agent:test",
        )

        started = time.perf_counter()
        results = await _run_batch(engine, count=20)
        elapsed = time.perf_counter() - started

        assert results == list(range(20))
        # If approval waits were serialized, this would be ~1.0s+.
        assert elapsed < 0.6

    asyncio.run(_run())


def test_async_engine_persists_pending_before_approval_wait() -> None:
    async def _run() -> None:
        store = InMemoryAsyncApprovalStore()
        engine = AsyncSudoEngine(
            policy=RequireApprovalPolicy(),
            approver=StoreCheckingApprover(store=store),
            logger=InMemoryAsyncAuditLogger(),
            ledger=InMemoryAsyncLedger(),
            approval_store=store,
            agent_id="agent:test",
        )

        result = await engine.execute(lambda: 7)
        assert result == 7

    asyncio.run(_run())


def test_async_engine_rejects_mismatched_approval_binding() -> None:
    async def _run() -> None:
        ledger = InMemoryAsyncLedger()
        engine = AsyncSudoEngine(
            policy=RequireApprovalPolicy(),
            approver=MismatchedBindingApprover(),
            logger=InMemoryAsyncAuditLogger(),
            ledger=ledger,
            approval_store=InMemoryAsyncApprovalStore(),
            agent_id="agent:test",
        )

        with pytest.raises(ApprovalDenied):
            await engine.execute(lambda: 1)

        decision_entries = [e for e in ledger.entries if e.get("event") == "decision"]
        assert decision_entries
        assert decision_entries[-1]["decision"]["effect"] == Decision.DENY.value

    asyncio.run(_run())
