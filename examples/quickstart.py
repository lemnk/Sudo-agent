"""Quickstart demo for SudoAgent v0.1."""

from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine


class HighValueRefundPolicy:
    """Policy that requires approval for refunds over $500."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        refund_amount = ctx.kwargs.get("refund_amount", 0)

        if refund_amount <= 500:
            return PolicyResult(
                decision=Decision.ALLOW,
                reason=f"refund of ${refund_amount} is within auto-approval limit",
            )
        else:
            return PolicyResult(
                decision=Decision.REQUIRE_APPROVAL,
                reason=f"refund of ${refund_amount} exceeds $500 threshold",
            )


def main() -> None:
    sudo = SudoEngine()

    @sudo.guard(policy=HighValueRefundPolicy())
    def refund_user(user_id: str, refund_amount: float) -> None:
        print(f"Processing refund: ${refund_amount} to user {user_id}")

    print("Demo 1: Low-value refund (auto-approved)")
    refund_user("user_123", refund_amount=250.0)

    print("\nDemo 2: High-value refund (requires approval)")
    try:
        refund_user("user_456", refund_amount=1500.0)
    except ApprovalDenied as e:
        print(f"Denied: {e}")


if __name__ == "__main__":
    main()
