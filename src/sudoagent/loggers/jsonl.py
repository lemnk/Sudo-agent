"""JSONL logger stub."""

from .base import Logger


class JsonlLogger(Logger):
    """Placeholder JSONL logger implementation."""

    def write(self, payload: str) -> None:
        """Stubbed append-only write."""
        pass
