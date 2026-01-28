from __future__ import annotations

from typing import Callable, ParamSpec, TypeVar

from ..engine import SudoEngine

P = ParamSpec("P")
R = TypeVar("R")


def guard_tool(
    engine: SudoEngine, tool: Callable[P, R], *, budget_cost: int | None = None
) -> Callable[P, R]:
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return engine.execute(
            tool,
            *args,
            policy_override=None,
            budget_cost=budget_cost,
            **kwargs,
        )

    return wrapper
