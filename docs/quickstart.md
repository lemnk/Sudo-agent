# Quickstart (5 minutes)

This quickstart gets you from install to a verified ledger in a few minutes.

## 1) Install

```bash
pip install sudoagent
```

## 2) Run the basic demo

```bash
python examples/quickstart.py
```

This runs a simple policy with interactive approval and writes:
- `sudo_audit.jsonl` (operational record; not tamper-evident)
- `sudo_ledger.jsonl` (tamper-evident evidence; verifiable)

Verify:

```bash
sudoagent verify sudo_ledger.jsonl
```

## 3) Run the full workflow (approval + budgets + verify)

Set auto-approval for a deterministic run:

```bash
SUDOAGENT_AUTO_APPROVE=1 python examples/workflow_demo.py
sudoagent verify sudo_ledger.jsonl
```

PowerShell:

```powershell
$env:SUDOAGENT_AUTO_APPROVE="1"; python examples/workflow_demo.py
sudoagent verify sudo_ledger.jsonl
```

This demo:
- Runs an approval path
- Applies budget limits
- Verifies the ledger after execution

## 4) Minimal integration snippet

```python
from pathlib import Path

from sudoagent import Context, Decision, PolicyResult, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger

class AllowLowRisk:
    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.ALLOW, reason="ok")

engine = SudoEngine(
    policy=AllowLowRisk(),
    agent_id="demo:quickstart",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)

@engine.guard()
def my_tool(x: int) -> int:
    return x * 2
```

## Production checklist

- Choose a ledger backend:
  - JSONL for single-process
  - SQLite WAL for multi-process on one host
- Use a non-interactive approver (Slack, HTTP, UI) instead of terminal prompts.
- Set stable `agent_id` and `policy_id` values for audit clarity.
- Enable signing if you need authenticity proofs (`pip install "sudoagent[crypto]"`); store private keys in a secret manager.
- Configure budgets and pass `budget_cost` for spend accounting.
- Verify ledgers on a schedule; alert on failures.
