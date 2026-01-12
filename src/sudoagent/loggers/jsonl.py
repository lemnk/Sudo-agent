"""JSONL audit logger implementation for SudoAgent v0.1."""

from __future__ import annotations

from pathlib import Path

from .base import AuditLogger
from ..errors import AuditLogError
from ..types import AuditEntry


class JsonlAuditLogger:
    """Append-only JSONL audit logger."""

    def __init__(self, path: str = "sudo_audit.jsonl") -> None:
        self.path = Path(path)

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSONL file."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(entry.to_json_line() + "\n")
        except Exception as e:
            raise AuditLogError(f"Failed to write audit log: {e}") from e
