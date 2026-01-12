"""Policy interface for SudoAgent v0.1."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, field_validator

from .types import Context, Decision


class PolicyResult(BaseModel):
    """Result of policy evaluation without request ID."""

    model_config = {"frozen": True}

    decision: Decision
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reason must be a non-empty string")
        return value


class Policy(Protocol):
    """Policy interface for evaluating guarded actions."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        """Evaluate the context and return a policy decision."""
        ...


class AllowAllPolicy:
    """Policy that allows all actions."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.ALLOW, reason="allowed")


class DenyAllPolicy:
    """Policy that denies all actions."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.DENY, reason="denied")
