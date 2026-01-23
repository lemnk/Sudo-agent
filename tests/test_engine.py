"""Tests for SudoEngine execution and audit behavior."""

from __future__ import annotations

import pytest

from sudoagent import ApprovalDenied, ApprovalError, AuditLogError, PolicyError, SudoEngine
from sudoagent.policies import PolicyResult
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


class ControlledFailureLogger:
    """Logger that optionally fails on a specific audit event."""

    def __init__(self, *, fail_on_event: str | None = None) -> None:
        self.fail_on_event = fail_on_event
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        if self.fail_on_event is not None and entry.event == self.fail_on_event:
            raise RuntimeError(f"logger failed on {entry.event}")
        self.entries.append(entry)


class WeirdPolicy:
    """Test policy that returns an invalid decision type."""

    def evaluate(self, ctx: Context):
        class WeirdResult:
            decision = "weird"
            reason = "weird reason"
        return WeirdResult()


# -----------------------------------------------------------------------------
# v0.1.1: Policy required
# -----------------------------------------------------------------------------


def test_policy_required() -> None:
    """Creating SudoEngine without policy raises ValueError."""
    with pytest.raises(ValueError, match="policy is required"):
        SudoEngine(policy=None)  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# v0.1.1: Thread-safe guard() - does not mutate self.policy
# -----------------------------------------------------------------------------


def test_guard_does_not_mutate_shared_policy() -> None:
    """guard(policy=override) must not mutate engine.policy."""
    default_policy = StubPolicy(Decision.DENY, "default denies")
    override_policy = StubPolicy(Decision.ALLOW, "override allows")
    logger = MemoryLogger()
    engine = SudoEngine(policy=default_policy, logger=logger, approver=StubApprover(False))

    @engine.guard(policy=override_policy)
    def sample_func(x: int) -> int:
        return x * 2

    result = sample_func(5)

    assert result == 10
    # Engine's policy must NOT have been mutated
    assert engine.policy is default_policy


# -----------------------------------------------------------------------------
# v0.1.1: Positional args redaction
# -----------------------------------------------------------------------------


def test_positional_args_redacted() -> None:
    """Positional args with secret-like values are redacted."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(token: str, count: int) -> int:
        return count

    result = engine.execute(sample_func, "sk-secret-key-12345", 42)

    assert result == 42
    # Find the decision entry
    decision_entries = [e for e in logger.entries if e.event == "decision"]
    assert len(decision_entries) >= 1
    args_in_metadata = decision_entries[0].metadata["args"]
    assert args_in_metadata[0] == "[redacted]"
    assert "sk-secret-key-12345" not in str(decision_entries[0].metadata)


# -----------------------------------------------------------------------------
# v0.1.1: Decision + outcome logging with same request_id
# -----------------------------------------------------------------------------


def test_decision_and_outcome_logged_with_same_request_id_on_error() -> None:
    """Allowed function that raises logs decision + outcome error with same request_id."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def failing_func() -> None:
        raise ValueError("something went wrong")

    with pytest.raises(ValueError, match="something went wrong"):
        engine.execute(failing_func)

    # Should have 2 entries: decision + outcome
    assert len(logger.entries) == 2

    decision_entry = logger.entries[0]
    outcome_entry = logger.entries[1]

    assert decision_entry.event == "decision"
    assert decision_entry.decision == Decision.ALLOW

    assert outcome_entry.event == "outcome"
    assert outcome_entry.outcome == "error"
    assert outcome_entry.error_type == "ValueError"
    assert "something went wrong" in (outcome_entry.error or "")

    # Same request_id
    assert decision_entry.request_id == outcome_entry.request_id
    assert decision_entry.request_id != ""


# -----------------------------------------------------------------------------
# Existing tests (updated for v0.1.1 audit schema)
# -----------------------------------------------------------------------------


def test_allow_executes_and_logs() -> None:
    policy = StubPolicy(Decision.ALLOW, "allowed by policy")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(x: int) -> int:
        return x * 2

    result = engine.execute(sample_func, 5)

    assert result == 10
    # v0.1.1: decision + outcome = 2 entries
    assert len(logger.entries) == 2
    decision_entry = logger.entries[0]
    assert decision_entry.event == "decision"
    assert decision_entry.decision == Decision.ALLOW
    assert decision_entry.reason == "allowed by policy"
    assert decision_entry.request_id != ""

    outcome_entry = logger.entries[1]
    assert outcome_entry.event == "outcome"
    assert outcome_entry.outcome == "success"
    assert outcome_entry.request_id == decision_entry.request_id


def test_deny_raises_and_logs() -> None:
    policy = StubPolicy(Decision.DENY, "denied by policy")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(x: int) -> int:
        return x * 2

    with pytest.raises(ApprovalDenied, match="denied by policy"):
        engine.execute(sample_func, 5)

    # Deny path: only decision, no outcome
    assert len(logger.entries) == 1
    assert logger.entries[0].event == "decision"
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "denied by policy"
    assert logger.entries[0].request_id != ""


