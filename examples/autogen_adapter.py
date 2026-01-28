from __future__ import annotations

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.autogen import guard_tool

try:
    import autogen  # noqa: F401
except ImportError as exc:
    raise SystemExit("Install autogen to run this example") from exc


def multiply(x: int, y: int) -> int:
    return x * y


engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, multiply)

print(guarded(3, 4))
