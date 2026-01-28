from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sudoagent import ApprovalDenied, Context, Decision, JSONLLedger, PolicyResult, SudoEngine
from sudoagent.notifiers.base import Approver


class HighValuePolicy:
    def __init__(self, *, limit: int) -> None:
        self.limit = limit

    def evaluate(self, ctx: Context) -> PolicyResult:
        amount = int(ctx.kwargs.get("amount", 0))
        if amount <= self.limit:
            return PolicyResult(decision=Decision.ALLOW, reason="within limit")
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="over limit")


class ScriptedApprover(Approver):
    """Approver that returns scripted approvals for demos/tests."""

    def __init__(self, outcomes: Iterator[bool]) -> None:
        self.outcomes = outcomes

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        return next(self.outcomes)


def main() -> None:
    ledger_path = Path("sudo_ledger.jsonl")
    ledger = JSONLLedger(ledger_path)

    # First approval attempt will deny, second will approve.
    approver = ScriptedApprover(iter([False, True]))
    engine = SudoEngine(policy=HighValuePolicy(limit=100), approver=approver, ledger=ledger, agent_id="demo:v2")

    def transfer(amount: int) -> str:
        return f"sent ${amount}"

    print("Attempt 1: expect approval denied")
    try:
        engine.execute(transfer, amount=250)
    except ApprovalDenied as exc:
        print(f"Denied: {exc}")

    print("Attempt 2: expect approval granted")
    result = engine.execute(transfer, amount=250)
    print(f"Result: {result}")

    print(f"Ledger written to: {ledger_path}")
    print("Verify:")
    print(f"  sudoagent verify {ledger_path}")
    print(f"  sudoagent verify {ledger_path} --json")


if __name__ == "__main__":
    main()
