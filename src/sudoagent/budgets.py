"""Budget checking and committing with idempotent semantics."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, Tuple
import sqlite3
import threading


class BudgetError(RuntimeError):
    """Base class for budget errors."""


class BudgetExceeded(BudgetError):
    """Raised when a budget limit is exceeded."""

    def __init__(self, message: str, *, scope: str | None = None) -> None:
        super().__init__(message)
        self.scope = scope


class BudgetStateError(BudgetError):
    """Raised when budget state is invalid or missing."""


@dataclass(frozen=True)
class BudgetCheckResult:
    request_id: str
    agent: str
    tool: str
    cost: int
    accepted: bool


def _validate_cost(cost: int) -> None:
    if cost < 0:
        raise BudgetStateError("cost must be non-negative")


def _enforce_limits(
    *,
    agent_usage: int,
    tool_usage: int,
    cost: int,
    agent_limit: int | None,
    tool_limit: int | None,
) -> None:
    if agent_limit is not None and agent_usage + cost > agent_limit:
        raise BudgetExceeded("agent budget exceeded", scope="agent")
    if tool_limit is not None and tool_usage + cost > tool_limit:
        raise BudgetExceeded("tool budget exceeded", scope="tool")


def _check_common(
    *,
    request_id: str,
    agent: str,
    tool: str,
    cost: int,
    now: datetime,
    exists_committed: Callable[[str], bool],
    exists_pending: Callable[[str], bool],
    usage: Callable[[str, str], int],
    add_pending: Callable[[str, str, str, int, datetime], None],
    agent_limit: int | None,
    tool_limit: int | None,
) -> BudgetCheckResult:
    if exists_committed(request_id) or exists_pending(request_id):
        return BudgetCheckResult(request_id, agent, tool, cost, True)

    agent_usage = usage("agent", agent)
    tool_usage = usage("tool", tool)
    _enforce_limits(
        agent_usage=agent_usage,
        tool_usage=tool_usage,
        cost=cost,
        agent_limit=agent_limit,
        tool_limit=tool_limit,
    )
    add_pending(request_id, agent, tool, cost, now)
    return BudgetCheckResult(request_id, agent, tool, cost, True)


def _commit_common(
    *,
    request_id: str,
    now: datetime,
    exists_committed: Callable[[str], bool],
    get_pending: Callable[[str], Tuple[str, str, int, datetime] | None],
    add_committed: Callable[[str, str, str, int, datetime], None],
    delete_pending: Callable[[str], None],
    spend_counter: bool,
    on_spend: Callable[[int], None],
) -> None:
    if exists_committed(request_id):
        return
    pending = get_pending(request_id)
    if pending is None:
        raise BudgetStateError("pending check not found for commit")
    agent, tool, cost, checked_at = pending
    add_committed(request_id, agent, tool, cost, now)
    if spend_counter:
        on_spend(cost)
    delete_pending(request_id)


class BudgetManager:
    """Simple in-memory budget manager with windowed limits."""

    def __init__(
        self,
        *,
        agent_limit: int | None,
        tool_limit: int | None,
        window_seconds: int,
        budget_key: str | None = None,
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
        self.budget_key = budget_key
        self.window_seconds = window_seconds
        self.window = timedelta(seconds=window_seconds)
        self.spend_counter = spend_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._pending: Dict[str, Tuple[str, str, int, datetime]] = {}
        self._committed: Dict[str, Tuple[str, str, int, datetime]] = {}
        self.total_spend: int = 0
        self._lock = threading.Lock()

    def check(self, request_id: str, agent: str, tool: str, cost: int) -> BudgetCheckResult:
        """Perform a budget check; idempotent by request_id."""
        _validate_cost(cost)
        now = self._now()
        with self._lock:
            self._prune(now)
            return _check_common(
                request_id=request_id,
                agent=agent,
                tool=tool,
                cost=cost,
                now=now,
                exists_committed=lambda rid: rid in self._committed,
                exists_pending=lambda rid: rid in self._pending,
                usage=lambda key_type, key_value: self._current_usage(
                    now, key_type=key_type, key_value=key_value
                ),
                add_pending=lambda rid, a, t, c, ts: self._pending.__setitem__(
                    rid, (a, t, c, ts)
                ),
                agent_limit=self.agent_limit,
                tool_limit=self.tool_limit,
            )

    def commit(self, request_id: str) -> None:
        """Commit a previously checked request; idempotent by request_id."""
        now = self._now()
        with self._lock:
            self._prune(now)
            _commit_common(
                request_id=request_id,
                now=now,
                exists_committed=lambda rid: rid in self._committed,
                get_pending=lambda rid: self._pending.get(rid),
                add_committed=lambda rid, a, t, c, ts: self._committed.__setitem__(
                    rid, (a, t, c, ts)
                ),
                delete_pending=lambda rid: self._pending.__delitem__(rid),
                spend_counter=self.spend_counter,
                on_spend=lambda c: setattr(self, "total_spend", self.total_spend + c),
            )

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
        for _, (agent, tool, cost, ts) in self._pending.items():
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
        budget_key: str | None = None,
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
        self.budget_key = budget_key
        self.window_seconds = window_seconds
        self.window = timedelta(seconds=window_seconds)
        self.spend_counter = spend_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._init_db()

    def check(self, request_id: str, agent: str, tool: str, cost: int) -> BudgetCheckResult:
        _validate_cost(cost)
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._prune_with_conn(conn, now)
            def _add_pending(rid: str, a: str, t: str, c: int, ts: datetime) -> None:
                conn.execute(
                    "INSERT INTO pending (request_id, agent, tool, cost, checked_at) VALUES (?, ?, ?, ?, ?)",
                    (rid, a, t, c, ts.isoformat()),
                )
            result = _check_common(
                request_id=request_id,
                agent=agent,
                tool=tool,
                cost=cost,
                now=now,
                exists_committed=lambda rid: self._exists_committed(conn, rid),
                exists_pending=lambda rid: self._exists_pending(conn, rid),
                usage=lambda key_type, key_value: self._usage(
                    conn, now, key=key_type, value=key_value
                ),
                add_pending=_add_pending,
                agent_limit=self.agent_limit,
                tool_limit=self.tool_limit,
            )
            conn.commit()
            return result

    def commit(self, request_id: str) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._prune_with_conn(conn, now)
            def _add_committed(rid: str, a: str, t: str, c: int, ts: datetime) -> None:
                conn.execute(
                    "INSERT INTO committed (request_id, agent, tool, cost, committed_at) VALUES (?, ?, ?, ?, ?)",
                    (rid, a, t, c, ts.isoformat()),
                )

            def _delete_pending(rid: str) -> None:
                conn.execute(
                    "DELETE FROM pending WHERE request_id = ?",
                    (rid,),
                )
            def _get_pending(rid: str) -> Tuple[str, str, int, datetime] | None:
                row = conn.execute(
                    "SELECT agent, tool, cost, checked_at FROM pending WHERE request_id = ?",
                    (rid,),
                ).fetchone()
                if row is None:
                    return None
                agent, tool, cost, checked_at = row
                if not isinstance(checked_at, str):
                    raise BudgetStateError("pending checked_at invalid")
                return agent, tool, int(cost), datetime.fromisoformat(checked_at)

            _commit_common(
                request_id=request_id,
                now=now,
                exists_committed=lambda rid: self._exists_committed(conn, rid),
                get_pending=_get_pending,
                add_committed=_add_committed,
                delete_pending=_delete_pending,
                spend_counter=self.spend_counter,
                on_spend=lambda c: None,
            )
            conn.commit()

    # ----- internal helpers -----

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        _ensure_wal_mode(self.path)
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_wal_mode(self.path)
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

    def _exists_pending(self, conn: sqlite3.Connection, request_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM pending WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return row is not None

    def _exists_committed(self, conn: sqlite3.Connection, request_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM committed WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return row is not None

    def _usage(self, conn: sqlite3.Connection, now: datetime, *, key: str, value: str) -> int:
        if key not in {"agent", "tool"}:
            raise BudgetStateError("invalid usage key")
        cutoff = (now - self.window).isoformat()
        total = 0
        row = conn.execute(
            f"SELECT COALESCE(SUM(cost), 0) FROM committed WHERE {key} = ? AND committed_at >= ?",
            (value, cutoff),
        ).fetchone()
        if row and row[0] is not None:
            total += int(row[0])
        row = conn.execute(
            f"SELECT COALESCE(SUM(cost), 0) FROM pending WHERE {key} = ? AND checked_at >= ?",
            (value, cutoff),
        ).fetchone()
        if row and row[0] is not None:
            total += int(row[0])
        return total

    def _prune(self, now: datetime) -> None:
        with self._connect() as conn:
            self._prune_with_conn(conn, now)
            conn.commit()

    def _prune_with_conn(self, conn: sqlite3.Connection, now: datetime) -> None:
        cutoff = (now - self.window).isoformat()
        conn.execute("DELETE FROM committed WHERE committed_at < ?", (cutoff,))
        stale_cutoff = (now - self.window * 2).isoformat()
        conn.execute("DELETE FROM pending WHERE checked_at < ?", (stale_cutoff,))


def persistent_budget(
    path: str | Path,
    *,
    agent_limit: int | None,
    tool_limit: int | None,
    window_seconds: int = 60,
    budget_key: str | None = None,
    spend_counter: bool = False,
    now: Callable[[], datetime] | None = None,
) -> SQLiteBudgetManager:
    """Helper to create a durable budget manager (SQLite)."""
    return SQLiteBudgetManager(
        path,
        agent_limit=agent_limit,
        tool_limit=tool_limit,
        window_seconds=window_seconds,
        budget_key=budget_key,
        spend_counter=spend_counter,
        now=now,
    )


# Thread-safe WAL initialization cache
_WAL_INITIALIZED: dict[Path, bool] = {}
_WAL_LOCK = threading.Lock()


def _ensure_wal_mode(path: Path) -> None:
    """Ensure WAL mode is set exactly once per database file. Thread-safe."""
    with _WAL_LOCK:
        if path in _WAL_INITIALIZED:
            return
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            _WAL_INITIALIZED[path] = True
        finally:
            conn.close()
