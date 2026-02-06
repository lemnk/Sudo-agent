from __future__ import annotations

from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.crewai import guard_tool
from sudoagent.ledger.jsonl import JSONLLedger

try:
    import crewai  # noqa: F401
except ImportError as exc:
    raise SystemExit("Install crewai to run this example") from exc


def summarize(text: str) -> str:
    return text.upper()


engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:crewai",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, summarize)

print(guarded("crew ai"))
