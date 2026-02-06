"""Demo: custom policy that restricts high-value production actions."""

from decimal import Decimal
from pathlib import Path

from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger


class CustomPolicy:
    """Deny high-value production changes; allow everything else."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        environment = ctx.kwargs.get("environment", "")
        amount = ctx.kwargs.get("amount", Decimal("0"))

        if environment == "prod" and amount > Decimal("100"):
            return PolicyResult(
                decision=Decision.DENY,
                reason="high-value production charge requires approval",
            )

        return PolicyResult(decision=Decision.ALLOW, reason="allowed")


sudo = SudoEngine(
    policy=CustomPolicy(),
    agent_id="demo:custom-policy",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)


@sudo.guard()
def charge(amount: Decimal, environment: str) -> None:
    """Simulate charging a customer."""
    print(f"Charged ${amount} in {environment} environment")


def main() -> None:
    print("1. Low-value dev charge:")
    charge(amount=Decimal("50"), environment="dev")

    print("\n2. High-value prod charge:")
    try:
        charge(amount=Decimal("200"), environment="prod")
    except ApprovalDenied as e:
        print(f"Denied: {e}")


if __name__ == "__main__":
    main()
