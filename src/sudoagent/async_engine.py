"""Async execution engine for SudoAgent.

Native async engine for SaaS environments where approval waits must not hold threads.
The event loop yields control during approval waits, enabling high concurrency.

Design notes:
- Accepts only async protocol implementations (use adapters for sync)
- Approval waits are event-loop-native (no thread holding)
- Fail-closed: decision must be logged before execution
- Outcome logging is best-effort (does not block on failure)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Literal, Mapping, ParamSpec, TypeVar, cast
from uuid import uuid4

from .budgets import BudgetExceeded, BudgetStateError
from .errors import ApprovalDenied, ApprovalError, AuditLogError, PolicyError
from .ledger.jcs import sha256_hex
from .ledger.types import JSONValue
from .ledger.versioning import LEDGER_VERSION, SCHEMA_VERSION
from .policies import Policy, PolicyResult
from .protocols import (
    AsyncApprovalStore,
    AsyncApprover,
    AsyncAuditLogger,
    AsyncBudgetManager,
    AsyncLedger,
)
from .redaction import redact_args, redact_kwargs
from .reason_codes import (
    APPROVAL_DENIED,
    APPROVAL_PROCESS_FAILED,
    BUDGET_EVALUATION_FAILED,
    BUDGET_EXCEEDED_AGENT_RATE,
    BUDGET_EXCEEDED_TOOL_RATE,
    POLICY_ALLOW_LOW_RISK,
    POLICY_DENY_HIGH_RISK,
    POLICY_EVALUATION_FAILED,
    POLICY_REQUIRE_APPROVAL_HIGH_VALUE,
)
from .types import (
    AuditEntry,
    ApprovalRecord,
    BudgetRecord,
    Context,
    Decision,
    LedgerDecisionEntry,
    LedgerOutcomeEntry,
)

# Named constants
DEFAULT_MAX_ERROR_LENGTH: int = 200
DEFAULT_APPROVAL_TTL_SECONDS: int = 300  # 5 minutes
DEFAULT_BUDGET_WINDOW_SECONDS: int = 3600  # 1 hour

_logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _format_timestamp(value: datetime) -> str:
    """Format datetime as ISO 8601 with microseconds and Z suffix."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _safe_error_for_ledger(
    exc: BaseException, *, include_message: bool, max_length: int
) -> dict[str, str]:
    """Create safe error dict for ledger entry. No stacktraces or paths."""
    error_type = type(exc).__name__
    raw_msg = str(exc) if include_message else error_type

    # Strip file paths (common patterns: /path/to/file.py, C:\path\to\file.py)
    if "/" in raw_msg or "\\" in raw_msg:
        raw_msg = error_type

    if len(raw_msg) > max_length:
        raw_msg = raw_msg[:max_length - 3] + "..."

    return {"error": raw_msg, "error_type": error_type, "error_message": raw_msg}


def _policy_source_hash(policy: Policy) -> str | None:
    """Try to derive a stable source hash for policy logic."""
    try:
        source = inspect.getsource(policy.evaluate)
    except (OSError, TypeError):
        return None
    return sha256_hex({"policy_source": source})


_DEFAULT_REASON_CODES: dict[Decision, str] = {
    Decision.ALLOW: POLICY_ALLOW_LOW_RISK,
    Decision.DENY: POLICY_DENY_HIGH_RISK,
    Decision.REQUIRE_APPROVAL: POLICY_REQUIRE_APPROVAL_HIGH_VALUE,
}


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """Immutable snapshot of execution state for a single guarded call.

    All fields needed for decision/outcome logging are captured upfront.
    This prevents parameter drilling and ensures consistency.
    """

    request_id: str
    action: str
    safe_args: tuple[JSONValue, ...]
    safe_kwargs: dict[str, JSONValue]
    ctx: Context
    policy_id: str
    policy_version: str | None
    policy_hash: str
    decision_time: datetime
    decision_hash: str
    agent_id: str
    budget_cost: int
    budget_requested: bool
    approval_ttl_seconds: int


