"""Approver interface for SudoAgent v0.1."""

from __future__ import annotations

from typing import Protocol

from ..policies import PolicyResult
from ..types import Context


class Approver(Protocol):
    """Protocol for approval implementations."""

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        """Request approval for an action. Returns True if approved, False if denied."""
        ...
