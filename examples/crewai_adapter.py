from __future__ import annotations

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.crewai import guard_tool

try:
    import crewai  # noqa: F401
except ImportError as exc:
    raise SystemExit("Install crewai to run this example") from exc


def summarize(text: str) -> str:
    return text.upper()


engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, summarize)

print(guarded("crew ai"))
