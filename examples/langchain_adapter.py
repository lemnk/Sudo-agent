from __future__ import annotations

from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.langchain import guard_tool
from sudoagent.ledger.jsonl import JSONLLedger

try:
    from langchain.tools import tool
except ImportError as exc:
    raise SystemExit("Install langchain to run this example") from exc


@tool
def add(x: int, y: int) -> int:
    return x + y


engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:langchain",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, add)

print(guarded.run(2, 3))
