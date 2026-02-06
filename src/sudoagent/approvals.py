"""Deprecated: use approvals_store instead.

This module remains for backward compatibility and re-exports the canonical
approval store types.
"""

from .approvals_store import ApprovalStore, SQLiteApprovalStore

__all__ = ["ApprovalStore", "SQLiteApprovalStore"]
