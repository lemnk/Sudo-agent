"""
Simple latency microbenchmark for SudoAgent.

Measures:
- baseline direct call
- SudoEngine + JSONL ledger
- SudoEngine + SQLite ledger
- SudoEngine + approval (auto-approve) + SQLite ledger
"""

from __future__ import annotations

import time
from pathlib import Path
from statistics import mean, median, quantiles
from tempfile import TemporaryDirectory

from sudoagent import Context, Decision, PolicyResult, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.ledger.sqlite import SQLiteLedger
from sudoagent.notifiers.base import Approver

ROUNDS = 100  # adjust for tighter p95s; increase for more stable p95


class AllowPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.ALLOW, reason="ok")


class RequireApprovalPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")


class AutoApprover(Approver):
    def approve(self, ctx: Context, result: PolicyResult, request_id: str):
        return True  # simple auto-approve for benchmarking


def bench(label: str, call) -> None:
    times = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        call()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1_000_000)  # microseconds
    p50 = median(times)
    p95 = quantiles(times, n=100)[94]
    print(f"{label:28s} avg {mean(times):8.2f} us | p50 {p50:8.2f} us | p95 {p95:8.2f} us")


def main() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        jsonl_engine = SudoEngine(
            policy=AllowPolicy(),
            ledger=JSONLLedger(tmp / "ledger.jsonl"),
        )
        sqlite_engine = SudoEngine(
            policy=AllowPolicy(),
            ledger=SQLiteLedger(tmp / "ledger.sqlite"),
        )
        approval_engine = SudoEngine(
            policy=RequireApprovalPolicy(),
            approver=AutoApprover(),
            ledger=SQLiteLedger(tmp / "ledger_approval.sqlite"),
        )

        bench("baseline direct", lambda: (lambda x: x)(1))
        bench("sudoengine JSONL", lambda: jsonl_engine.execute(lambda: 1))
        bench("sudoengine SQLite", lambda: sqlite_engine.execute(lambda: 1))
        bench("sudoengine approval", lambda: approval_engine.execute(lambda: 1))


if __name__ == "__main__":
    main()
