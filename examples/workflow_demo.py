from __future__ import annotations

import os
from pathlib import Path

from sudoagent import (
    ApprovalDenied,
    BudgetManager,
    Context,
    Decision,
    JSONLLedger,
    PolicyResult,
    SudoEngine,
)
from sudoagent.notifiers.base import Approver


class PaymentPolicy:
    """Require approval for amounts above a fixed limit."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        amount = float(ctx.kwargs.get("amount", 0))
        if amount <= 100:
            return PolicyResult(
                decision=Decision.ALLOW,
                reason="amount within auto-approval limit",
            )
        return PolicyResult(
            decision=Decision.REQUIRE_APPROVAL,
            reason="amount exceeds auto-approval limit",
        )


class AlwaysApprove(Approver):
    """Auto-approver for CI/demo runs."""

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        print("[auto-approved for demo]")
        return True


def main() -> None:
    ledger_path = Path("sudo_ledger.jsonl")
    ledger = JSONLLedger(ledger_path)
    budget = BudgetManager(agent_limit=2, tool_limit=2, window_seconds=60)
    approver = AlwaysApprove() if os.getenv("SUDOAGENT_AUTO_APPROVE") == "1" else None
    engine = SudoEngine(
        policy=PaymentPolicy(),
        approver=approver,
        ledger=ledger,
        budget_manager=budget,
        agent_id="demo-agent",
    )

    @engine.guard(budget_cost=1)
    def charge(user_id: str, amount: float) -> None:
        print(f"charge {user_id} amount={amount}")

    print("Demo 1: low amount (allowed)")
    charge("user-1", amount=25.0)

    print("\nDemo 2: high amount (requires approval)")
    try:
        charge("user-2", amount=250.0)
    except ApprovalDenied as exc:
        print(f"Denied: {exc}")

    print("\nDemo 3: budget limit (may deny)")
    try:
        charge("user-3", amount=10.0)
    except ApprovalDenied as exc:
        print(f"Denied: {exc}")

    print("\nVerifying ledger...")
    ledger.verify()
    print(f"Ledger verification ok: {ledger_path}")


if __name__ == "__main__":
    main()
