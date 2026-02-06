from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from sudoagent import (
    ApprovalDenied,
    BudgetManager,
    Context,
    Decision,
    JSONLLedger,
    SQLiteLedger,
    PolicyResult,
    SudoEngine,
)
from sudoagent.notifiers.base import Approver


class PaymentPolicy:
    """Require approval for amounts above a fixed limit."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        amount = ctx.kwargs.get("amount", Decimal("0"))
        if amount <= Decimal("100"):
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
    ledger_kind = (os.getenv("SUDOAGENT_LEDGER") or "jsonl").strip().lower()
    env_path = os.getenv("SUDOAGENT_LEDGER_PATH")

    if ledger_kind == "sqlite":
        ledger_path = Path(env_path) if env_path else Path("sudo_ledger.sqlite")
        ledger = SQLiteLedger(ledger_path)
    else:
        ledger_path = Path(env_path) if env_path else Path("sudo_ledger.jsonl")
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
    def charge(user_id: str, amount: Decimal) -> None:
        print(f"charge {user_id} amount={amount}")

    print("Demo 1: low amount (allowed)")
    charge("user-1", amount=Decimal("25"))

    print("\nDemo 2: high amount (requires approval)")
    try:
        charge("user-2", amount=Decimal("250"))
    except ApprovalDenied as exc:
        print(f"Denied: {exc}")

    print("\nDemo 3: budget limit (may deny)")
    try:
        charge("user-3", amount=Decimal("10"))
    except ApprovalDenied as exc:
        print(f"Denied: {exc}")

    print("\nVerifying ledger...")
    ledger.verify()
    print(f"Ledger verification ok: {ledger_path}")


if __name__ == "__main__":
    main()