class AsyncSudoEngine:
    """Async execution engine for guarding function calls.

    This engine accepts only async protocol implementations.
    Use adapters from sudoagent.adapters.sync_to_async to wrap sync implementations.

    Example:
        from sudoagent.adapters import SyncLedgerAdapter, SyncApproverAdapter

        sync_ledger = JSONLLedger(path)
        sync_approver = InteractiveApprover()

        engine = AsyncSudoEngine(
            policy=MyPolicy(),
            ledger=SyncLedgerAdapter(sync_ledger),
            approver=SyncApproverAdapter(sync_approver),  # WARNING: holds thread
            agent_id="my-agent",
        )

        result = await engine.execute(some_function, arg1, arg2)
    """

    __slots__ = (
        "_policy",
        "_approver",
        "_logger",
        "_ledger",
        "_budget_manager",
        "_approval_store",
        "_agent_id",
        "_on_error",
        "_error_count",
        "_include_error_messages",
        "_max_error_length",
    )

    def __init__(
        self,
        *,
        policy: Policy,
        approver: AsyncApprover,
        logger: AsyncAuditLogger,
        ledger: AsyncLedger,
        budget_manager: AsyncBudgetManager | None = None,
        approval_store: AsyncApprovalStore | None = None,
        agent_id: str,
        on_error: Callable[[str, Exception], None] | None = None,
        include_error_messages: bool = False,
        max_error_length: int = DEFAULT_MAX_ERROR_LENGTH,
    ) -> None:
        """Initialize async engine with async protocol implementations.

        Args:
            policy: Policy for decision evaluation (sync, deterministic)
            approver: Async approver for human-in-the-loop authorization
            logger: Async audit logger for operational records
            ledger: Async ledger for tamper-evident evidence
            budget_manager: Optional async budget manager for rate limiting
            approval_store: Optional async approval store for durable state
            agent_id: Identifier for this agent instance
            on_error: Optional callback(event_type, exception) for metrics
        """
        if policy is None:
            raise ValueError("policy is required")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id must be a non-empty string")

        self._policy = policy
        self._approver = approver
        self._logger = logger
        self._ledger = ledger
        self._budget_manager = budget_manager
        self._approval_store = approval_store
        self._agent_id = agent_id
        self._on_error = on_error
        self._error_count: int = 0
        self._include_error_messages = include_error_messages
        self._max_error_length = max_error_length

    @property
    def error_count(self) -> int:
        """Number of outcome logging errors since engine creation."""
        return self._error_count

    async def execute(
        self,
        func: Callable[..., R],
        /,
        *args: Any,
        policy_override: Policy | None = None,
        budget_cost: int | None = None,
        approval_ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> R:
        """Execute a guarded function call.

        Flow: policy -> (approval) -> budget -> decision log -> execute -> outcome log

        Args:
            func: Function to execute
            *args: Positional arguments for func
            policy_override: Optional policy to use instead of engine default
            budget_cost: Cost to charge for this execution (default: 1)
            approval_ttl_seconds: TTL for approval request (default: 300s)
            **kwargs: Keyword arguments for func

        Returns:
            Result of func(*args, **kwargs)

        Raises:
            ApprovalDenied: If policy denies or approval is rejected
            PolicyError: If policy evaluation fails
            ApprovalError: If approval process fails
            AuditLogError: If decision logging fails (fail-closed)
        """
        state = self._build_state(func, args, kwargs, policy_override, budget_cost, approval_ttl_seconds)
        effective_policy = policy_override or self._policy

        # Evaluate policy (sync, deterministic, no I/O)
        try:
            result, reason_code = self._evaluate_policy(effective_policy, state)
        except PolicyError as exc:
            # Log fail-closed decision, then re-raise
            await self._log_decision(
                state, Decision.DENY, "policy evaluation failed", POLICY_EVALUATION_FAILED,
                _safe_error_for_ledger(
                    exc.__cause__ if exc.__cause__ else exc,
                    include_message=self._include_error_messages,
                    max_length=self._max_error_length,
                )
            )
            raise

        if result.decision == Decision.ALLOW:
            return await self._execute_allowed(func, args, kwargs, state, result.reason, reason_code)

        if result.decision == Decision.DENY:
            await self._log_decision(state, Decision.DENY, result.reason, reason_code)
            raise ApprovalDenied(result.reason)

        if result.decision == Decision.REQUIRE_APPROVAL:
            return await self._execute_with_approval(
                func, args, kwargs, state, result, reason_code
            )

        # Unknown decision type - fail closed
        await self._log_decision(state, Decision.DENY, "unknown decision type", POLICY_EVALUATION_FAILED)
        raise PolicyError(f"Unknown decision: {result.decision}")

    def _build_state(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        policy_override: Policy | None,
        budget_cost: int | None,
        approval_ttl_seconds: int | None = None,
    ) -> ExecutionState:
        """Build immutable execution state from call parameters."""
        request_id = str(uuid4())
        action = f"{func.__module__}.{func.__qualname__}"
        safe_args = tuple(redact_args(args))
        safe_kwargs = redact_kwargs(kwargs)

        effective_policy = policy_override or self._policy
        policy_id = self._get_policy_id(effective_policy)
        policy_version = getattr(effective_policy, "version", None)
        
        # Enhanced policy hash includes version + source when available
        explicit_hash = getattr(effective_policy, "policy_hash", None)
        if isinstance(explicit_hash, str) and explicit_hash.strip():
            policy_hash = explicit_hash
        else:
            source_hash = _policy_source_hash(effective_policy)
            policy_hash = sha256_hex({
                "policy_id": policy_id,
                "policy_version": policy_version,
                "policy_class": effective_policy.__class__.__qualname__,
                "policy_source_hash": source_hash,
            })

        decision_time = datetime.now(timezone.utc)
        decision_hash = sha256_hex({
            "version": "2.0",
            "request_id": request_id,
            "decision_at": _format_timestamp(decision_time),
            "policy_hash": policy_hash,
            "intent": action,
            "resource": {"type": "function", "name": action},
            "parameters": {"args": list(safe_args), "kwargs": safe_kwargs},
            "actor": {"principal": self._agent_id, "source": "python"},
        })

        ctx = Context(
            action=action,
            args=safe_args,
            kwargs=safe_kwargs,
            metadata={"agent_id": self._agent_id, "_redacted": True},
        )

        return ExecutionState(
            request_id=request_id,
            action=action,
            safe_args=safe_args,
            safe_kwargs=safe_kwargs,
            ctx=ctx,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_hash=policy_hash,
            decision_time=decision_time,
            decision_hash=decision_hash,
            agent_id=self._agent_id,
            budget_cost=budget_cost if budget_cost is not None else 1,
            budget_requested=budget_cost is not None,
            approval_ttl_seconds=approval_ttl_seconds if approval_ttl_seconds is not None else DEFAULT_APPROVAL_TTL_SECONDS,
        )

    def _evaluate_policy(
        self, policy: Policy, state: ExecutionState
    ) -> tuple[PolicyResult, str | None]:
        """Evaluate policy synchronously. No I/O, must be deterministic."""
        try:
            result = policy.evaluate(state.ctx)
        except Exception as exc:
            raise PolicyError("Policy evaluation failed") from exc

        reason_code = getattr(result, "reason_code", None) or _DEFAULT_REASON_CODES.get(result.decision)
        return result, reason_code

    async def _execute_allowed(
        self,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        state: ExecutionState,
        reason: str,
        reason_code: str | None,
        approval_metadata: dict[str, Any] | None = None,
        approval_record: dict[str, Any] | None = None,
    ) -> R:
        """Execute an allowed function call with budget and logging."""
        # Budget check/commit (fail-closed)
        if self._budget_manager is not None:
            try:
                await self._budget_manager.check(
                    state.request_id, state.agent_id, state.action, state.budget_cost
                )
                await self._budget_manager.commit(state.request_id)
            except BudgetExceeded as exc:
                scope = getattr(exc, "scope", None)
                if scope == "agent":
                    reason_code = BUDGET_EXCEEDED_AGENT_RATE
                elif scope == "tool":
                    reason_code = BUDGET_EXCEEDED_TOOL_RATE
                else:
                    reason_code = BUDGET_EVALUATION_FAILED
                await self._log_decision(
                    state,
                    Decision.DENY,
                    "budget exceeded",
                    reason_code,
                    budget_checked=True,
                )
                raise ApprovalDenied("budget exceeded") from exc
            except BudgetStateError as exc:
                await self._log_decision(
                    state,
                    Decision.DENY,
                    "budget evaluation failed",
                    BUDGET_EVALUATION_FAILED,
                    budget_checked=True,
                )
                raise ApprovalDenied("budget evaluation failed") from exc

        # Log decision (fail-closed)
        # Pass approval_metadata as approval_info if it contains approval data
        await self._log_decision(
            state,
            Decision.ALLOW,
            reason,
            reason_code,
            approval_metadata,
            budget_checked=(self._budget_manager is not None),
            approval_info=approval_metadata if approval_metadata and approval_metadata.get("approved") is not None else None,
            approval_record=approval_record,
        )

        # Execute function
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            await self._log_outcome(state, reason, reason_code, "error", exc)
            raise

        # Log outcome (best-effort)
        await self._log_outcome(state, reason, reason_code, "success", None)
        return result

    async def _execute_with_approval(
        self,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        state: ExecutionState,
        policy_result: PolicyResult,
        reason_code: str | None,
    ) -> R:
        """Execute a function that requires approval."""
        # Calculate expiration time from state TTL (cap to store max if available)
        ttl_seconds = state.approval_ttl_seconds
        if self._approval_store is not None:
            max_ttl = getattr(self._approval_store, "max_ttl_seconds", None)
            if isinstance(max_ttl, int):
                ttl_seconds = min(ttl_seconds, max_ttl)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        
        # Persist pending state BEFORE yielding to external approval
        if self._approval_store is not None:
            await self._approval_store.expire_expired()
            await self._approval_store.create_pending(
                request_id=state.request_id,
                policy_hash=state.policy_hash,
                decision_hash=state.decision_hash,
                expires_at=expires_at,
            )

        # Await approval (event-loop-native, no thread holding)
        try:
            approval_response = await asyncio.wait_for(
                self._approver.approve(state.ctx, policy_result, state.request_id),
                timeout=ttl_seconds,
            )
        except asyncio.TimeoutError:
            if self._approval_store is not None:
                await self._approval_store.resolve(
                    request_id=state.request_id,
                    state="expired",
                    approver_id=None,
                )
                approval_record = await self._approval_store.fetch(state.request_id)
            else:
                approval_record = None
            await self._log_decision(
                state,
                Decision.DENY,
                "approval expired",
                APPROVAL_PROCESS_FAILED,
                {"approved": False, "policy_decision": "require_approval"},
                approval_info={"approved": False, "state": "expired", "policy_decision": "require_approval"},
                approval_record=approval_record,
            )
            raise ApprovalDenied("approval expired")
        except Exception as exc:
            if self._approval_store is not None:
                await self._approval_store.resolve(
                    request_id=state.request_id,
                    state="failed",
                    approver_id=None,
                )
            await self._log_decision(
                state,
                Decision.DENY,
                "approval process failed",
                APPROVAL_PROCESS_FAILED,
                _safe_error_for_ledger(
                    exc, include_message=self._include_error_messages, max_length=self._max_error_length
                ),
                approval_info={"approved": False, "state": "failed", "policy_decision": "require_approval"},
            )
            raise ApprovalError("Approval process failed") from exc

        # Parse approval response
        approved, binding, approver_id = self._parse_approval_response(
            approval_response,
            expected={
                "request_id": state.request_id,
                "policy_hash": state.policy_hash,
                "decision_hash": state.decision_hash,
            },
        )

        if not approved:
            if self._approval_store is not None:
                await self._approval_store.resolve(
                    request_id=state.request_id,
                    state="denied",
                    approver_id=approver_id,
                )
                approval_record = await self._approval_store.fetch(state.request_id)
            else:
                approval_record = None
            await self._log_decision(
                state,
                Decision.DENY,
                policy_result.reason,
                APPROVAL_DENIED,
                {"approved": False, "policy_decision": "require_approval", "approval_binding": binding},
                approval_info={
                    "approved": False,
                    "state": "denied",
                    "approver_id": approver_id,
                    "approval_binding": binding,
                    "policy_decision": "require_approval",
                },
                approval_record=approval_record,
            )
            raise ApprovalDenied(policy_result.reason)

        # Approval granted
        if self._approval_store is not None:
            await self._approval_store.resolve(
                request_id=state.request_id,
                state="approved",
                approver_id=approver_id,
            )
            approval_record = await self._approval_store.fetch(state.request_id)
        else:
            approval_record = None

        return await self._execute_allowed(
            func, args, kwargs, state, policy_result.reason, reason_code,
            approval_metadata={
                "approval_binding": binding,
                "approved": True,
                "approver_id": approver_id,
                "policy_decision": "require_approval",
            },
            approval_record=approval_record,
        )

    async def _log_decision(
        self,
        state: ExecutionState,
        decision: Decision,
        reason: str,
        reason_code: str | None,
        extra_metadata: dict[str, Any] | None = None,
        budget_checked: bool = False,
        approval_info: dict[str, Any] | None = None,
        approval_record: dict[str, Any] | None = None,
    ) -> None:
        """Log decision to ledger and audit log. Fail-closed on error."""
        # Backwards-compatible metadata (includes args/kwargs for existing tests/tools)
        ledger_metadata: dict[str, Any] = {}
        if extra_metadata:
            ledger_metadata.update(extra_metadata)
        if reason_code:
            ledger_metadata["reason_code"] = reason_code

        audit_metadata: dict[str, Any] = {
            "args": list(state.safe_args),
            "kwargs": state.safe_kwargs,
        }
        audit_metadata.update(ledger_metadata)

        # Explicit budget block with full audit info
        budget_block: dict[str, Any] | None = None
        if budget_checked or state.budget_requested:
            window_seconds = None
            if self._budget_manager is not None:
                if hasattr(self._budget_manager, "window_seconds"):
                    window_seconds = getattr(self._budget_manager, "window_seconds")
                else:
                    window = getattr(self._budget_manager, "window", None)
                    if window is not None and hasattr(window, "total_seconds"):
                        window_seconds = int(window.total_seconds())

            budget_block = {
                "budget_key": getattr(self._budget_manager, "budget_key", None)
                if self._budget_manager is not None
                else None,
                "agent_id": state.agent_id,
                "action": state.action,
                "cost": state.budget_cost,
                "window_seconds": window_seconds or DEFAULT_BUDGET_WINDOW_SECONDS,
                "checked": bool(budget_checked),
            }

        # Structured approval block with id/state/timestamps
        approval_block: dict[str, Any] | None = None
        if approval_info is not None or approval_record is not None:
            approval_id = None
            if approval_record is not None:
                approval_id = approval_record.get("approval_id") or approval_record.get("request_id")
            if approval_id is None and approval_info is not None:
                approval_id = approval_info.get("approval_id")
            if approval_id is None and approval_info is not None:
                approval_id = state.request_id
            approval_block = {
                "approval_id": approval_id,
                "approver_id": (approval_record.get("approver_id") if approval_record else None)
                or (approval_info.get("approver_id") if approval_info else None),
                "state": approval_record.get("state") if approval_record else (
                    approval_info.get("state") if approval_info and approval_info.get("state") else
                    ("approved" if approval_info and approval_info.get("approved") else "denied")
                ),
                "created_at": approval_record.get("created_at") if approval_record else None,
                "resolved_at": approval_record.get("resolved_at") if approval_record else None,
                "expires_at": approval_record.get("expires_at") if approval_record else None,
                "binding": approval_info.get("approval_binding") if approval_info else None,
            }

        approval_typed: ApprovalRecord | None = (
            cast(ApprovalRecord, approval_block) if approval_block is not None else None
        )
        budget_typed: BudgetRecord | None = (
            cast(BudgetRecord, budget_block) if budget_block is not None else None
        )

        entry: LedgerDecisionEntry = {
            "schema_version": SCHEMA_VERSION,
            "ledger_version": LEDGER_VERSION,
            "prev_entry_hash": None,
            "entry_hash": None,
            "request_id": state.request_id,
            "created_at": _format_timestamp(state.decision_time),
            "event": "decision",
            "action": state.action,
            "agent_id": state.agent_id,
            "decision": {
                "effect": decision.value,
                "reason": reason,
                "reason_code": reason_code,
                "policy_id": state.policy_id,
                "policy_version": state.policy_version,
                "policy_hash": state.policy_hash,
                "decision_hash": state.decision_hash,
            },
            "approval": approval_typed,
            "budget": budget_typed,
            "parameters": {"args": list(state.safe_args), "kwargs": state.safe_kwargs},
            "metadata": ledger_metadata,
        }

        try:
            await self._ledger.append(entry)
        except Exception as exc:
            raise AuditLogError("Failed to write audit log") from exc

        try:
            await self._logger.log(AuditEntry(
                timestamp=state.decision_time,
                request_id=state.request_id,
                event="decision",
                action=state.action,
                decision=decision,
                reason=reason,
                metadata=audit_metadata,
            ))
        except Exception as exc:
            raise AuditLogError("Failed to write audit log") from exc

    async def _log_outcome(
        self,
        state: ExecutionState,
        reason: str,
        reason_code: str | None,
        outcome: Literal["success", "error"],
        error: Exception | None,
    ) -> None:
        """Log outcome to ledger and audit log. Best-effort with logging hook."""
        error_msg: str | None = None
        error_type: str | None = None
        if error is not None:
            safe_error = _safe_error_for_ledger(
                error, include_message=self._include_error_messages, max_length=self._max_error_length
            )
            error_msg = safe_error.get("error")
            error_type = safe_error.get("error_type")

        entry: LedgerOutcomeEntry = {
            "schema_version": SCHEMA_VERSION,
            "ledger_version": LEDGER_VERSION,
            "prev_entry_hash": None,
            "entry_hash": None,
            "request_id": state.request_id,
            "created_at": _format_timestamp(datetime.now(timezone.utc)),
            "event": "outcome",
            "action": state.action,
            "agent_id": state.agent_id,
            "decision": {
                "decision_hash": state.decision_hash,
                "policy_id": state.policy_id,
                "policy_version": state.policy_version,
                "policy_hash": state.policy_hash,
                "reason": reason,
                "reason_code": reason_code,
            },
            "outcome": {
                "status": outcome,
                "reason": reason,
                "reason_code": reason_code,
                "error_type": error_type,
                "error": error_msg,
            },
            "parameters": {"args": list(state.safe_args), "kwargs": state.safe_kwargs},
            # No metadata duplication - parameters already contains args/kwargs
        }

        try:
            await self._ledger.append(entry)
        except Exception as exc:
            self._error_count += 1
            _logger.warning("Failed to write outcome to ledger: %s", exc)
            if self._on_error is not None:
                try:
                    self._on_error("outcome_ledger_write", exc)
                except Exception:
                    pass  # Hook failure shouldn't cascade

        try:
            await self._logger.log(AuditEntry(
                timestamp=datetime.now(timezone.utc),
                request_id=state.request_id,
                event="outcome",
                action=state.action,
                decision=Decision.ALLOW,
                reason=reason,
                outcome=outcome,
                error_type=error_type,
                error=error_msg,
                metadata={},
            ))
        except Exception as exc:
            self._error_count += 1
            _logger.warning("Failed to write outcome to audit log: %s", exc)
            if self._on_error is not None:
                try:
                    self._on_error("outcome_audit_write", exc)
                except Exception:
                    pass  # Hook failure shouldn't cascade

    def _parse_approval_response(
        self,
        response: object,
        expected: Mapping[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        """Parse approval response into (approved, binding, approver_id).
        
        Handles 4 response types:
        1. bool -> Quick approve/deny, use expected binding
        2. Non-Mapping -> Reject as malformed
        3. Mapping without binding -> Use expected, check 'approved' key
        4. Mapping with binding -> Verify binding matches expected
        
        Security: Binding mismatch = automatic rejection (replay protection).
        """
        # Default: use expected binding, no approver
        binding: dict[str, str] = dict(expected)
        approver_id: str | None = None

        # Case 1: Simple bool response
        if isinstance(response, bool):
            return response, binding, approver_id

        # Case 2: Non-Mapping is malformed -> reject
        if not isinstance(response, Mapping):
            return False, binding, approver_id

        # Extract approver_id if present
        raw_approver = response.get("approver_id")
        if isinstance(raw_approver, str) and raw_approver.strip():
            approver_id = raw_approver

        # Extract binding if provided (Case 4)
        raw_binding = response.get("binding")
        if isinstance(raw_binding, Mapping):
            binding = {k: str(v) for k, v in raw_binding.items()}

        # Determine approval: explicit 'approved' key, or implicit from binding presence
        approved = bool(response.get("approved", raw_binding is not None))

        # SECURITY: Binding mismatch = automatic rejection
        if binding != dict(expected):
            approved = False

        return approved, binding, approver_id

    def _get_policy_id(self, policy: Policy) -> str:
        """Extract policy identifier from policy object."""
        candidate = getattr(policy, "policy_id", None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        return f"{policy.__class__.__module__}.{policy.__class__.__qualname__}"

    def guard(
        self, *, policy: Policy | None = None, budget_cost: int | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to guard an async function.

        Usage:
            @engine.guard()
            async def my_function(x: int) -> int:
                return x * 2
        """
        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return await self.execute(
                    func,
                    *args,
                    policy_override=policy,
                    budget_cost=budget_cost,
                    **cast(dict[str, Any], kwargs),
                )
            return wrapper  # type: ignore[return-value]
        return decorator
