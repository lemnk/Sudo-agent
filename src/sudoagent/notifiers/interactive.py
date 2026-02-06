"""Interactive approval implementation for SudoAgent."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

from .base import Approver
from ..errors import ApprovalError
from ..policies import PolicyResult
from ..redaction import redact_args, redact_kwargs
from ..types import Context

class InteractiveApprover(Approver):
    """Interactive terminal-based approver using rich."""

    def __init__(self, prompt: str = "Approve this action?") -> None:
        self.prompt = prompt
        self.console = Console()

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        """Prompt user for approval in terminal."""
        try:
            if ctx.metadata.get("_redacted"):
                display_args = list(ctx.args)
                display_kwargs = dict(ctx.kwargs)
            else:
                display_args = redact_args(ctx.args)
                display_kwargs = redact_kwargs(ctx.kwargs)
            self.console.print(f"\n[bold]Action:[/bold] {escape(ctx.action)}")
            self.console.print(f"[bold]Decision:[/bold] {escape(result.decision.value)}")
            self.console.print(f"[bold]Reason:[/bold] {escape(result.reason)}")
            self.console.print(f"[bold]Request ID:[/bold] {escape(request_id)}")
            self.console.print(f"[bold]Args:[/bold] {escape(str(display_args))}")
            self.console.print(f"[bold]Kwargs:[/bold] {escape(str(display_kwargs))}")
            self.console.print()
            return Confirm.ask(escape(self.prompt), default=False)
        except (KeyboardInterrupt, EOFError) as e:
            raise ApprovalError("Approval prompt interrupted") from e
        except Exception as e:
            raise ApprovalError("Approval prompt failed") from e
