from __future__ import annotations

from io import StringIO

from rich.console import Console

import sudoagent.notifiers.interactive as interactive
from sudoagent.policies import PolicyResult
from sudoagent.redaction import redact_args, redact_kwargs
from sudoagent.types import Context, Decision


def test_redaction_of_sensitive_key_and_value() -> None:
    args = ("sk-secret", "hello")
    kwargs = {"api_key": "not-secret", "note": "Bearer token-123", "count": 5}

    redacted_args = redact_args(args)
    redacted_kwargs = redact_kwargs(kwargs)

    assert redacted_args[0] == "[redacted]"
    assert redacted_args[1] == "'hello'"
    assert redacted_kwargs["api_key"] == "[redacted]"
    assert redacted_kwargs["note"] == "[redacted]"
    assert redacted_kwargs["count"] == "5"


def test_interactive_approver_redacts_output(monkeypatch) -> None:
    buffer = StringIO()
    approver = interactive.InteractiveApprover()
    approver.console = Console(file=buffer, force_terminal=False, color_system=None)
    monkeypatch.setattr(interactive.Confirm, "ask", lambda *args, **kwargs: False)

    ctx = Context(
        action="demo.tool",
        args=("sk-secret", 5),
        kwargs={"api_key": "token-123", "note": "hello"},
        metadata={},
    )
    result = PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")

    approver.approve(ctx, result, "req-1")

    output = buffer.getvalue()
    assert str(list(redact_args(ctx.args))) in output
    assert str(redact_kwargs(ctx.kwargs)) in output
    assert "sk-secret" not in output
