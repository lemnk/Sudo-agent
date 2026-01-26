# sudoagent

<p align="center">
  <img src="https://raw.githubusercontent.com/lemnk/Sudo-agent/main/docs/sudoagent_logo.png" width="120" alt="SudoAgent Logo" />
</p>

<p align="center">
  <a href="https://github.com/lemnk/Sudo-agent/actions/workflows/ci.yml">
    <img src="https://github.com/lemnk/Sudo-agent/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://pypi.org/project/sudoagent/">
    <img src="https://img.shields.io/pypi/v/sudoagent.svg" alt="PyPI" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/pypi/l/sudoagent.svg" alt="License" />
  </a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/lemnk/Sudo-agent/main/docs/demo.gif" alt="SudoAgent Demo" />
</p>

A Python library that guards function calls at runtime with policy evaluation, optional human approval, and audit logging.

Version: 0.2.0 (v2 ledger/verification)

## What it does

SudoAgent wraps a function call and enforces one of three outcomes:

- **allow**: execute immediately
- **deny**: block the call, raise `ApprovalDenied`
- **require_approval**: request approval; executes only if approved

Every decision is recorded to an audit log (`sudo_audit.jsonl` by default).

## How it works

1. You create a `SudoEngine` with a required policy.
2. You decorate functions with `@sudo.guard()` or call `sudo.execute(func, ...)`.
3. The engine evaluates the policy, optionally invokes the approver, writes the decision to the audit log, and then executes (or denies).

Key behavior:
- Decision logging happens *before* execution and is fail-closed. If logging fails, execution is blocked and `AuditLogError` is raised.
- Outcome logging happens *after* execution and is best-effort. Logging failures do not affect the return value.
- Approved actions produce two audit entries (decision + outcome). Denied actions produce one (decision only).
- Entries for the same call are linked by `request_id` (UUID4).
- Audit entries include timestamp, action, decision, reason, and safe representations of args/kwargs.

See [docs/architecture.md](docs/architecture.md) for the full execution flow and audit semantics.

## Install

```bash
pip install sudoagent
```

Dev install:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Quickstart

Run the demo:

```bash
python examples/quickstart.py
```

What happens:
- A low-value refund is allowed automatically.
- A high-value refund triggers an interactive approval prompt.
- Decisions are written to `sudo_audit.jsonl`.

v2 ledger demo (decision_hash + verification):

```bash
python examples/v2_demo.py
sudoagent verify sudo_ledger.jsonl
# Or JSON output
sudoagent verify sudo_ledger.jsonl --json
```
(The demo writes `sudo_ledger.jsonl` in the current directory; delete it between runs if you want a fresh ledger.)

To run non-interactively (CI/demo):

```bash
SUDOAGENT_AUTO_APPROVE=1 python examples/quickstart.py
```

On Windows PowerShell:

```powershell
$env:SUDOAGENT_AUTO_APPROVE="1"; python examples/quickstart.py
```

## Basic usage

```python
from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine

class HighValueRefundPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        refund_amount = ctx.kwargs.get("refund_amount", 0)
        if refund_amount <= 500:
            return PolicyResult(decision=Decision.ALLOW, reason="within limit")
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="over limit")

policy = HighValueRefundPolicy()
sudo = SudoEngine(policy=policy)

@sudo.guard()
def refund_user(user_id: str, refund_amount: float) -> None:
    print(f"Refunding {refund_amount} to {user_id}")

refund_user("user_1", refund_amount=10.0)

try:
    refund_user("user_2", refund_amount=1500.0)
except ApprovalDenied as e:
    print(f"Denied: {e}")
```

## Core concepts

- **Context**: captures the function call (action name, args, kwargs, metadata).
- **Policy**: returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL` with a reason.
- **Approver**: handles the approval step. Default is `InteractiveApprover` (terminal y/n).
- **AuditLogger**: writes audit entries. Default is `JsonlAuditLogger`.
- **Fail-closed**: if policy, approval, or decision logging fails, execution is blocked.
- **decision_hash**: SHA-256 over canonical decision payload (request_id, intent, parameters, actor, policy_hash).
- **policy_hash**: SHA-256 over canonicalized policy identifier (class name by default).
- **Ledger verification**: `sudoagent verify <ledger_path>` checks hash chain and canonical form.

## Security notes

- Rich markup in approval prompts is escaped to prevent terminal injection.
- Audit logging redacts sensitive key names (`api_key`, `token`, `password`, etc.) and values (JWT-like strings, `sk-` prefixes, PEM blocks).
- Decision logging failures raise `AuditLogError` and block execution. Outcome logging failures do not block.
- Denied actions log the decision only. Approved actions log decision and outcome, linked by `request_id`.

Example audit entries:
```json
{"event":"decision","request_id":"...","action":"...","decision":"allow","reason":"within limit",...}
{"event":"outcome","request_id":"...","outcome":"success",...}
```

Limitations:
- This is not a sandbox. Side effects inside the guarded function are not prevented.
- The default JSONL logger is intended for single-process use (append-only by normal operation, not tamper-evident). For multi-process or multi-host deployments, implement a custom `AuditLogger`.

## Extending

v0.1 includes:
- `InteractiveApprover` (terminal prompt)
- `JsonlAuditLogger` (append-only JSONL)

To use Slack, email, web UIs, or a database:
- Implement the `Approver` protocol.
- Implement the `AuditLogger` protocol.
- Pass them to `SudoEngine(policy=..., approver=..., logger=...)`.

Notes:
- Policy is required at construction. Pass `AllowAllPolicy()` explicitly for permissive mode.
- `InteractiveApprover` is intended for local development. For production, implement a custom approver.

## Contributing

Small PRs are welcome. Include tests for new behavior.

```bash
pytest -q
ruff check .
mypy src
```

## License

MIT License. See LICENSE.
