from __future__ import annotations

from typing import Any, Protocol

# Any is required because tool signatures are framework-defined.

from ..engine import SudoEngine


class LangChainTool(Protocol):
    name: str

    def run(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        ...


class GuardedLangChainTool:
    def __init__(
        self, engine: SudoEngine, tool: LangChainTool, *, budget_cost: int | None
    ) -> None:
        self._engine = engine
        self._tool = tool
        self._budget_cost = budget_cost

    def run(self, *args: Any, **kwargs: Any) -> Any:
        if hasattr(self._tool, "run"):
            return self._engine.execute(
                self._tool.run,
                *args,
                policy_override=None,
                budget_cost=self._budget_cost,
                **kwargs,
            )
        raise AttributeError("tool does not implement run()")

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        if hasattr(self._tool, "invoke"):
            return self._engine.execute(
                self._tool.invoke,
                *args,
                policy_override=None,
                budget_cost=self._budget_cost,
                **kwargs,
            )
        raise AttributeError("tool does not implement invoke()")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tool, name)


def guard_tool(
    engine: SudoEngine, tool: LangChainTool, *, budget_cost: int | None = None
) -> GuardedLangChainTool:
    return GuardedLangChainTool(engine, tool, budget_cost=budget_cost)
