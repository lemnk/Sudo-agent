from __future__ import annotations


class LedgerError(RuntimeError):
    """Base class for ledger errors."""


class LedgerWriteError(LedgerError):
    """Raised when an append operation fails."""


class LedgerVerificationError(LedgerError):
    """Raised when ledger verification fails."""


def sanitize_exception(exc: Exception) -> str:
    """Return a safe error message without filesystem paths."""
    if isinstance(exc, OSError):
        parts: list[str] = [exc.__class__.__name__]
        if exc.errno is not None:
            parts.append(f"errno={exc.errno}")
        if exc.strerror:
            parts.append(exc.strerror)
        return " ".join(parts).strip()
    return str(exc)
