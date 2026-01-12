"""Execution engine for SudoAgent v0.1."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar
from uuid import uuid4

from .errors import ApprovalDenied, ApprovalError, AuditLogError, PolicyError
from .loggers.base import AuditLogger
from .loggers.jsonl import JsonlAuditLogger
from .notifiers.base import Approver
from .notifiers.interactive import InteractiveApprover
from .policies import AllowAllPolicy, Policy
from .types import AuditEntry, Context, Decision

P = ParamSpec("P")
R = TypeVar("R")


def _safe_repr(obj: Any, max_length: int = 200) -> str:
    """Safe string representation with truncation. Never raises."""
    try:
        r = repr(obj)
        if len(r) > max_length:
            return r[:max_length] + "..."
        return r
    except Exception:
        return "<repr failed>"


def _safe_args_list(args: tuple[Any, ...]) -> list[str]:
    """Convert args tuple to list of safe string representations."""
    return [_safe_repr(arg) for arg in args]


def _safe_kwargs_dict(kwargs: dict[str, Any]) -> dict[str, str]:
    """Convert kwargs dict to dict with safe string representations."""
    return {k: _safe_repr(v) for k, v in kwargs.items()}


class SudoEngine:
    """Runtime engine for guarding function calls with policy evaluation and approval."""

    def __init__(
        self,
        *,
        policy: Policy | None = None,
        approver: Approver | None = None,
        logger: AuditLogger | None = None,
    ) -> None:
        self.policy = policy if policy is not None else AllowAllPolicy()
        self.approver = approver if approver is not None else InteractiveApprover()
        self.logger = logger if logger is not None else JsonlAuditLogger()

    def execute(self, func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute a function under policy control with audit logging."""
        action = f"{func.__module__}.{func.__qualname__}"

        ctx = Context(
            action=action,
            args=args,
            kwargs=kwargs,
            metadata={},
        )

        try:
            result = self.policy.evaluate(ctx)
        except Exception as e:
            self._log_audit(
                action=action,
                decision=Decision.DENY,
                reason="policy evaluation failed",
                metadata={
                    "error": str(e),
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            raise PolicyError(f"Policy evaluation failed: {e}") from e

        if result.decision == Decision.ALLOW:
            self._log_audit(
                action=action,
                decision=Decision.ALLOW,
                reason=result.reason,
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            return func(*args, **kwargs)

        elif result.decision == Decision.DENY:
            self._log_audit(
                action=action,
                decision=Decision.DENY,
                reason=result.reason,
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            raise ApprovalDenied(f"Action denied: {result.reason}")

        elif result.decision == Decision.REQUIRE_APPROVAL:
            request_id = str(uuid4())

            try:
                approved = self.approver.approve(ctx, result, request_id)
            except Exception as e:
                self._log_audit(
                    action=action,
                    decision=Decision.DENY,
                    reason="approval process failed",
                    metadata={
                        "request_id": request_id,
                        "error": str(e),
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                raise ApprovalError(f"Approval process failed: {e}") from e

            if approved:
                self._log_audit(
                    action=action,
                    decision=Decision.ALLOW,
                    reason=result.reason,
                    metadata={
                        "request_id": request_id,
                        "approved": True,
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                return func(*args, **kwargs)
            else:
                self._log_audit(
                    action=action,
                    decision=Decision.DENY,
                    reason=result.reason,
                    metadata={
                        "request_id": request_id,
                        "approved": False,
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                raise ApprovalDenied(f"Action denied by user: {result.reason}")

        else:
            self._log_audit(
                action=action,
                decision=Decision.DENY,
                reason="unknown decision type",
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            raise PolicyError(f"Unknown decision: {result.decision}")

    def _log_audit(
        self, action: str, decision: Decision, reason: str, metadata: dict[str, Any]
    ) -> None:
        """Write an audit entry. Raises AuditLogError on failure."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            action=action,
            decision=decision,
            reason=reason,
            metadata=metadata,
        )
        try:
            self.logger.log(entry)
        except Exception as e:
            raise AuditLogError(f"Failed to write audit log: {e}") from e

    def guard(
        self, *, policy: Policy | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to guard a function with optional policy override."""
        original_policy = self.policy

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if policy is not None:
                    self.policy = policy
                try:
                    return self.execute(func, *args, **kwargs)
                finally:
                    if policy is not None:
                        self.policy = original_policy

            return wrapper

        return decorator
