"""Budget checking and committing with idempotent semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Tuple
import sqlite3


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


class SQLiteBudgetManager:
    """Durable budget manager backed by SQLite. Semantics match BudgetManager (idempotent by request_id)."""

    def __init__(
        self,
        path: str | Path,
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
        self.path = Path(path)
        self.agent_limit = agent_limit
        self.tool_limit = tool_limit
        self.window = timedelta(seconds=window_seconds)
        self.spend_counter = spend_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._init_db()

    def check(self, request_id: str, agent: str, tool: str, cost: int) -> BudgetCheckResult:
        if cost < 0:
            raise BudgetStateError("cost must be non-negative")
        now = self._now()
        self._prune(now)
        with self._connect() as conn:
            if self._exists(conn, "committed", request_id) or self._exists(conn, "pending", request_id):
                return BudgetCheckResult(request_id, agent, tool, cost, True)
            self._enforce_limits(conn, now, agent, tool, cost)
            conn.execute(
                "INSERT INTO pending (request_id, agent, tool, cost, checked_at) VALUES (?, ?, ?, ?, ?)",
                (request_id, agent, tool, cost, now.isoformat()),
            )
            conn.commit()
        return BudgetCheckResult(request_id, agent, tool, cost, True)

    def commit(self, request_id: str) -> None:
        now = self._now()
        self._prune(now)
        with self._connect() as conn:
            if self._exists(conn, "committed", request_id):
                return
            row = conn.execute(
                "SELECT agent, tool, cost, checked_at FROM pending WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetStateError("pending check not found for commit")
            agent, tool, cost, checked_at = row
            self._enforce_limits(conn, now, agent, tool, cost)
            conn.execute(
                "INSERT INTO committed (request_id, agent, tool, cost, committed_at) VALUES (?, ?, ?, ?, ?)",
                (request_id, agent, tool, cost, now.isoformat()),
            )
            conn.execute("DELETE FROM pending WHERE request_id = ?", (request_id,))
            conn.commit()

    # ----- internal helpers -----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending (
                    request_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    checked_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS committed (
                    request_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    committed_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _exists(self, conn: sqlite3.Connection, table: str, request_id: str) -> bool:
        row = conn.execute(f"SELECT 1 FROM {table} WHERE request_id = ?", (request_id,)).fetchone()
        return row is not None

    def _usage(self, conn: sqlite3.Connection, now: datetime, *, key: str, value: str) -> int:
        cutoff = (now - self.window).isoformat()
        row = conn.execute(
            f"SELECT COALESCE(SUM(cost), 0) FROM committed WHERE {key} = ? AND committed_at >= ?",
            (value, cutoff),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _enforce_limits(
        self, conn: sqlite3.Connection, now: datetime, agent: str, tool: str, cost: int
    ) -> None:
        agent_usage = self._usage(conn, now, key="agent", value=agent)
        tool_usage = self._usage(conn, now, key="tool", value=tool)
        if self.agent_limit is not None and agent_usage + cost > self.agent_limit:
            raise BudgetExceeded("agent budget exceeded")
        if self.tool_limit is not None and tool_usage + cost > self.tool_limit:
            raise BudgetExceeded("tool budget exceeded")

    def _prune(self, now: datetime) -> None:
        cutoff = (now - self.window).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM committed WHERE committed_at < ?", (cutoff,))
            stale_cutoff = (now - self.window * 2).isoformat()
            conn.execute("DELETE FROM pending WHERE checked_at < ?", (stale_cutoff,))
            conn.commit()


def persistent_budget(
    path: str | Path,
    *,
    agent_limit: int | None,
    tool_limit: int | None,
    window_seconds: int = 60,
    spend_counter: bool = False,
    now: Callable[[], datetime] | None = None,
) -> SQLiteBudgetManager:
    """Helper to create a durable budget manager (SQLite)."""
    return SQLiteBudgetManager(
        path,
        agent_limit=agent_limit,
        tool_limit=tool_limit,
        window_seconds=window_seconds,
        spend_counter=spend_counter,
        now=now,
    )
