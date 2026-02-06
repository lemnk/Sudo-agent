"""Execution engine for SudoAgent.

Synchronous wrapper around AsyncSudoEngine. This is the recommended API for:
- Simple scripts and CLI tools
- Synchronous codebases

For async contexts (FastAPI, aiohttp, etc.), use AsyncSudoEngine directly.
"""

from __future__ import annotations

import asyncio
import os
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, ParamSpec, TypeVar, cast

from .adapters.sync_to_async import (
    SyncApprovalStoreAdapter,
    SyncApproverAdapter,
    SyncAuditLoggerAdapter,
    SyncBudgetManagerAdapter,
    SyncLedgerAdapter,
)
from .async_engine import DEFAULT_MAX_ERROR_LENGTH
from .approvals_store import ApprovalStore
from .async_engine import AsyncSudoEngine
from .async_utils import run_sync
from .budgets import BudgetManager
from .ledger.base import Ledger
from .ledger.jsonl import JSONLLedger
from .loggers.base import AuditLogger
from .loggers.jsonl import JsonlAuditLogger
from .notifiers.base import Approver
from .notifiers.interactive import InteractiveApprover
from .policies import Policy

P = ParamSpec("P")
R = TypeVar("R")


class SudoEngine:
    """Synchronous execution engine for guarding function calls.

    This is a thin wrapper around AsyncSudoEngine that provides a synchronous API.
    Internally, all operations are async - this wrapper uses a shared background
    loop by default (run_sync), or an isolated asyncio.run() per call.

    For async contexts (FastAPI, aiohttp, Jupyter), use AsyncSudoEngine directly
    to avoid the overhead and potential issues with nested event loops.

    Example:
        from sudoagent import SudoEngine, AllowAllPolicy

        engine = SudoEngine(policy=AllowAllPolicy(), agent_id="my-agent")
        result = engine.execute(some_function, arg1, arg2)
    """

    __slots__ = (
        "_async_engine",
        "policy",
        "approver",
        "logger",
        "ledger",
        "budget_manager",
        "approval_store",
        "agent_id",
        "_run_sync_mode",
    )

    def __init__(
        self,
        *,
        policy: Policy,
        approver: Approver | None = None,
        logger: AuditLogger | None = None,
        ledger: Ledger | None = None,
        budget_manager: BudgetManager | None = None,
        approval_store: ApprovalStore | None = None,
        agent_id: str,
        include_error_messages: bool = False,
        max_error_length: int = DEFAULT_MAX_ERROR_LENGTH,
        run_sync_mode: Literal["background", "isolated"] = "isolated",
    ) -> None:
        """Initialize the synchronous engine.

        Args:
            policy: Policy for decision evaluation
            approver: Approver for human-in-the-loop authorization
            logger: Audit logger for operational records
            ledger: Ledger for tamper-evident evidence (default: JSONLLedger("sudo_ledger.jsonl"))
            budget_manager: Optional budget manager for rate limiting
            approval_store: Optional approval store for durable state
            agent_id: Identifier for this agent instance (required)
            max_error_length: Max length for stored error messages when include_error_messages is enabled
            run_sync_mode: "isolated" (default) or "background" shared loop
        """
        if policy is None:
            raise ValueError(
                "policy is required (pass AllowAllPolicy() explicitly if you want permissive mode)"
            )
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id must be a non-empty string")

        # Store references for backwards compatibility
        self.policy = policy
        self.approver = approver if approver is not None else InteractiveApprover()
        self.logger = logger if logger is not None else JsonlAuditLogger()
        if ledger is None:
            env_path = os.environ.get("SUDOAGENT_LEDGER_PATH")
            if env_path:
                ledger = JSONLLedger(Path(env_path))
            else:
                ledger = JSONLLedger(Path("sudo_ledger.jsonl"))
        self.ledger = ledger
        self.budget_manager = budget_manager
        self.approval_store = approval_store
        self.agent_id = agent_id
        self._run_sync_mode = run_sync_mode

        # Wrap sync implementations with async adapters
        async_approver = SyncApproverAdapter(self.approver)
        async_logger = SyncAuditLoggerAdapter(self.logger)
        async_ledger = SyncLedgerAdapter(self.ledger)
        async_budget = SyncBudgetManagerAdapter(self.budget_manager) if self.budget_manager else None
        async_store = SyncApprovalStoreAdapter(self.approval_store) if self.approval_store else None

        # Create the async engine that does the real work
        self._async_engine = AsyncSudoEngine(
            policy=self.policy,
            approver=async_approver,
            logger=async_logger,
            ledger=async_ledger,
            budget_manager=async_budget,
            approval_store=async_store,
            agent_id=self.agent_id,
            include_error_messages=include_error_messages,
            max_error_length=max_error_length,
        )

    def execute(
        self,
        func: Callable[..., R],
        /,
        *args: Any,
        policy_override: Policy | None = None,
        budget_cost: int | None = None,
        **kwargs: Any,
    ) -> R:
        """Execute a guarded function call synchronously.

        Flow: policy -> (approval) -> budget -> decision log -> execute -> outcome log

        Args:
            func: Function to execute
            *args: Positional arguments for func
            policy_override: Optional policy to use instead of engine default
            budget_cost: Cost to charge for this execution (default: 1)
            **kwargs: Keyword arguments for func

        Returns:
            Result of func(*args, **kwargs)

        Raises:
            ApprovalDenied: If policy denies or approval is rejected
            PolicyError: If policy evaluation fails
            ApprovalError: If approval process fails
            AuditLogError: If decision logging fails (fail-closed)
            RuntimeError: If called from within an async event loop
        """
        # Check if we're already in an event loop
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "SudoEngine.execute() cannot be called from within an async event loop. "
                "Use AsyncSudoEngine instead: await engine.execute(...)"
            )

        # Execute the async engine synchronously
        if self._run_sync_mode == "isolated":
            return asyncio.run(
                self._async_engine.execute(
                    func,
                    *args,
                    policy_override=policy_override,
                    budget_cost=budget_cost,
                    **kwargs,
                )
            )
        return run_sync(
            self._async_engine.execute(
                func,
                *args,
                policy_override=policy_override,
                budget_cost=budget_cost,
                **kwargs,
            )
        )

    def guard(
        self, *, policy: Policy | None = None, budget_cost: int | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to guard a function.

        Usage:
            @engine.guard()
            def my_function(x: int) -> int:
                return x * 2
        """
        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return self.execute(
                    func, *args, policy_override=policy, budget_cost=budget_cost, **kwargs
                )
            return cast(Callable[P, R], wrapper)
        return decorator

    @classmethod
    def from_env(
        cls,
        *,
        policy: Policy,
        agent_id: str,
        approver: Approver | None = None,
        logger: AuditLogger | None = None,
        budget_manager: BudgetManager | None = None,
        approval_store: ApprovalStore | None = None,
        run_sync_mode: Literal["background", "isolated"] = "isolated",
        include_error_messages: bool = False,
        max_error_length: int = DEFAULT_MAX_ERROR_LENGTH,
    ) -> "SudoEngine":
        """Create a SudoEngine using SUDOAGENT_LEDGER_PATH for the ledger."""
        env_path = os.environ.get("SUDOAGENT_LEDGER_PATH")
        if not env_path:
            raise ValueError("SUDOAGENT_LEDGER_PATH is not set")
        ledger = JSONLLedger(Path(env_path))
        return cls(
            policy=policy,
            approver=approver,
            logger=logger,
            ledger=ledger,
            budget_manager=budget_manager,
            approval_store=approval_store,
            agent_id=agent_id,
            run_sync_mode=run_sync_mode,
            include_error_messages=include_error_messages,
            max_error_length=max_error_length,
        )
