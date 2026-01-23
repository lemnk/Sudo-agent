"""Interactive approval implementation for SudoAgent v0.1."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

from .base import Approver
from ..errors import ApprovalError
from ..policies import PolicyResult
from ..types import Context


# Sensitive key detection terms (case-insensitive substring match)
_SENSITIVE_KEY_TERMS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "bearer",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "credential",
    "session",
    "jwt",
    "auth",
)

# Sensitive value prefixes (case-sensitive)
_SENSITIVE_VALUE_PREFIXES = (
    "sk-",
    "rk-",
    "ghp_",
    "github_pat_",
    "xoxb-",
    "xoxa-",
)


def _safe_repr(obj: Any, max_length: int = 200) -> str:
    """Safe string representation with truncation. Never raises."""
    try:
        r = repr(obj)
        if len(r) > max_length:
            return r[:max_length] + "..."
        return r
    except Exception:
        return "<repr failed>"


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(term in key_lower for term in _SENSITIVE_KEY_TERMS)


def _looks_like_secret(value: Any) -> bool:
    """Check if a value looks like a secret based on heuristics."""
    if not isinstance(value, str):
        return False
    s = value.strip()
    # JWT-like: three base64 segments separated by dots
    if s.count(".") == 2 and len(s) >= 24:
        return True
    # Bearer token (case-insensitive)
    if s.lower().startswith("bearer "):
        return True
    # Known secret prefixes (case-sensitive)
    for prefix in _SENSITIVE_VALUE_PREFIXES:
        if s.startswith(prefix):
            return True
    # PEM blocks
    if "-----BEGIN" in s:
        return True
    return False


def _safe_value(key: str | None, value: Any) -> str:
    """Return safe representation, redacting if key or value is sensitive."""
    if key is not None and _is_sensitive_key(key):
        return "[redacted]"
    if _looks_like_secret(value):
        return "[redacted]"
    return _safe_repr(value)


def _safe_args(args: tuple[Any, ...]) -> list[str]:
    """Convert args tuple to list of safe string representations."""
    return [_safe_value(None, arg) for arg in args]


def _safe_kwargs(kwargs: dict[str, Any]) -> dict[str, str]:
    """Convert kwargs dict to dict with safe string representations."""
    return {k: _safe_value(k, v) for k, v in kwargs.items()}


class InteractiveApprover(Approver):
    """Interactive terminal-based approver using rich."""

    def __init__(self, prompt: str = "Approve this action?") -> None:
        self.prompt = prompt
        self.console = Console()

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        """Prompt user for approval in terminal."""
        try:
            self.console.print(f"\n[bold]Action:[/bold] {escape(ctx.action)}")
            self.console.print(f"[bold]Decision:[/bold] {escape(result.decision.value)}")
            self.console.print(f"[bold]Reason:[/bold] {escape(result.reason)}")
            self.console.print(f"[bold]Request ID:[/bold] {escape(request_id)}")
            self.console.print(f"[bold]Args:[/bold] {escape(str(_safe_args(ctx.args)))}")
            self.console.print(f"[bold]Kwargs:[/bold] {escape(str(_safe_kwargs(ctx.kwargs)))}")
            self.console.print()
            return Confirm.ask(escape(self.prompt), default=False)
        except (KeyboardInterrupt, EOFError) as e:
            raise ApprovalError("Approval prompt interrupted") from e
        except Exception as e:
            raise ApprovalError(f"Approval prompt failed: {e}") from e
