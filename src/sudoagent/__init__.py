"""SudoAgent v0.1 public API."""

from .engine import SudoEngine
from .errors import (
    ApprovalDenied,
    ApprovalError,
    AuditLogError,
    PolicyError,
    SudoAgentError,
)
from .policies import AllowAllPolicy, DenyAllPolicy, Policy, PolicyResult
from .types import AuditEntry, Context, Decision

__all__ = (
    "SudoEngine",
    "Decision",
    "Context",
    "AuditEntry",
    "Policy",
    "PolicyResult",
    "AllowAllPolicy",
    "DenyAllPolicy",
    "SudoAgentError",
    "PolicyError",
    "ApprovalDenied",
    "ApprovalError",
    "AuditLogError",
)
