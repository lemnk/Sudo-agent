from __future__ import annotations

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.langchain import guard_tool

try:
    from langchain.tools import tool
except ImportError as exc:
    raise SystemExit("Install langchain to run this example") from exc


@tool
def add(x: int, y: int) -> int:
    return x + y


engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, add)

print(guarded.run(2, 3))
