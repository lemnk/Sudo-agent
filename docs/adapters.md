# Adapter Guide

SudoAgent ships thin wrappers for common agent frameworks. These adapters route tool calls through engine execution and do not add orchestration.

Engine choice:
- Use `SudoEngine` for sync integrations.
- Use `AsyncSudoEngine` for async integrations (or wrap sync implementations with `sync_to_async` adapters).

## LangChain

Install:

```bash
pip install "sudoagent[langchain]"
```

```python
from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.adapters.langchain import guard_tool

from langchain.tools import tool

@tool
def add(x: int, y: int) -> int:
    return x + y

engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:langchain",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, add)
guarded.run(2, 3)
```

## CrewAI

Install:

```bash
pip install "sudoagent[crewai]"
```

```python
from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.adapters.crewai import guard_tool

def summarize(text: str) -> str:
    return text.upper()

engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:crewai",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, summarize)
guarded("crew ai")
```

## AutoGen

Install:

```bash
pip install "sudoagent[autogen]"
```

```python
from pathlib import Path

from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.adapters.autogen import guard_tool

def multiply(x: int, y: int) -> int:
    return x * y

engine = SudoEngine(
    policy=AllowAllPolicy(),
    agent_id="demo:autogen",
    ledger=JSONLLedger(Path("sudo_ledger.jsonl")),
)
guarded = guard_tool(engine, multiply)
guarded(3, 4)
```
