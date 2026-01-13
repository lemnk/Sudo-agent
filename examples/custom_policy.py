"""Demo: custom policy that restricts high-value production actions."""

from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine


class CustomPolicy:
    """Deny high-value production changes; allow everything else."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        environment = ctx.kwargs.get("environment", "")
        amount = ctx.kwargs.get("amount", 0)

        if environment == "prod" and amount > 100:
            return PolicyResult(
                decision=Decision.DENY,
                reason="high-value production charge requires approval",
            )

        return PolicyResult(decision=Decision.ALLOW, reason="allowed")


sudo = SudoEngine(policy=CustomPolicy())


@sudo.guard()
def charge(amount: float, environment: str) -> None:
    """Simulate charging a customer."""
    print(f"Charged ${amount} in {environment} environment")


def main() -> None:
    print("1. Low-value dev charge:")
    charge(amount=50, environment="dev")

    print("\n2. High-value prod charge:")
    try:
        charge(amount=200, environment="prod")
    except ApprovalDenied as e:
        print(f"Denied: {e}")


if __name__ == "__main__":
    main()
