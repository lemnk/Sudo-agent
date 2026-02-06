"""SudoAgent public API."""

from .budgets import BudgetError, BudgetExceeded, BudgetManager, BudgetStateError
from .engine import SudoEngine
from .async_engine import AsyncSudoEngine
from .errors import (
    ApprovalDenied,
    ApprovalError,
    AuditLogError,
    PolicyError,
    SudoAgentError,
)
from .ledger import (
    JSONLLedger,
    SQLiteLedger,
    Ledger,
    LedgerVerificationError,
    LedgerWriteError,
)
from .policies import AllowAllPolicy, DenyAllPolicy, Policy, PolicyResult
from .protocols import (
    AsyncLedger,
    AsyncAuditLogger,
    AsyncApprover,
    AsyncApprovalStore,
    AsyncBudgetManager,
)
from .types import AuditEntry, Context, Decision

__all__ = (
    # Sync engine (backwards compatible)
    "SudoEngine",
    # Async engine (SaaS-grade)
    "AsyncSudoEngine",
    # Types
    "Decision",
    "Context",
    "AuditEntry",
    # Policies
    "Policy",
    "PolicyResult",
    "AllowAllPolicy",
    "DenyAllPolicy",
    # Budgets
    "BudgetManager",
    "BudgetError",
    "BudgetExceeded",
    "BudgetStateError",
    # Ledger
    "Ledger",
    "JSONLLedger",
    "SQLiteLedger",
    "LedgerWriteError",
    "LedgerVerificationError",
    # Async protocols
    "AsyncLedger",
    "AsyncAuditLogger",
    "AsyncApprover",
    "AsyncApprovalStore",
    "AsyncBudgetManager",
    # Errors
    "SudoAgentError",
    "PolicyError",
    "ApprovalDenied",
    "ApprovalError",
    "AuditLogError",
)

