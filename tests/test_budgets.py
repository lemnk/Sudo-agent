from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sudoagent import ApprovalDenied, SudoEngine
from sudoagent.budgets import (
    BudgetError,
    BudgetExceeded,
    BudgetManager,
    BudgetStateError,
    SQLiteBudgetManager,
)
from sudoagent.policies import PolicyResult
from sudoagent.types import AuditEntry, Context, Decision

TEST_AGENT_ID = "test-agent"


def _fixed_time():
    base = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
    current = {"now": base}

    def now() -> datetime:
        return current["now"]

    def advance(seconds: int) -> None:
        current["now"] = current["now"] + timedelta(seconds=seconds)

    return now, advance


def test_check_commit_success_and_limits() -> None:
    now, advance = _fixed_time()
    mgr = BudgetManager(agent_limit=5, tool_limit=5, window_seconds=60, now=now)

    mgr.check("r1", agent="agent", tool="tool", cost=2)
    mgr.commit("r1")

    mgr.check("r2", agent="agent", tool="tool", cost=3)
    mgr.commit("r2")

    advance(61)
    mgr.check("r3", agent="agent", tool="tool", cost=5)  # window rolled


def test_commit_idempotent_does_not_double_charge() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=5, tool_limit=5, window_seconds=60, now=now)

    mgr.check("r1", agent="agent", tool="tool", cost=2)
    mgr.commit("r1")
    mgr.commit("r1")  # idempotent

    mgr.check("r2", agent="agent", tool="tool", cost=3)  # would fail if doubled
    mgr.commit("r2")


def test_commit_without_check_fails_closed() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=5, tool_limit=5, window_seconds=60, now=now)

    with pytest.raises(BudgetStateError):
        mgr.commit("missing")


def test_check_denies_when_limit_exceeded() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=3, tool_limit=3, window_seconds=60, now=now)

    mgr.check("r1", agent="agent", tool="tool", cost=2)
    mgr.commit("r1")

    with pytest.raises(BudgetExceeded):
        mgr.check("r2", agent="agent", tool="tool", cost=2)


def test_state_error_on_negative_cost() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=3, tool_limit=3, window_seconds=60, now=now)

    with pytest.raises(BudgetError):
        mgr.check("r1", agent="agent", tool="tool", cost=-1)


def test_budget_idempotent_recheck_same_request() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=5, tool_limit=5, window_seconds=60, now=now)

    first = mgr.check("r1", agent="agent", tool="tool", cost=2)
    second = mgr.check("r1", agent="agent", tool="tool", cost=2)

    assert first.accepted is True
    assert second.accepted is True


def test_budget_idempotent_recommit_same_request() -> None:
    now, _ = _fixed_time()
    mgr = BudgetManager(agent_limit=5, tool_limit=5, window_seconds=60, now=now)

    mgr.check("r1", agent="agent", tool="tool", cost=2)
    mgr.commit("r1")
    mgr.commit("r1")  # should not raise

    mgr.check("r2", agent="agent", tool="tool", cost=3)


def test_budget_window_expiry_allows_new_requests() -> None:
    now, advance = _fixed_time()
    mgr = BudgetManager(agent_limit=1, tool_limit=None, window_seconds=60, now=now)

    mgr.check("r1", agent="agent", tool="tool", cost=1)
    mgr.commit("r1")

    advance(61)

    result = mgr.check("r2", agent="agent", tool="tool", cost=1)
    assert result.accepted is True


class _AllowPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.ALLOW, reason="allowed")


class _MemoryLogger:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class _MemoryLedger:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, entry: dict[str, object]) -> str:
        self.entries.append(entry)
        return str(entry.get("decision_hash", "hash"))


def test_budget_exceeded_on_check_blocks_execution() -> None:
    budget = BudgetManager(agent_limit=1, tool_limit=None, window_seconds=60)
    logger = _MemoryLogger()
    ledger = _MemoryLedger()
    engine = SudoEngine(agent_id=TEST_AGENT_ID, 
        policy=_AllowPolicy(),
        logger=logger,
        ledger=ledger,
        budget_manager=budget,
    )

    result = engine.execute(lambda: 1)
    assert result == 1

    with pytest.raises(ApprovalDenied, match="budget exceeded"):
        engine.execute(lambda: 2)

    decision_entry = logger.entries[-1]
    assert decision_entry.event == "decision"
    assert decision_entry.metadata["reason_code"] == "BUDGET_EXCEEDED_AGENT_RATE"


def test_budget_commit_happens_before_execution() -> None:
    budget = BudgetManager(agent_limit=1, tool_limit=None, window_seconds=60)
    logger = _MemoryLogger()
    ledger = _MemoryLedger()
    engine = SudoEngine(agent_id=TEST_AGENT_ID, 
        policy=_AllowPolicy(),
        logger=logger,
        ledger=ledger,
        budget_manager=budget,
    )

    def failing() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        engine.execute(failing)

    with pytest.raises(ApprovalDenied, match="budget exceeded"):
        engine.execute(lambda: None)


def test_budget_cost_override_affects_limits() -> None:
    budget = BudgetManager(agent_limit=2, tool_limit=None, window_seconds=60)
    logger = _MemoryLogger()
    ledger = _MemoryLedger()
    engine = SudoEngine(agent_id=TEST_AGENT_ID, 
        policy=_AllowPolicy(),
        logger=logger,
        ledger=ledger,
        budget_manager=budget,
    )

    result = engine.execute(lambda: 1, budget_cost=2)
    assert result == 1

    with pytest.raises(ApprovalDenied, match="budget exceeded"):
        engine.execute(lambda: 2, budget_cost=1)


def test_sqlite_budget_persists_across_instances(tmp_path):
    db = tmp_path / "budget.sqlite"
    mgr = SQLiteBudgetManager(db, agent_limit=2, tool_limit=None, window_seconds=60)
    mgr.check("req-1", agent="agent-a", tool="t1", cost=1)
    mgr.commit("req-1")

    mgr2 = SQLiteBudgetManager(db, agent_limit=2, tool_limit=None, window_seconds=60)
    with pytest.raises(BudgetExceeded):
        mgr2.check("req-2", agent="agent-a", tool="t1", cost=2)


def test_sqlite_budget_idempotent_commit(tmp_path):
    db = tmp_path / "budget.sqlite"
    mgr = SQLiteBudgetManager(db, agent_limit=3, tool_limit=None, window_seconds=60)
    mgr.check("req-1", agent="agent-a", tool="t1", cost=2)
    mgr.commit("req-1")
    mgr.commit("req-1")  # second commit should not raise


def test_sqlite_budget_window_prune(tmp_path):
    db = tmp_path / "budget.sqlite"
    base = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
    current = {"now": base}

    def now() -> datetime:
        return current["now"]

    mgr = SQLiteBudgetManager(db, agent_limit=2, tool_limit=None, window_seconds=60, now=now)
    mgr.check("req-1", agent="agent-a", tool="t1", cost=2)
    mgr.commit("req-1")

    current["now"] = current["now"] + timedelta(seconds=120)
    mgr._prune(now())
    mgr.check("req-2", agent="agent-a", tool="t1", cost=2)
