"""Tests for SudoEngine execution and audit behavior."""

from __future__ import annotations

import pytest

from sudoagent import ApprovalDenied, ApprovalError, PolicyError, SudoEngine
from sudoagent.policies import Policy, PolicyResult
from sudoagent.types import AuditEntry, Context, Decision


class StubPolicy:
    """Test policy that returns a fixed decision."""

    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        self.reason = reason

    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=self.decision, reason=self.reason)


class FailingPolicy:
    """Test policy that raises an exception."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        raise RuntimeError("policy exploded")


class StubApprover:
    """Test approver that returns a fixed response."""

    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.last_request_id: str | None = None

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        self.last_request_id = request_id
        return self.approved


class FailingApprover:
    """Test approver that raises an exception."""

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        raise RuntimeError("approver exploded")


class MemoryLogger:
    """Test logger that collects audit entries in memory."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_allow_executes_and_logs() -> None:
    policy = StubPolicy(Decision.ALLOW, "allowed by policy")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(x: int) -> int:
        return x * 2

    result = engine.execute(sample_func, 5)

    assert result == 10
    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.ALLOW
    assert logger.entries[0].reason == "allowed by policy"


def test_deny_raises_and_logs() -> None:
    policy = StubPolicy(Decision.DENY, "denied by policy")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(x: int) -> int:
        return x * 2

    with pytest.raises(ApprovalDenied, match="denied by policy"):
        engine.execute(sample_func, 5)

    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "denied by policy"


def test_require_approval_approved_executes_and_logs() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=True)
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver)

    def sample_func(x: int) -> int:
        return x * 3

    result = engine.execute(sample_func, 7)

    assert result == 21
    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.ALLOW
    assert logger.entries[0].reason == "needs approval"
    assert "request_id" in logger.entries[0].metadata
    assert logger.entries[0].metadata["approved"] is True
    assert logger.entries[0].metadata["policy_decision"] == "require_approval"
    assert approver.last_request_id is not None


def test_require_approval_denied_raises_and_logs() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=False)
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver)

    def sample_func(x: int) -> int:
        return x * 3

    with pytest.raises(ApprovalDenied, match="denied by user"):
        engine.execute(sample_func, 7)

    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "needs approval"
    assert "request_id" in logger.entries[0].metadata
    assert logger.entries[0].metadata["approved"] is False
    assert logger.entries[0].metadata["policy_decision"] == "require_approval"


def test_policy_exception_fails_closed() -> None:
    policy = FailingPolicy()
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(x: int) -> int:
        return x * 2

    with pytest.raises(PolicyError, match="Policy evaluation failed"):
        engine.execute(sample_func, 5)

    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "policy evaluation failed"
    assert "error" in logger.entries[0].metadata


def test_approver_exception_fails_closed() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = FailingApprover()
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver)

    def sample_func(x: int) -> int:
        return x * 2

    with pytest.raises(ApprovalError, match="Approval process failed"):
        engine.execute(sample_func, 5)

    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "approval process failed"
    assert "error" in logger.entries[0].metadata
    assert "request_id" in logger.entries[0].metadata
