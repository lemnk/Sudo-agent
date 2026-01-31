"""Execution engine for SudoAgent."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, ParamSpec, TypeVar
from uuid import uuid4

from .budgets import BudgetError, BudgetExceeded, BudgetManager
from .approvals_store import ApprovalStore
from .errors import ApprovalDenied, ApprovalError, AuditLogError, PolicyError
from .loggers.base import AuditLogger
from .loggers.jsonl import JsonlAuditLogger
from .ledger.jcs import sha256_hex
from .ledger.base import Ledger
from .ledger.jsonl import JSONLLedger
from .ledger.versioning import LEDGER_VERSION, SCHEMA_VERSION
from .notifiers.base import Approver
from .notifiers.interactive import InteractiveApprover
from .policies import Policy, PolicyResult
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
    Context,
    Decision,
    ApprovalRecord,
    LedgerDecisionEntry,
    LedgerOutcomeEntry,
)

P = ParamSpec("P")
R = TypeVar("R")



def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_DEFAULT_POLICY_REASON_CODES = {
    Decision.ALLOW: POLICY_ALLOW_LOW_RISK,
    Decision.DENY: POLICY_DENY_HIGH_RISK,
    Decision.REQUIRE_APPROVAL: POLICY_REQUIRE_APPROVAL_HIGH_VALUE,
}


class SudoEngine:
    """Runtime engine for guarding function calls with policy evaluation and approval."""

    def __init__(
        self,
        *,
        policy: Policy,
        approver: Approver | None = None,
        logger: AuditLogger | None = None,
        ledger: Ledger | None = None,
        budget_manager: BudgetManager | None = None,
        approval_store: ApprovalStore | None = None,
        agent_id: str = "unknown",
    ) -> None:
        if policy is None:
            raise ValueError(
                "policy is required (pass AllowAllPolicy() explicitly if you want permissive mode)"
            )
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id must be a non-empty string")
        self.policy = policy
        self.approver = approver if approver is not None else InteractiveApprover()
        self.logger = logger if logger is not None else JsonlAuditLogger()
        self.ledger = ledger if ledger is not None else JSONLLedger(Path("sudo_ledger.jsonl"))
        self.budget_manager = budget_manager
        self.approval_store = approval_store
        self.agent_id = agent_id

    def execute(
        self,
        func: Callable[..., R],
        /,
        *args: Any,
        policy_override: Policy | None = None,
        budget_cost: int | None = None,
        **kwargs: Any,
    ) -> R:
        """Orchestrate a guarded call: policy -> (maybe approval) -> budget -> decision log -> run -> outcome log."""
        request_id = str(uuid4())
        action = f"{func.__module__}.{func.__qualname__}"
        budget_cost = 1 if budget_cost is None else budget_cost

        ctx, safe_args, safe_kwargs = self._build_context(action, args, kwargs)
        policy_id, policy_hash = self._resolve_policy(policy_override)
        decision_time = datetime.now(timezone.utc)
        decision_time_text = _format_timestamp(decision_time)

        result, reason_code = self._evaluate_policy_safe(
            policy=policy_override or self.policy,
            ctx=ctx,
            request_id=request_id,
            action=action,
            policy_id=policy_id,
            policy_hash=policy_hash,
            safe_args=safe_args,
            safe_kwargs=safe_kwargs,
        )

        decision_hash = self._decision_hash(
            action=action,
            request_id=request_id,
            policy_hash=policy_hash,
            decision_time=decision_time_text,
            parameters={"args": safe_args, "kwargs": safe_kwargs},
        )

        if result.decision == Decision.ALLOW:
            return self._handle_allow(
                func=func,
                args=args,
                kwargs=kwargs,
                safe_args=safe_args,
                safe_kwargs=safe_kwargs,
                request_id=request_id,
                action=action,
                decision_reason=result.reason,
                reason_code=reason_code,
                policy_id=policy_id,
                policy_hash=policy_hash,
                decision_hash=decision_hash,
                decision_time=decision_time,
                budget_cost=budget_cost,
            )

        if result.decision == Decision.DENY:
            self._log_decision_strict(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason=result.reason,
                metadata={"args": safe_args, "kwargs": safe_kwargs},
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=self.agent_id,
                reason_code=reason_code,
                decision_time=decision_time,
            )
            raise ApprovalDenied(result.reason)

        if result.decision == Decision.REQUIRE_APPROVAL:
            return self._handle_require_approval(
                func=func,
                args=args,
                kwargs=kwargs,
                safe_args=safe_args,
                safe_kwargs=safe_kwargs,
                request_id=request_id,
                action=action,
                decision_reason=result.reason,
                reason_code=reason_code,
                policy_id=policy_id,
                policy_hash=policy_hash,
                decision_hash=decision_hash,
                decision_time=decision_time,
                budget_cost=budget_cost,
                policy_result=result,
            )

        self._log_decision_strict(
            request_id=request_id,
            action=action,
            decision=Decision.DENY,
            reason="unknown decision type",
            metadata={"policy_decision": getattr(result, "decision", "unknown")},
            policy_id=policy_id,
            policy_hash=policy_hash,
            agent_id=self.agent_id,
            reason_code=POLICY_EVALUATION_FAILED,
            decision_time=decision_time,
        )
        raise PolicyError(f"Unknown decision: {result.decision}")

    def _build_context(
        self, action: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[Context, list[str], dict[str, str]]:
        safe_args = redact_args(args)
        safe_kwargs = redact_kwargs(kwargs)
        ctx = Context(
            action=action,
            args=tuple(safe_args),
            kwargs=safe_kwargs,
            metadata={"agent_id": self.agent_id, "_redacted": True},
        )
        return ctx, safe_args, safe_kwargs

    def _resolve_policy(self, override: Policy | None) -> tuple[str, str]:
        effective = override or self.policy
        policy_id = self._policy_id(effective)
        policy_hash = self._policy_hash(policy_id)
        return policy_id, policy_hash

    def _evaluate_policy_safe(
        self,
        *,
        policy: Policy,
        ctx: Context,
        request_id: str,
        action: str,
        policy_id: str,
        policy_hash: str,
        safe_args: list[str],
        safe_kwargs: dict[str, str],
    ) -> tuple[Any, str | None]:
        try:
            result = policy.evaluate(ctx)
        except Exception as e:
            self._log_decision_strict(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="policy evaluation failed",
                metadata={"error": str(e), "args": safe_args, "kwargs": safe_kwargs},
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=self.agent_id,
                reason_code=POLICY_EVALUATION_FAILED,
                decision_time=datetime.now(timezone.utc),
            )
            raise PolicyError(f"Policy evaluation failed: {e}") from e

        reason_code = getattr(result, "reason_code", None) or _DEFAULT_POLICY_REASON_CODES.get(
            result.decision
        )
        return result, reason_code

    def _handle_allow(
        self,
        *,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        safe_args: list[str],
        safe_kwargs: dict[str, str],
        request_id: str,
        action: str,
        decision_reason: str,
        reason_code: str | None,
        policy_id: str,
        policy_hash: str,
        decision_hash: str,
        decision_time: datetime,
        budget_cost: int,
        decision_metadata: dict[str, Any] | None = None,
    ) -> R:
        self._budget_check(
            request_id=request_id,
            agent=self.agent_id,
            tool=action,
            cost=budget_cost,
            policy_id=policy_id,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            agent_id=self.agent_id,
            action=action,
            args=safe_args,
            kwargs=safe_kwargs,
        )
        self._budget_commit(
            request_id=request_id,
            agent=self.agent_id,
            tool=action,
            cost=budget_cost,
            policy_id=policy_id,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            agent_id=self.agent_id,
            action=action,
            args=safe_args,
            kwargs=safe_kwargs,
        )
        decision_hash = self._log_decision_strict(
            request_id=request_id,
            action=action,
            decision=Decision.ALLOW,
            reason=decision_reason,
            metadata={
                "args": safe_args,
                "kwargs": safe_kwargs,
                **(decision_metadata or {}),
            },
            policy_id=policy_id,
            policy_hash=policy_hash,
            agent_id=self.agent_id,
            reason_code=reason_code,
            decision_hash=decision_hash,
            decision_time=decision_time,
        )
        return self._execute_and_log_outcome(
            func=func,
            args=args,
            kwargs=kwargs,
            safe_args=safe_args,
            safe_kwargs=safe_kwargs,
            request_id=request_id,
            action=action,
            reason=decision_reason,
            reason_code=reason_code,
            policy_id=policy_id,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            agent_id=self.agent_id,
        )

    def _handle_require_approval(
        self,
        *,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        safe_args: list[str],
        safe_kwargs: dict[str, str],
        request_id: str,
        action: str,
        decision_reason: str,
        reason_code: str | None,
        policy_id: str,
        policy_hash: str,
        decision_hash: str,
        decision_time: datetime,
        budget_cost: int,
        policy_result: PolicyResult,
    ) -> R:
        if self.approval_store is not None:
            self.approval_store.create_pending(
                request_id=request_id,
                policy_hash=policy_hash,
                decision_hash=decision_hash,
                expires_at=None,
            )
        try:
            ctx = Context(
                action=action,
                args=tuple(safe_args),
                kwargs=safe_kwargs,
                metadata={"agent_id": self.agent_id, "_redacted": True},
            )
            approval_response = self.approver.approve(
                ctx,
                policy_result,
                request_id,
            )
            approved, binding, approver_id = self._parse_approval_response(
                approval_response,
                expected={
                    "request_id": request_id,
                    "policy_hash": policy_hash,
                    "decision_hash": decision_hash,
                },
            )
        except Exception as e:
            if self.approval_store is not None:
                self.approval_store.resolve(
                    request_id=request_id, state="failed", approver_id=None
                )
            self._log_decision_strict(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="approval process failed",
                metadata={
                    "error": str(e),
                    "policy_decision": "require_approval",
                    "args": safe_args,
                    "kwargs": safe_kwargs,
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=self.agent_id,
                reason_code=APPROVAL_PROCESS_FAILED,
                decision_time=decision_time,
            )
            raise ApprovalError(f"Approval process failed: {e}") from e

        if not approved:
            if self.approval_store is not None:
                self.approval_store.resolve(
                    request_id=request_id, state="denied", approver_id=approver_id
                )
            self._log_decision_strict(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason=decision_reason,
                metadata={
                    "approval_binding": binding,
                    "approved": approved,
                    "args": safe_args,
                    "kwargs": safe_kwargs,
                    "policy_decision": "require_approval",
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=self.agent_id,
                reason_code=APPROVAL_DENIED,
                decision_time=decision_time,
            )
            raise ApprovalDenied(decision_reason)

        if self.approval_store is not None:
            self.approval_store.resolve(
                request_id=request_id,
                state="approved",
                approver_id=approver_id,
            )

        return self._handle_allow(
            func=func,
            args=args,
            kwargs=kwargs,
            safe_args=safe_args,
            safe_kwargs=safe_kwargs,
            request_id=request_id,
            action=action,
            decision_reason=decision_reason,
            reason_code=reason_code,
            policy_id=policy_id,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            decision_time=decision_time,
            budget_cost=budget_cost,
            decision_metadata={
                "approval_binding": binding,
                "approved": approved,
                "approver_id": approver_id,
                "policy_decision": "require_approval",
            },
        )

    def _log_decision_strict(
        self,
        *,
        request_id: str,
        action: str,
        decision: Decision,
        reason: str,
        metadata: dict[str, Any],
        policy_id: str,
        policy_hash: str,
        agent_id: str,
        reason_code: str | None,
        decision_hash: str | None = None,
        decision_time: datetime | None = None,
    ) -> str:
        """Log decision; if logging fails, raise AuditLogError to fail closed."""
        decision_time = decision_time or datetime.now(timezone.utc)
        metadata_with_reason = dict(metadata)
        if reason_code is not None:
            metadata_with_reason.setdefault("reason_code", reason_code)
        entry = self._build_decision_ledger_entry(
            action=action,
            request_id=request_id,
            decision=decision,
            reason=reason,
            metadata=metadata_with_reason,
            decision_hash=decision_hash or "",
            policy_id=policy_id,
            policy_hash=policy_hash,
            agent_id=agent_id,
            reason_code=reason_code,
            decision_time=_format_timestamp(decision_time),
        )
        try:
            decision_hash_value = self.ledger.append(entry)
        except Exception as exc:
            raise AuditLogError(f"Failed to write audit log: {exc}") from exc
        try:
            self.logger.log(
                AuditEntry(
                    timestamp=decision_time,
                    request_id=request_id,
                    event="decision",
                    action=action,
                    decision=decision,
                    reason=reason,
                    metadata=metadata_with_reason,
                )
            )
        except Exception as exc:
            raise AuditLogError(f"Failed to write audit log: {exc}") from exc
        return decision_hash_value

    def _execute_and_log_outcome(
        self,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        safe_args: list[str],
        safe_kwargs: dict[str, str],
        request_id: str,
        action: str,
        reason: str,
        reason_code: str | None,
        policy_id: str,
        policy_hash: str,
        decision_hash: str,
        agent_id: str,
    ) -> R:
        """Execute function and log outcome (success or error). Re-raises exceptions."""
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e)
            if len(error_msg) > 200:
                error_msg = error_msg[:197] + "..."
            self._log_outcome(
                request_id=request_id,
                action=action,
                reason=reason,
                reason_code=reason_code,
                outcome="error",
                error_type=type(e).__name__,
                error=error_msg,
                policy_id=policy_id,
                policy_hash=policy_hash,
                decision_hash=decision_hash,
                agent_id=agent_id,
                args=safe_args,
                kwargs=safe_kwargs,
            )
            raise
        else:
            self._log_outcome(
                request_id=request_id,
                action=action,
                reason=reason,
                reason_code=reason_code,
                outcome="success",
                policy_id=policy_id,
                policy_hash=policy_hash,
                decision_hash=decision_hash,
                agent_id=agent_id,
                args=safe_args,
                kwargs=safe_kwargs,
            )
            return result

    def _log_decision(
        self,
        request_id: str,
        action: str,
        decision: Decision,
        reason: str,
        metadata: dict[str, Any],
        policy_id: str,
        policy_hash: str,
        agent_id: str,
        reason_code: str | None,
        decision_hash: str | None = None,
        decision_time: datetime | None = None,
    ) -> str:
        """Write a decision audit entry. Raises AuditLogError on failure."""
        timestamp = decision_time or datetime.now(timezone.utc)
        decision_time_text = _format_timestamp(timestamp)
        hash_value = decision_hash or self._decision_hash(
            action=action,
            request_id=request_id,
            policy_hash=policy_hash,
            decision_time=decision_time_text,
            parameters={
                "args": metadata.get("args", []),
                "kwargs": metadata.get("kwargs", {}),
            },
        )
        audit_metadata = dict(metadata)
        audit_metadata["policy_id"] = policy_id
        audit_metadata["policy_hash"] = policy_hash
        audit_metadata["decision_hash"] = hash_value
        audit_metadata["agent_id"] = agent_id
        if reason_code is not None:
            audit_metadata["reason_code"] = reason_code
        entry = AuditEntry(
            timestamp=timestamp,
            request_id=request_id,
            event="decision",
            action=action,
            decision=decision,
            reason=reason,
            metadata=audit_metadata,
        )
        try:
            self.ledger.append(
                self._build_decision_ledger_entry(
                    action=action,
                    request_id=request_id,
                    decision=decision,
                    reason=reason,
                    metadata=audit_metadata,
                    decision_hash=hash_value,
                    policy_id=policy_id,
                    policy_hash=policy_hash,
                    agent_id=agent_id,
                    reason_code=reason_code,
                    decision_time=decision_time_text,
                )
            )
            self.logger.log(entry)
        except Exception as e:
            raise AuditLogError(f"Failed to write audit log: {e}") from e
        return hash_value

    def _budget_check(
        self,
        *,
        request_id: str,
        agent: str,
        tool: str,
        cost: int,
        policy_id: str,
        policy_hash: str,
        decision_hash: str,
        agent_id: str,
        action: str,
        args: list[str],
        kwargs: dict[str, str],
    ) -> None:
        if self.budget_manager is None:
            return
        try:
            self.budget_manager.check(request_id=request_id, agent=agent, tool=tool, cost=cost)
        except BudgetExceeded as exc:
            reason_code = BUDGET_EXCEEDED_TOOL_RATE
            message = str(exc).lower()
            if "agent" in message:
                reason_code = BUDGET_EXCEEDED_AGENT_RATE
            elif "tool" in message:
                reason_code = BUDGET_EXCEEDED_TOOL_RATE
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="budget exceeded",
                metadata={
                    "error": str(exc),
                    "args": args,
                    "kwargs": kwargs,
                    "policy_decision": "require_budget",
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=agent_id,
                reason_code=reason_code,
                decision_hash=decision_hash,
                decision_time=datetime.now(timezone.utc),
            )
            raise ApprovalDenied("budget exceeded") from exc
        except BudgetError as exc:
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="budget state error",
                metadata={
                    "error": str(exc),
                    "args": args,
                    "kwargs": kwargs,
                    "policy_decision": "require_budget",
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=agent_id,
                reason_code=BUDGET_EVALUATION_FAILED,
                decision_hash=decision_hash,
                decision_time=datetime.now(timezone.utc),
            )
            raise PolicyError("budget state error") from exc

    def _budget_commit(
        self,
        *,
        request_id: str,
        agent: str,
        tool: str,
        cost: int,
        policy_id: str,
        policy_hash: str,
        decision_hash: str,
        agent_id: str,
        action: str,
        args: list[str],
        kwargs: dict[str, str],
    ) -> None:
        if self.budget_manager is None:
            return
        try:
            self.budget_manager.commit(request_id)
        except BudgetExceeded as exc:
            reason_code = BUDGET_EXCEEDED_TOOL_RATE
            message = str(exc).lower()
            if "agent" in message:
                reason_code = BUDGET_EXCEEDED_AGENT_RATE
            elif "tool" in message:
                reason_code = BUDGET_EXCEEDED_TOOL_RATE
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="budget exceeded",
                metadata={
                    "error": str(exc),
                    "args": args,
                    "kwargs": kwargs,
                    "policy_decision": "require_budget",
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=agent_id,
                reason_code=reason_code,
                decision_hash=decision_hash,
                decision_time=datetime.now(timezone.utc),
            )
            raise ApprovalDenied("budget exceeded") from exc
        except BudgetError as exc:
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="budget state error",
                metadata={
                    "error": str(exc),
                    "args": args,
                    "kwargs": kwargs,
                    "policy_decision": "require_budget",
                },
                policy_id=policy_id,
                policy_hash=policy_hash,
                agent_id=agent_id,
                reason_code=BUDGET_EVALUATION_FAILED,
                decision_hash=decision_hash,
                decision_time=datetime.now(timezone.utc),
            )
            raise PolicyError("budget state error") from exc

    def _log_outcome(
        self,
        request_id: str,
        action: str,
        reason: str,
        reason_code: str | None,
        outcome: Literal["success", "error"],
        error_type: str | None = None,
        error: str | None = None,
        policy_id: str | None = None,
        policy_hash: str | None = None,
        decision_hash: str | None = None,
        agent_id: str | None = None,
        args: list[str] | None = None,
        kwargs: dict[str, str] | None = None,
    ) -> None:
        """Write an outcome audit entry. Best-effort (does not block on failure)."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            request_id=request_id,
            event="outcome",
            action=action,
            decision=Decision.ALLOW,  # Outcome only logged for allowed executions
            reason=reason,
            outcome=outcome,
            error_type=error_type,
            error=error,
            metadata={
                "policy_id": policy_id,
                "policy_hash": policy_hash,
                "decision_hash": decision_hash,
                "agent_id": agent_id,
                "reason_code": reason_code,
                "args": args or [],
                "kwargs": kwargs or {},
            },
        )
        try:
            self.ledger.append(
                self._build_outcome_ledger_entry(
                    action=action,
                    request_id=request_id,
                    decision_hash=decision_hash,
                    policy_id=policy_id or "",
                    policy_hash=policy_hash or "",
                    reason=reason,
                    reason_code=reason_code,
                    outcome=outcome,
                    error_type=error_type,
                    error=error,
                    agent_id=agent_id or "unknown",
                    args=args or [],
                    kwargs=kwargs or {},
                )
            )
        except Exception:
            pass
        try:
            self.logger.log(entry)
        except Exception:
            pass

    def _parse_approval_response(
        self,
        response: object,
        expected: Mapping[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        binding: dict[str, str] = dict(expected)
        approver_id: str | None = None
        approved = False
        if isinstance(response, bool):
            approved = response
        elif isinstance(response, Mapping):
            candidate_binding = response.get("binding") if isinstance(response, Mapping) else None
            if isinstance(candidate_binding, Mapping):
                binding = {k: str(v) for k, v in candidate_binding.items()}
            candidate_approver = response.get("approver_id")
            if isinstance(candidate_approver, str) and candidate_approver.strip():
                approver_id = candidate_approver
            approved = bool(response.get("approved", "binding" in response and candidate_binding is not None))
        else:
            approved = False
        if binding != dict(expected):
            approved = False
        return approved, binding, approver_id

    def _decision_hash(
        self,
        *,
        action: str,
        request_id: str,
        policy_hash: str,
        decision_time: str,
        parameters: dict[str, Any],
    ) -> str:
        payload = {
            "version": "2.0",
            "request_id": request_id,
            "decision_at": decision_time,
            "policy_hash": policy_hash,
            "intent": action,
            "resource": {"type": "function", "name": action},
            "parameters": parameters,
            "actor": {"principal": "unknown", "source": "python"},
        }
        return sha256_hex(payload)

    def _build_decision_ledger_entry(
        self,
        *,
        action: str,
        request_id: str,
        decision: Decision,
        reason: str,
        metadata: dict[str, Any],
        decision_hash: str,
        policy_id: str,
        policy_hash: str,
        agent_id: str,
        reason_code: str | None,
        decision_time: str,
    ) -> LedgerDecisionEntry:
        approval_binding = metadata.get("approval_binding")
        approver_id = metadata.get("approver_id")
        approval_block: ApprovalRecord | None = None
        if approval_binding is not None:
            approval_block = ApprovalRecord(
                binding=approval_binding,
                approved=bool(metadata.get("approved", False)),
            )
            if approver_id is not None:
                approval_block["approver_id"] = approver_id
            if "policy_decision" in metadata:
                approval_block["policy_decision"] = metadata.get("policy_decision")
        return {
            "schema_version": SCHEMA_VERSION,
            "ledger_version": LEDGER_VERSION,
            "prev_entry_hash": None,
            "entry_hash": None,
            "request_id": request_id,
            "created_at": decision_time,
            "event": "decision",
            "action": action,
            "agent_id": agent_id,
            "decision": {
                "effect": decision.value,
                "reason": reason,
                "reason_code": reason_code,
                "policy_id": policy_id,
                "policy_hash": policy_hash,
                "decision_hash": decision_hash,
            },
            "approval": approval_block,
            "metadata": metadata,
        }

    def _build_outcome_ledger_entry(
        self,
        *,
        action: str,
        request_id: str,
        decision_hash: str | None,
        policy_id: str,
        policy_hash: str,
        reason: str,
        reason_code: str | None,
        outcome: Literal["success", "error"],
        error_type: str | None,
        error: str | None,
        agent_id: str,
        args: list[str],
        kwargs: dict[str, str],
    ) -> LedgerOutcomeEntry:
        return {
            "schema_version": SCHEMA_VERSION,
            "ledger_version": LEDGER_VERSION,
            "prev_entry_hash": None,
            "entry_hash": None,
            "request_id": request_id,
            "created_at": _format_timestamp(datetime.now(timezone.utc)),
            "event": "outcome",
            "action": action,
            "agent_id": agent_id,
            "decision": {
                "decision_hash": decision_hash,
                "policy_id": policy_id,
                "policy_hash": policy_hash,
                "reason": reason,
                "reason_code": reason_code,
            },
            "result": {
                "outcome": outcome,
                "reason": reason,
                "reason_code": reason_code,
                "error_type": error_type,
                "error": error,
            },
            "parameters": {"args": args, "kwargs": kwargs},
            "metadata": {"args": args, "kwargs": kwargs},
        }

    def _policy_id(self, policy: Policy) -> str:
        candidate = getattr(policy, "policy_id", None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        return f"{policy.__class__.__module__}.{policy.__class__.__qualname__}"

    def _policy_hash(self, policy_id: str) -> str:
        return sha256_hex({"policy": policy_id})

    def guard(
        self, *, policy: Policy | None = None, budget_cost: int | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to guard a function with optional policy override.

        Thread-safe: does not mutate self.policy.
        """

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return self.execute(
                    func,
                    *args,
                    policy_override=policy,
                    budget_cost=budget_cost,
                    **kwargs,
                )

            return wrapper

        return decorator
