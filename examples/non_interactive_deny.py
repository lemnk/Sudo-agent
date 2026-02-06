"""Demo: non-interactive mode where approvals always fail closed (deny)."""

from decimal import Decimal
from pathlib import Path

from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger


class NonInteractiveApprover:
    """Headless approver that always denies (fail closed)."""

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        """Always return False to deny in non-interactive environments."""
        return False


class RequiresApprovalPolicy:
    """Policy that requires approval for all actions."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(
            decision=Decision.REQUIRE_APPROVAL,
            reason="action requires human approval (non-interactive mode denies)",
        )


def dangerous_transfer(user_id: str, amount: Decimal) -> None:
    """Simulate a dangerous money transfer."""
    print(f"TRANSFER: ${amount} to {user_id}")


def main() -> None:
    policy = RequiresApprovalPolicy()
    approver = NonInteractiveApprover()
    sudo = SudoEngine(
        policy=policy,
        approver=approver,
        agent_id="demo:non-interactive",
        ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
    )

    guarded_transfer = sudo.guard()(dangerous_transfer)

    print("Attempting transfer in non-interactive mode...")
    print("No prompt will appear; approvals are disabled in this mode.")
    try:
        guarded_transfer(user_id="user_789", amount=Decimal("5000"))
    except ApprovalDenied as e:
        print(f"Denied: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