def test_require_approval_approved_executes_and_logs() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=True)
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver)

    def sample_func(x: int) -> int:
        return x * 3

    result = engine.execute(sample_func, 7)

    assert result == 21
    # v0.1.1: decision + outcome = 2 entries
    assert len(logger.entries) == 2
    decision_entry = logger.entries[0]
    assert decision_entry.event == "decision"
    assert decision_entry.decision == Decision.ALLOW
    assert decision_entry.reason == "needs approval"
    assert decision_entry.request_id != ""
    assert decision_entry.metadata["approved"] is True
    assert decision_entry.metadata["policy_decision"] == "require_approval"
    assert approver.last_request_id == decision_entry.request_id

    outcome_entry = logger.entries[1]
    assert outcome_entry.event == "outcome"
    assert outcome_entry.outcome == "success"


def test_require_approval_denied_raises_and_logs() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=False)
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver)

    def sample_func(x: int) -> int:
        return x * 3

    with pytest.raises(ApprovalDenied, match="needs approval"):
        engine.execute(sample_func, 7)

    # Denied approval: only decision, no outcome
    assert len(logger.entries) == 1
    assert logger.entries[0].event == "decision"
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "needs approval"
    assert logger.entries[0].request_id != ""
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
    assert logger.entries[0].event == "decision"
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "policy evaluation failed"
    assert "error" in logger.entries[0].metadata
    assert logger.entries[0].request_id != ""


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
    assert logger.entries[0].event == "decision"
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "approval process failed"
    assert "error" in logger.entries[0].metadata
    assert logger.entries[0].request_id != ""


def test_sensitive_kwargs_redacted_in_audit() -> None:
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(api_key: str, user_id: str) -> str:
        return f"user={user_id}"

    result = engine.execute(sample_func, api_key="sk-test", user_id="user_123")

    assert result == "user=user_123"
    # v0.1.1: decision + outcome = 2 entries
    assert len(logger.entries) == 2
    decision_entry = logger.entries[0]
    assert decision_entry.event == "decision"
    assert decision_entry.decision == Decision.ALLOW
    kwargs_in_metadata = decision_entry.metadata["kwargs"]
    assert kwargs_in_metadata["api_key"] == "[redacted]"
    assert "sk-test" not in str(decision_entry.metadata)


# -----------------------------------------------------------------------------
# v0.1.1: Audit log failure semantics
# -----------------------------------------------------------------------------


def test_decision_log_failure_blocks_execution() -> None:
    """If decision logging fails, execution must be blocked (fail-closed)."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = ControlledFailureLogger(fail_on_event="decision")
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    called = False

    def sample_func() -> int:
        nonlocal called
        called = True
        return 123

    with pytest.raises(AuditLogError, match="Failed to write audit log"):
        engine.execute(sample_func)

    assert called is False
    # Decision failed to log; no entries should be recorded.
    assert len(logger.entries) == 0


def test_outcome_log_failure_does_not_block_return() -> None:
    """Outcome logging is best-effort; failures must not block successful returns."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = ControlledFailureLogger(fail_on_event="outcome")
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func() -> int:
        return 7

    result = engine.execute(sample_func)

    assert result == 7
    # Decision logged, outcome failed and should not be appended
    assert len(logger.entries) == 1
    assert logger.entries[0].event == "decision"


# -----------------------------------------------------------------------------
# v0.1.1: Value-based redaction
# -----------------------------------------------------------------------------


def test_jwt_value_redacted() -> None:
    """JWT-like values should be redacted in args/kwargs metadata."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

    def sample_func(token: str) -> str:
        return "ok"

    result = engine.execute(sample_func, jwt_like)
    assert result == "ok"

    decision_entry = next(e for e in logger.entries if e.event == "decision")
    assert decision_entry.metadata["args"][0] == "[redacted]"
    assert jwt_like not in str(decision_entry.metadata)


def test_pem_value_redacted() -> None:
    """PEM blocks should be redacted in kwargs metadata."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    pem = "-----BEGIN PRIVATE KEY-----\nABCDEF\n-----END PRIVATE KEY-----"

    def sample_func(config: str) -> str:
        return "ok"

    result = engine.execute(sample_func, config=pem)
    assert result == "ok"

    decision_entry = next(e for e in logger.entries if e.event == "decision")
    assert decision_entry.metadata["kwargs"]["config"] == "[redacted]"
    assert pem not in str(decision_entry.metadata)


# -----------------------------------------------------------------------------
# v0.1.1: Unknown decision fails closed
# -----------------------------------------------------------------------------


def test_unknown_decision_fails_closed() -> None:
    """Unknown decision types should fail closed with DENY."""
    policy = WeirdPolicy()
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func() -> None:
        raise AssertionError("should not execute")

    with pytest.raises(PolicyError, match="Unknown decision"):
        engine.execute(sample_func)

    assert len(logger.entries) == 1
    assert logger.entries[0].event == "decision"
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].reason == "unknown decision type"

