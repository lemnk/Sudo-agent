"""Tests for SudoEngine execution and audit behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from sudoagent import ApprovalDenied, ApprovalError, AuditLogError, PolicyError, SudoEngine
from sudoagent.policies import PolicyResult
from sudoagent.types import AuditEntry, Context, Decision
from sudoagent.approvals_store import ApprovalStore


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


class MemoryLedger:
    """In-memory ledger stub for tests."""

    def __init__(self, *, fail_on_event: str | None = None) -> None:
        self.fail_on_event = fail_on_event
        self.entries: list[dict[str, object]] = []

    def append(self, entry: dict[str, object]) -> str:
        if self.fail_on_event is not None and entry.get("event") == self.fail_on_event:
            raise RuntimeError(f"ledger failed on {entry.get('event')}")
        self.entries.append(entry)
        return str(entry.get("decision_hash", "hash"))


class StubApprovalStore(ApprovalStore):
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.resolutions: list[tuple[str, str, str | None]] = []

    def create_pending(
        self, *, request_id: str, policy_hash: str, decision_hash: str, expires_at: datetime | None
    ) -> None:
        self.pending.append(request_id)

    def resolve(
        self,
        *,
        request_id: str,
        state: str,
        approver_id: str | None,
        resolved_at: datetime | None = None,
    ) -> None:
        self.resolutions.append((request_id, state, approver_id))


class BindingApprover:
    """Approver that returns an explicit binding."""

    def __init__(self, binding_override: dict[str, str]) -> None:
        self.binding_override = binding_override
        self.calls: list[str] = []

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> dict[str, object]:
        self.calls.append(request_id)
        return {"approved": True, "binding": self.binding_override}


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
    assert logger.entries[0].metadata["reason_code"] == "APPROVAL_DENIED"


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
    assert logger.entries[0].metadata["reason_code"] == "POLICY_EVALUATION_FAILED"
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
    assert logger.entries[0].metadata["reason_code"] == "APPROVAL_PROCESS_FAILED"
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


def test_decision_ledger_failure_blocks_execution() -> None:
    """Ledger append failure on decision must block execution."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    ledger = MemoryLedger(fail_on_event="decision")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, ledger=ledger, approver=StubApprover(False))

    called = False

    def sample_func() -> int:
        nonlocal called
        called = True
        return 123

    with pytest.raises(AuditLogError, match="Failed to write audit log"):
        engine.execute(sample_func)

    assert called is False
    assert logger.entries == []
    assert ledger.entries == []


def test_outcome_ledger_failure_does_not_block_return() -> None:
    """Outcome ledger append failure must not affect return value."""
    policy = StubPolicy(Decision.ALLOW, "allowed")
    ledger = MemoryLedger(fail_on_event="outcome")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, ledger=ledger, approver=StubApprover(False))

    def sample_func() -> int:
        return 9

    result = engine.execute(sample_func)

    assert result == 9
    # Decision recorded, outcome ledger failure swallowed
    assert len(logger.entries) == 2
    assert logger.entries[0].event == "decision"
    assert logger.entries[1].event == "outcome"
    assert len(ledger.entries) == 1  # decision only


def test_approval_binding_mismatch_decision_hash_fails_closed() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    logger = MemoryLogger()
    ledger = MemoryLedger()
    mismatched_binding = {
        "request_id": "wrong",
        "policy_hash": "wrong",
        "decision_hash": "wrong",
    }
    approver = BindingApprover(binding_override=mismatched_binding)
    engine = SudoEngine(policy=policy, logger=logger, ledger=ledger, approver=approver)

    def sample_func() -> int:
        return 1

    with pytest.raises(ApprovalDenied):
        engine.execute(sample_func)

    assert len(logger.entries) == 1
    decision_entry = logger.entries[0]
    assert decision_entry.event == "decision"
    assert decision_entry.decision == Decision.DENY
    assert decision_entry.metadata["approval_binding"] == mismatched_binding


def test_approval_binding_mismatch_policy_hash_fails_closed() -> None:
    class PolicyWithCode:
        def evaluate(self, ctx: Context) -> PolicyResult:
            return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval", reason_code="X")

    policy = PolicyWithCode()
    logger = MemoryLogger()
    ledger = MemoryLedger()
    approver = BindingApprover(
        binding_override={
            "request_id": "placeholder",
            "policy_hash": "different",
            "decision_hash": "placeholder",
        }
    )
    engine = SudoEngine(policy=policy, logger=logger, ledger=ledger, approver=approver)

    def sample_func() -> int:
        return 2

    with pytest.raises(ApprovalDenied):
        engine.execute(sample_func)

    assert len(logger.entries) == 1
    assert logger.entries[0].decision == Decision.DENY
    assert logger.entries[0].metadata["approval_binding"]["policy_hash"] == "different"


def test_reason_code_propagates_to_ledger_and_audit() -> None:
    class PolicyWithReasonCode:
        def evaluate(self, ctx: Context) -> PolicyResult:
            return PolicyResult(
                decision=Decision.ALLOW,
                reason="allowed",
                reason_code="ALLOW_TRUSTED_ACTION",
            )

    ledger = MemoryLedger()
    logger = MemoryLogger()
    engine = SudoEngine(policy=PolicyWithReasonCode(), logger=logger, ledger=ledger)

    result = engine.execute(lambda: 1)

    assert result == 1
    assert len(ledger.entries) == 2
    decision_entry = ledger.entries[0]
    assert decision_entry["event"] == "decision"
    assert decision_entry["decision"]["reason_code"] == "ALLOW_TRUSTED_ACTION"
    audit_decision = logger.entries[0]
    assert audit_decision.metadata["reason_code"] == "ALLOW_TRUSTED_ACTION"


