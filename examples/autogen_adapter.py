from __future__ import annotations

from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.autogen import guard_tool
from sudoagent.ledger.jsonl import JSONLLedger

try:
    import autogen  # noqa: F401
except ImportError as exc:
    raise SystemExit("Install autogen to run this example") from exc


def multiply(x: int, y: int) -> int:
    return x * y


engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:autogen",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, multiply)

print(guarded(3, 4))
