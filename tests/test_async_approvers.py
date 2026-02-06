"""Tests for native async approvers and approval store."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sudoagent.notifiers.async_approvers import (
    ApprovalTimeoutError,
    ImmediateAsyncApprover,
    PollingAsyncApprover,
)
from sudoagent.policies import PolicyResult
from sudoagent.types import Context, Decision


class MockAsyncApprovalStore:
    """In-memory async approval store for testing."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def create_pending(
        self, *, request_id: str, policy_hash: str, decision_hash: str, expires_at
    ) -> None:
        self.records[request_id] = {
            "request_id": request_id,
            "policy_hash": policy_hash,
            "decision_hash": decision_hash,
            "state": "pending",
            "approver_id": None,
        }

    async def resolve(
        self, *, request_id: str, state: str, approver_id: str | None
    ) -> None:
        if request_id in self.records:
            self.records[request_id]["state"] = state
            self.records[request_id]["approver_id"] = approver_id

    async def fetch(self, request_id: str) -> dict[str, Any] | None:
        return self.records.get(request_id)

    async def expire_expired(self) -> int:
        return 0


@pytest.fixture
def ctx() -> Context:
    return Context(action="test.action", args=(), kwargs={}, metadata={})


@pytest.fixture
def policy_result() -> PolicyResult:
    return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")


class TestImmediateAsyncApprover:
    def test_approve_returns_true(self, ctx, policy_result):
        async def run():
            approver = ImmediateAsyncApprover(approved=True, approver_id="test-approver")
            return await approver.approve(ctx, policy_result, "req-1")

        result = asyncio.run(run())
        assert result["approved"] is True
        assert result["approver_id"] == "test-approver"

    def test_deny_returns_false(self, ctx, policy_result):
        async def run():
            approver = ImmediateAsyncApprover(approved=False)
            return await approver.approve(ctx, policy_result, "req-1")

        result = asyncio.run(run())
        assert result is False


class TestPollingAsyncApprover:
    def test_polls_until_approved(self, ctx, policy_result):
        async def run():
            store = MockAsyncApprovalStore()
            approver = PollingAsyncApprover(store=store, poll_interval=0.01, timeout=1.0)

            await store.create_pending(
                request_id="req-1",
                policy_hash="policy-hash",
                decision_hash="decision-hash",
                expires_at=None,
            )

            async def approve_later():
                await asyncio.sleep(0.05)
                await store.resolve(
                    request_id="req-1", state="approved", approver_id="approver-1"
                )

            task = asyncio.create_task(approve_later())
            result = await approver.approve(ctx, policy_result, "req-1")
            await task
            return result

        result = asyncio.run(run())
        assert result["approved"] is True
        assert result["approver_id"] == "approver-1"
        assert result["binding"]["request_id"] == "req-1"

    def test_polls_until_denied(self, ctx, policy_result):
        async def run():
            store = MockAsyncApprovalStore()
            approver = PollingAsyncApprover(store=store, poll_interval=0.01, timeout=1.0)

            await store.create_pending(
                request_id="req-1",
                policy_hash="policy-hash",
                decision_hash="decision-hash",
                expires_at=None,
            )

            async def deny_later():
                await asyncio.sleep(0.05)
                await store.resolve(request_id="req-1", state="denied", approver_id=None)

            task = asyncio.create_task(deny_later())
            result = await approver.approve(ctx, policy_result, "req-1")
            await task
            return result

        result = asyncio.run(run())
        assert result is False

    def test_timeout_raises_error(self, ctx, policy_result):
        async def run():
            store = MockAsyncApprovalStore()
            approver = PollingAsyncApprover(store=store, poll_interval=0.01, timeout=0.05)

            await store.create_pending(
                request_id="req-1",
                policy_hash="policy-hash",
                decision_hash="decision-hash",
                expires_at=None,
            )

            await approver.approve(ctx, policy_result, "req-1")

        with pytest.raises(ApprovalTimeoutError, match="exceeded 0.05s"):
            asyncio.run(run())

    def test_missing_record_returns_false(self, ctx, policy_result):
        async def run():
            store = MockAsyncApprovalStore()
            approver = PollingAsyncApprover(store=store, poll_interval=0.01, timeout=0.1)
            return await approver.approve(ctx, policy_result, "nonexistent")

        result = asyncio.run(run())
        assert result is False

    def test_expired_record_returns_false(self, ctx, policy_result):
        async def run():
            store = MockAsyncApprovalStore()
            approver = PollingAsyncApprover(store=store, poll_interval=0.01, timeout=1.0)

            await store.create_pending(
                request_id="req-1",
                policy_hash="policy-hash",
                decision_hash="decision-hash",
                expires_at=None,
            )
            await store.resolve(request_id="req-1", state="expired", approver_id=None)
            return await approver.approve(ctx, policy_result, "req-1")

        result = asyncio.run(run())
        assert result is False


class TestBudgetBlockInLedger:
    """Test that budget blocks are explicit in ledger entries."""

    def test_budget_block_present_on_allow(self):
        """Budget block should be present when budget_cost > 0."""
        from sudoagent import SudoEngine, AllowAllPolicy

        class MemoryLedger:
            def __init__(self):
                self.entries = []

            def append(self, entry):
                self.entries.append(entry)
                return "hash"

            def verify(self, *, public_key=None):
                pass

        ledger = MemoryLedger()
        engine = SudoEngine(policy=AllowAllPolicy(), ledger=ledger, agent_id="test-agent")

        result = engine.execute(lambda: 42, budget_cost=5)

        assert result == 42
        assert len(ledger.entries) >= 1

        decision_entry = ledger.entries[0]
        assert "budget" in decision_entry
        assert decision_entry["budget"]["cost"] == 5
        assert decision_entry["budget"]["agent_id"] == "test-agent"