def test_ledger_entries_include_schema_and_ids() -> None:
    class PolicyWithId:
        policy_id = "policy:demo"

        def evaluate(self, ctx: Context) -> PolicyResult:
            return PolicyResult(
                decision=Decision.REQUIRE_APPROVAL,
                reason="needs approval",
                reason_code="POLICY_REQUIRE_APPROVAL_HIGH_VALUE",
            )

    class ApproverWithId:
        def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> dict[str, object]:
            return {"approved": True, "approver_id": "approver:1"}

    ledger = MemoryLedger()
    logger = MemoryLogger()
    engine = SudoEngine(
        policy=PolicyWithId(),
        logger=logger,
        ledger=ledger,
        approver=ApproverWithId(),
        agent_id="agent:demo",
    )

    result = engine.execute(lambda: 1)

    assert result == 1
    assert len(ledger.entries) == 2
    decision_entry = ledger.entries[0]
    assert decision_entry["schema_version"] == "2.0"
    assert decision_entry["ledger_version"] == "2.0"
    assert decision_entry["agent_id"] == "agent:demo"
    assert decision_entry["decision"]["policy_id"] == "policy:demo"
    assert decision_entry["approval"]["approver_id"] == "approver:1"
    assert decision_entry["decision"]["reason_code"] == "POLICY_REQUIRE_APPROVAL_HIGH_VALUE"

    outcome_entry = ledger.entries[1]
    assert outcome_entry["schema_version"] == "2.0"
    assert outcome_entry["ledger_version"] == "2.0"
    assert outcome_entry["agent_id"] == "agent:demo"
    assert outcome_entry["decision"]["policy_id"] == "policy:demo"
    assert outcome_entry["decision"]["reason_code"] == "POLICY_REQUIRE_APPROVAL_HIGH_VALUE"


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


def test_outcome_ledger_includes_redacted_args_kwargs() -> None:
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    ledger = MemoryLedger()
    engine = SudoEngine(policy=policy, logger=logger, ledger=ledger, approver=StubApprover(False))

    def sample_func(api_key: str, note: str) -> str:
        return note

    result = engine.execute(sample_func, "sk-secret", note="ok")
    assert result == "ok"

    assert len(ledger.entries) == 2
    outcome_entry = ledger.entries[1]
    metadata = outcome_entry.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata["args"][0] == "[redacted]"
    assert metadata["kwargs"]["note"] == "'ok'"


def test_redaction_deterministic_across_calls() -> None:
    policy = StubPolicy(Decision.ALLOW, "allowed")
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    def sample_func(token: str, secret: str) -> str:
        return "ok"

    engine.execute(sample_func, "sk-abc", secret="Bearer token-123")
    engine.execute(sample_func, "sk-abc", secret="Bearer token-123")

    decisions = [e for e in logger.entries if e.event == "decision"]
    assert len(decisions) == 2
    first_meta = decisions[0].metadata
    second_meta = decisions[1].metadata
    assert first_meta["args"] == second_meta["args"] == ["[redacted]"]
    assert first_meta["kwargs"]["secret"] == second_meta["kwargs"]["secret"] == "[redacted]"


def test_policy_receives_redacted_context() -> None:
    class CapturingPolicy:
        def __init__(self) -> None:
            self.ctx: Context | None = None

        def evaluate(self, ctx: Context) -> PolicyResult:
            self.ctx = ctx
            return PolicyResult(decision=Decision.DENY, reason="deny")

    policy = CapturingPolicy()
    logger = MemoryLogger()
    engine = SudoEngine(policy=policy, logger=logger, approver=StubApprover(False))

    with pytest.raises(ApprovalDenied):
        engine.execute(lambda token, count: None, "sk-secret-key", count=7)

    assert policy.ctx is not None
    assert policy.ctx.args[0] == "[redacted]"
    assert policy.ctx.kwargs["count"] == "7"


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


# -----------------------------------------------------------------------------
# Approval store integration
# -----------------------------------------------------------------------------


def test_approval_store_records_pending_and_resolution() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=True)
    logger = MemoryLogger()
    store = StubApprovalStore()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver, approval_store=store)

    result = engine.execute(lambda: 1)
    assert result == 1
    assert len(store.pending) == 1
    assert len(store.resolutions) == 1
    rid = store.pending[0]
    assert store.resolutions[0] == (rid, "approved", None)


def test_approval_store_records_denial() -> None:
    policy = StubPolicy(Decision.REQUIRE_APPROVAL, "needs approval")
    approver = StubApprover(approved=False)
    logger = MemoryLogger()
    store = StubApprovalStore()
    engine = SudoEngine(policy=policy, logger=logger, approver=approver, approval_store=store)

    with pytest.raises(ApprovalDenied):
        engine.execute(lambda: 1)

    assert len(store.pending) == 1
    assert len(store.resolutions) == 1
    rid = store.pending[0]
    assert store.resolutions[0] == (rid, "denied", None)
