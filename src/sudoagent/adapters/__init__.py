"""Framework adapters for SudoAgent.

Import adapters directly from their modules to avoid circular imports:
    from sudoagent.adapters.autogen import guard_tool as guard_autogen_tool
    from sudoagent.adapters.sync_to_async import SyncLedgerAdapter
"""

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "guard_autogen_tool":
        from .autogen import guard_tool as guard_autogen_tool
        return guard_autogen_tool
    elif name == "guard_crewai_tool":
        from .crewai import guard_tool as guard_crewai_tool
        return guard_crewai_tool
    elif name == "guard_langchain_tool":
        from .langchain import guard_tool as guard_langchain_tool
        return guard_langchain_tool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = (
    "guard_autogen_tool",
    "guard_crewai_tool",
    "guard_langchain_tool",
)


