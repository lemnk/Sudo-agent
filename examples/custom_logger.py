"""Demo: custom in-memory audit logger."""

from decimal import Decimal
from pathlib import Path

from sudoagent import (
    ApprovalDenied,
    AuditEntry,
    Context,
    Decision,
    PolicyResult,
    SudoEngine,
)
from sudoagent.ledger.jsonl import JSONLLedger


class MemoryLogger:
    """In-memory audit logger that implements the AuditLogger protocol."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        """Store audit entry in memory."""
        self.entries.append(entry)


class AmountPolicy:
    """Require approval for high-value amounts."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        amount = ctx.kwargs.get("amount", Decimal("0"))
        if amount > Decimal("100"):
            return PolicyResult(
                decision=Decision.REQUIRE_APPROVAL,
                reason="high-value amount requires approval",
            )
        return PolicyResult(decision=Decision.ALLOW, reason="low-value amount")


def charge(user_id: str, amount: Decimal) -> None:
    """Simulate charging a user."""
    print(f"Charged ${amount} to {user_id}")


def main() -> None:
    logger = MemoryLogger()
    policy = AmountPolicy()
    sudo = SudoEngine(
        policy=policy,
        logger=logger,
        agent_id="demo:custom-logger",
        ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
    )
    guarded_charge = sudo.guard()(charge)

    print("1. Low-value charge:")
    guarded_charge(user_id="u1", amount=Decimal("50"))

    print("\n2. High-value charge:")
    try:
        guarded_charge(user_id="u2", amount=Decimal("200"))
    except ApprovalDenied as e:
        print(f"Denied: {e}")

    print("\n--- Audit Summary ---")
    print(f"Total entries: {len(logger.entries)}")
    for i, entry in enumerate(logger.entries, 1):
        print(f"{i}. {entry.decision.value} | {entry.action} | {entry.reason}")


if __name__ == "__main__":
    main()
