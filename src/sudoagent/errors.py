"""Exception types for SudoAgent v0.1."""


class SudoAgentError(Exception):
    """Base exception for all SudoAgent errors."""


class PolicyError(SudoAgentError):
    """Raised when policy evaluation fails."""


class ApprovalDenied(SudoAgentError):
    """Raised when an action is denied by policy or by the approver."""


class ApprovalError(SudoAgentError):
    """Raised when the approval process fails."""


class AuditLogError(SudoAgentError):
    """Raised when audit logging fails."""
