from __future__ import annotations

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.autogen import guard_tool as guard_autogen_tool
from sudoagent.adapters.crewai import guard_tool as guard_crewai_tool
from sudoagent.adapters.langchain import guard_tool as guard_langchain_tool
from sudoagent.types import AuditEntry

TEST_AGENT_ID = "test-agent"


class _MemoryLogger:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class _MemoryLedger:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, entry: dict[str, object]) -> str:
        self.entries.append(entry)
        return str(entry.get("decision_hash", "hash"))


def _engine() -> SudoEngine:
    return SudoEngine(agent_id=TEST_AGENT_ID, 
        policy=AllowAllPolicy(),
        logger=_MemoryLogger(),
        ledger=_MemoryLedger(),
    )


def test_crewai_guard_tool_executes() -> None:
    engine = _engine()

    def tool(x: int) -> int:
        return x * 2

    guarded = guard_crewai_tool(engine, tool)

    assert guarded(3) == 6


def test_autogen_guard_tool_executes() -> None:
    engine = _engine()

    def tool(x: int, y: int) -> int:
        return x + y

    guarded = guard_autogen_tool(engine, tool)

    assert guarded(2, 4) == 6


def test_langchain_guard_tool_executes() -> None:
    engine = _engine()

    class DummyTool:
        name = "dummy"

        def run(self, x: int) -> int:
            return x + 1

        def invoke(self, x: int) -> int:
            return x + 2

    guarded = guard_langchain_tool(engine, DummyTool())

    assert guarded.run(1) == 2
    assert guarded.invoke(1) == 3
