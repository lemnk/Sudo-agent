# Adapter Guide

SudoAgent ships thin wrappers for common agent frameworks. These adapters simply route tool calls through `SudoEngine.execute` and do not add orchestration.

## LangChain

Install:

```bash
pip install "sudoagent[langchain]"
```

```python
from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.langchain import guard_tool

from langchain.tools import tool

@tool
def add(x: int, y: int) -> int:
    return x + y

engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, add)
guarded.run(2, 3)
```

## CrewAI

Install:

```bash
pip install "sudoagent[crewai]"
```

```python
from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.crewai import guard_tool

def summarize(text: str) -> str:
    return text.upper()

engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, summarize)
guarded("crew ai")
```

## AutoGen

Install:

```bash
pip install "sudoagent[autogen]"
```

```python
from sudoagent import AllowAllPolicy, SudoEngine
from sudoagent.adapters.autogen import guard_tool

def multiply(x: int, y: int) -> int:
    return x * y

engine = SudoEngine(policy=AllowAllPolicy())
guarded = guard_tool(engine, multiply)
guarded(3, 4)
```
