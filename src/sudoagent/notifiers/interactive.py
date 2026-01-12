"""Interactive approval implementation for SudoAgent v0.1."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

from .base import Approver
from ..errors import ApprovalError
from ..policies import PolicyResult
from ..types import Context


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
            self.console.print()
            
            return Confirm.ask(escape(self.prompt), default=False)
        except (KeyboardInterrupt, EOFError) as e:
            raise ApprovalError("Approval prompt interrupted") from e
        except Exception as e:
            raise ApprovalError(f"Approval prompt failed: {e}") from e
