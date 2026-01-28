"""Quickstart demo for SudoAgent v2."""

from __future__ import annotations

import os

from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine
from sudoagent.notifiers.base import Approver


class HighValueRefundPolicy:
    """Policy that requires approval for refunds over $500."""

    def evaluate(self, ctx: Context) -> PolicyResult:
        refund_amount = ctx.kwargs.get("refund_amount", 0)

        if refund_amount <= 500:
            return PolicyResult(
                decision=Decision.ALLOW,
                reason=f"refund of ${refund_amount} is within auto-approval limit",
            )
        return PolicyResult(
            decision=Decision.REQUIRE_APPROVAL,
            reason=f"refund of ${refund_amount} exceeds $500 threshold",
        )


class AlwaysApprove(Approver):
    """Auto-approver for CI/demo runs."""

    def approve(self, ctx: Context, result: PolicyResult, request_id: str) -> bool:
        print("[auto-approved for demo]")
        return True


def main() -> None:
    policy = HighValueRefundPolicy()

    # Use auto-approve if SUDOAGENT_AUTO_APPROVE=1 (for CI/demo)
    approver = AlwaysApprove() if os.getenv("SUDOAGENT_AUTO_APPROVE") == "1" else None
    sudo = SudoEngine(policy=policy, approver=approver, agent_id="demo:quickstart")

    @sudo.guard()
    def refund_user(user_id: str, refund_amount: float) -> None:
        print(f"Processing refund: ${refund_amount} to user {user_id}")

    print("Demo 1: Low-value refund (auto-approved)")
    refund_user("user_123", refund_amount=250.0)

    print("\nDemo 2: High-value refund (requires approval)")
    try:
        refund_user("user_456", refund_amount=1500.0)
    except ApprovalDenied as e:
        print(f"Denied: {e}")

    print("\nOutputs:")
    print("  Audit log: sudo_audit.jsonl")
    print("  Ledger:    sudo_ledger.jsonl")
    print("\nVerify ledger:")
    print("  sudoagent verify sudo_ledger.jsonl")


if __name__ == "__main__":
    main()
