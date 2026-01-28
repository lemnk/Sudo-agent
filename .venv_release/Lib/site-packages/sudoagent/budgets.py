"""Budget checking and committing with idempotent semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Tuple


class BudgetError(RuntimeError):
    """Base class for budget errors."""


class BudgetExceeded(BudgetError):
    """Raised when a budget limit is exceeded."""


class BudgetStateError(BudgetError):
    """Raised when budget state is invalid or missing."""


@dataclass(frozen=True)
class BudgetCheckResult:
    request_id: str
    agent: str
    tool: str
    cost: int
    accepted: bool


class BudgetManager:
    """Simple in-memory budget manager with windowed limits."""

    def __init__(
        self,
        *,
        agent_limit: int | None,
        tool_limit: int | None,
        window_seconds: int,
        spend_counter: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if agent_limit is not None and agent_limit < 0:
            raise ValueError("agent_limit must be non-negative when provided")
        if tool_limit is not None and tool_limit < 0:
            raise ValueError("tool_limit must be non-negative when provided")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.agent_limit = agent_limit
        self.tool_limit = tool_limit
        self.window = timedelta(seconds=window_seconds)
        self.spend_counter = spend_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._pending: Dict[str, Tuple[str, str, int, datetime]] = {}
        self._committed: Dict[str, Tuple[str, str, int, datetime]] = {}
        self.total_spend: int = 0

    def check(self, request_id: str, agent: str, tool: str, cost: int) -> BudgetCheckResult:
        """Perform a budget check; idempotent by request_id."""
        if cost < 0:
            raise BudgetStateError("cost must be non-negative")
        now = self._now()
        self._prune(now)
        if request_id in self._committed:
            return BudgetCheckResult(request_id, agent, tool, cost, True)
        if request_id in self._pending:
            return BudgetCheckResult(request_id, agent, tool, cost, True)

        agent_usage = self._current_usage(now, key_type="agent", key_value=agent)
        tool_usage = self._current_usage(now, key_type="tool", key_value=tool)

        if self.agent_limit is not None and agent_usage + cost > self.agent_limit:
            raise BudgetExceeded("agent budget exceeded")
        if self.tool_limit is not None and tool_usage + cost > self.tool_limit:
            raise BudgetExceeded("tool budget exceeded")

        self._pending[request_id] = (agent, tool, cost, now)
        return BudgetCheckResult(request_id, agent, tool, cost, True)

    def commit(self, request_id: str) -> None:
        """Commit a previously checked request; idempotent by request_id."""
        now = self._now()
        self._prune(now)
        if request_id in self._committed:
            return
        if request_id not in self._pending:
            raise BudgetStateError("pending check not found for commit")

        agent, tool, cost, checked_at = self._pending[request_id]
        agent_usage = self._current_usage(now, key_type="agent", key_value=agent)
        tool_usage = self._current_usage(now, key_type="tool", key_value=tool)

        if self.agent_limit is not None and agent_usage + cost > self.agent_limit:
            raise BudgetExceeded("agent budget exceeded")
        if self.tool_limit is not None and tool_usage + cost > self.tool_limit:
            raise BudgetExceeded("tool budget exceeded")

        self._committed[request_id] = (agent, tool, cost, checked_at)
        if self.spend_counter:
            self.total_spend += cost
        del self._pending[request_id]

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.window
        self._committed = {
            rid: record for rid, record in self._committed.items() if record[3] >= cutoff
        }
        stale_cutoff = now - (self.window * 2)
        self._pending = {
            rid: record for rid, record in self._pending.items() if record[3] >= stale_cutoff
        }

    def _current_usage(self, now: datetime, *, key_type: str, key_value: str) -> int:
        usage = 0
        cutoff = now - self.window
        for _, (agent, tool, cost, ts) in self._committed.items():
            if ts < cutoff:
                continue
            if key_type == "agent" and agent == key_value:
                usage += cost
            if key_type == "tool" and tool == key_value:
                usage += cost
        return usage
