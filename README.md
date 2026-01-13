# sudoagent

A small Python library that guards "dangerous" function calls at runtime.
It evaluates a policy, optionally asks a human for approval in the terminal, and writes an append-only JSONL audit log.

Status: v0.1 MVP

## What it does

SudoAgent wraps a Python function call and enforces one of three outcomes:

- allow: run immediately
- deny: block the call
- require_approval: pause and ask a human (interactive y/n)

Every decision is recorded to an append-only audit log (`sudo_audit.jsonl` by default).

## Why this exists

Agent code can call real tools: refunds, deletes, API writes, production changes.
Most "safety" today is prompt-level. SudoAgent is a runtime gate you can put around any tool function.

SudoAgent is intentionally minimal:
- synchronous only (v0.1)
- interactive approval in the same terminal
- JSONL audit log
- small surface area, easy to extend via interfaces

## Install

```bash
pip install sudoagent
```

Dev install:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# PowerShell: .\.venv\Scripts\Activate.ps1
# cmd.exe: .venv\Scripts\activate.bat
pip install -e ".[dev]"
```

## Quickstart

Run the demo:

```bash
python examples/quickstart.py
```

What you should see:

- a low-value refund auto-approves
- a high-value refund triggers an approval prompt
- approvals/denials are written to sudo_audit.jsonl

## Basic usage

```python
from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine

class HighValueRefundPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        refund_amount = ctx.kwargs.get("refund_amount", 0)
        if refund_amount <= 500:
            return PolicyResult(decision=Decision.ALLOW, reason="within limit")
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="over limit")

sudo = SudoEngine()

@sudo.guard(policy=HighValueRefundPolicy())
def refund_user(user_id: str, refund_amount: float) -> None:
    print(f"Refunding {refund_amount} to {user_id}")

refund_user("user_1", refund_amount=10.0)

try:
    refund_user("user_2", refund_amount=1500.0)
except ApprovalDenied as e:
    print(f"Denied: {e}")
```

## Core concepts

- Context: what got called (action), with args/kwargs captured
- Policy: decides allow/deny/require_approval
- Approver: performs the approval step (interactive terminal in v0.1)
- AuditLogger: writes structured records (JSONL in v0.1)
- Fail closed: if policy or approval fails, SudoAgent denies

## Security notes (v0.1)

SudoAgent is designed to be safe-by-default for the MVP:

- Rich UI output is escaped to prevent markup injection in prompts.
- Audit logging redacts common sensitive keyword names (api_key, token, password, secret, etc.).
- The system fails closed: policy/approval errors result in denial.

This is not a sandbox and does not prevent side effects inside the guarded function itself.
If you need isolation, run tools in a separate process/container and guard the boundary.

## Extending SudoAgent

v0.1 ships with:

- InteractiveApprover (terminal y/n)
- JsonlAuditLogger (append-only JSONL)

To integrate with Slack, email, web UIs, or a database logger:

- implement the Approver protocol
- implement the AuditLogger protocol
- pass them into SudoEngine(policy=..., approver=..., logger=...)

## Roadmap

Planned next:

- non-interactive mode (useful for CI / production defaults)
- richer redaction configuration
- Slack/Webhook approvers (out of core, optional adapters)
- async support (separate API surface)

## Contributing

Small PRs are welcome. Keep changes minimal and reviewable.
If you add a new behavior, include tests.

Development commands:

```bash
pytest -q
ruff check .
mypy src
```

## License

MIT License. See LICENSE.
