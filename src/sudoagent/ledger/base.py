from __future__ import annotations

from typing import Protocol

from sudoagent.types import LedgerEntry
from .types import VerifyKey


class Ledger(Protocol):
    """Minimal ledger interface used by SudoEngine.

    Implementations should provide:
    - append-only writes (decision entries are fail-closed)
    - full-ledger verification (used by CLI and callers)
    """

    def append(self, entry: LedgerEntry) -> str:
        """Append a single entry and return its chain hash."""

    def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify ledger integrity and (optionally) signatures."""
