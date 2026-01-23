"""Execution engine for SudoAgent v0.1."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Literal, ParamSpec, TypeVar
from uuid import uuid4

from .errors import ApprovalDenied, ApprovalError, AuditLogError, PolicyError
from .loggers.base import AuditLogger
from .loggers.jsonl import JsonlAuditLogger
from .notifiers.base import Approver
from .notifiers.interactive import InteractiveApprover
from .policies import Policy
from .types import AuditEntry, Context, Decision

P = ParamSpec("P")
R = TypeVar("R")

# Sensitive key detection terms (case-insensitive substring match)
_SENSITIVE_KEY_TERMS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "bearer",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "credential",
    "session",
    "jwt",
    "auth",
)

# Sensitive value prefixes (case-sensitive)
_SENSITIVE_VALUE_PREFIXES = (
    "sk-",
    "rk-",
    "ghp_",
    "github_pat_",
    "xoxb-",
    "xoxa-",
)


def _safe_repr(obj: Any, max_length: int = 200) -> str:
    """Safe string representation with truncation. Never raises."""
    try:
        r = repr(obj)
        if len(r) > max_length:
            return r[:max_length] + "..."
        return r
    except Exception:
        return "<repr failed>"


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(term in key_lower for term in _SENSITIVE_KEY_TERMS)


def _is_sensitive_value(value: Any) -> bool:
    """Check if a value looks like a secret based on heuristics."""
    if not isinstance(value, str):
        return False
    s = value.strip()
    # JWT-like: three base64 segments separated by dots
    if s.count(".") == 2 and len(s) >= 24:
        return True
    # Bearer token (case-insensitive)
    if s.lower().startswith("bearer "):
        return True
    # Known secret prefixes (case-sensitive)
    for prefix in _SENSITIVE_VALUE_PREFIXES:
        if s.startswith(prefix):
            return True
    # PEM blocks
    if "-----BEGIN" in s:
        return True
    return False


def _safe_value(key: str, value: Any) -> str:
    """Return safe representation, redacting if key or value is sensitive."""
    if _is_sensitive_key(key) or _is_sensitive_value(value):
        return "[redacted]"
    return _safe_repr(value)


def _safe_args_list(args: tuple[Any, ...]) -> list[str]:
    """Convert args tuple to list of safe string representations, redacting sensitive values."""
    result = []
    for arg in args:
        if _is_sensitive_value(arg):
            result.append("[redacted]")
        else:
            result.append(_safe_repr(arg))
    return result


def _safe_kwargs_dict(kwargs: dict[str, Any]) -> dict[str, str]:
    """Convert kwargs dict to dict with safe string representations, redacting sensitive keys/values."""
    return {k: _safe_value(k, v) for k, v in kwargs.items()}


class SudoEngine:
    """Runtime engine for guarding function calls with policy evaluation and approval."""

    def __init__(
        self,
        *,
        policy: Policy,
        approver: Approver | None = None,
        logger: AuditLogger | None = None,
    ) -> None:
        if policy is None:
            raise ValueError(
                "policy is required (pass AllowAllPolicy() explicitly if you want permissive mode)"
            )
        self.policy = policy
        self.approver = approver if approver is not None else InteractiveApprover()
        self.logger = logger if logger is not None else JsonlAuditLogger()

    def execute(
        self,
        func: Callable[..., R],
        /,
        *args: Any,
        policy_override: Policy | None = None,
        **kwargs: Any,
    ) -> R:
        """Execute a function under policy control with audit logging."""
        request_id = str(uuid4())
        effective_policy = policy_override or self.policy
        action = f"{func.__module__}.{func.__qualname__}"

        ctx = Context(
            action=action,
            args=args,
            kwargs=kwargs,
            metadata={},
        )

        # Evaluate policy
        try:
            result = effective_policy.evaluate(ctx)
        except Exception as e:
            self._log_decision(
                request_id=request_id,
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
            # Log decision BEFORE execution (fail-closed)
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.ALLOW,
                reason=result.reason,
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            return self._execute_and_log_outcome(
                func, args, kwargs, request_id, action, result.reason
            )

        elif result.decision == Decision.DENY:
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason=result.reason,
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            raise ApprovalDenied(result.reason)

        elif result.decision == Decision.REQUIRE_APPROVAL:
            try:
                approved = self.approver.approve(ctx, result, request_id)
            except Exception as e:
                self._log_decision(
                    request_id=request_id,
                    action=action,
                    decision=Decision.DENY,
                    reason="approval process failed",
                    metadata={
                        "error": str(e),
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                raise ApprovalError(f"Approval process failed: {e}") from e

            if approved:
                self._log_decision(
                    request_id=request_id,
                    action=action,
                    decision=Decision.ALLOW,
                    reason=result.reason,
                    metadata={
                        "approved": True,
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                return self._execute_and_log_outcome(
                    func, args, kwargs, request_id, action, result.reason
                )
            else:
                self._log_decision(
                    request_id=request_id,
                    action=action,
                    decision=Decision.DENY,
                    reason=result.reason,
                    metadata={
                        "approved": False,
                        "policy_decision": "require_approval",
                        "args": _safe_args_list(args),
                        "kwargs": _safe_kwargs_dict(kwargs),
                    },
                )
                raise ApprovalDenied(result.reason)

        else:
            self._log_decision(
                request_id=request_id,
                action=action,
                decision=Decision.DENY,
                reason="unknown decision type",
                metadata={
                    "args": _safe_args_list(args),
                    "kwargs": _safe_kwargs_dict(kwargs),
                },
            )
            raise PolicyError(f"Unknown decision: {result.decision}")

    def _execute_and_log_outcome(
        self,
        func: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        request_id: str,
        action: str,
        reason: str,
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
                outcome="error",
                error_type=type(e).__name__,
                error=error_msg,
            )
            raise
        else:
            self._log_outcome(
                request_id=request_id,
                action=action,
                reason=reason,
                outcome="success",
            )
            return result

    def _log_decision(
        self,
        request_id: str,
        action: str,
        decision: Decision,
        reason: str,
        metadata: dict[str, Any],
    ) -> None:
        """Write a decision audit entry. Raises AuditLogError on failure."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            request_id=request_id,
            event="decision",
            action=action,
            decision=decision,
            reason=reason,
            metadata=metadata,
        )
        try:
            self.logger.log(entry)
        except Exception as e:
            raise AuditLogError(f"Failed to write audit log: {e}") from e

    def _log_outcome(
        self,
        request_id: str,
        action: str,
        reason: str,
        outcome: Literal["success", "error"],
        error_type: str | None = None,
        error: str | None = None,
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
        )
        try:
            self.logger.log(entry)
        except Exception:
            # Outcome logging is best-effort; decision was already logged
            pass

    def guard(
        self, *, policy: Policy | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to guard a function with optional policy override.

        Thread-safe: does not mutate self.policy.
        """

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return self.execute(func, *args, policy_override=policy, **kwargs)

            return wrapper

        return decorator
