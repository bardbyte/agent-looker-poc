# liteagent

A lightweight ReAct agent extracted from `chat.py`. One reasoning loop, usable everywhere.

## Why this exists

`chat.py` is a working agent — it takes a user question, calls Looker MCP tools in a loop, and returns an answer. But it's a single script locked to one use case. When Cortex needed the same reasoning loop inside a Google ADK pipeline, and another project needed it in LangGraph, we had three options:

1. Copy-paste `chat.py` into every project (drift guaranteed)
2. Build a framework with routers, pipelines, YAML config, etc. (tried this — 12 files, never used)
3. Extract the working loop as-is, add thin adapters for each orchestration framework

liteagent is option 3.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Orchestration layer (caller's choice)              │
│  Google ADK  ·  LangGraph  ·  your own code         │
└──────────────────────┬──────────────────────────────┘
                       │
              ┌────────▼────────┐
              │    liteagent    │  ← this package
              │   Agent / Chat  │
              │   (ReAct loop)  │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │    safechain    │  ← enterprise LLM gateway
              │  MCPToolAgent   │     (auth, Vertex AI, tokens)
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │     Tools       │  ← optional, pluggable
              │  MCP · custom   │
              │  any LangChain  │
              └─────────────────┘
```

**safechain** handles all LLM access — enterprise auth, Vertex AI, token management. This is a hard dependency. Every LLM call goes through `MCPToolAgent`.

**Tools are optional.** Bind MCP tools from a Toolbox server, pass your own LangChain-compatible tools, or run with no tools at all (pure LLM chat).

**Orchestration is the caller's problem.** liteagent is a single agent. If you need multi-agent pipelines (Planner → Analyst → Summarizer), use ADK's `SequentialAgent` or LangGraph's `StateGraph` — liteagent plugs into both via adapters.

## Files

```
src/liteagent/
├── __init__.py      # Exports + lazy MCP bootstrap
├── agent.py         # Agent (ReAct loop) + Chat (CLI session)
├── thinking.py      # ThinkingEvent, ConsoleCallback (rich panels)
├── adk.py           # Google ADK adapter (optional)
├── langgraph.py     # LangGraph adapter (optional)
└── py.typed         # PEP 561
```

5 files. The core (`agent.py`, `thinking.py`, `__init__.py`) is a direct extraction of `chat.py` lines 112-650. The adapters are thin wrappers (~80 lines each).

## Quick start

### Prerequisites

- Python 3.11+
- `safechain` package (private — install from your internal registry)
- `.env` file with credentials (copy from `.env.example`)

### Setup

```bash
./setup.sh          # creates venv, installs deps, downloads MCP Toolbox
```

### Run (identical to chat.py)

```bash
# Terminal 1 — MCP Toolbox server (only if using MCP tools)
source venv/bin/activate
source .env && export LOOKER_INSTANCE_URL LOOKER_CLIENT_ID LOOKER_CLIENT_SECRET
./toolbox --tools-file tools.yaml

# Terminal 2 — agent
source venv/bin/activate
liteagent
```

That's it. Same behavior as `python chat.py`.

## Tool binding modes

```python
from liteagent import Agent

# 1. Load ALL MCP tools (same as chat.py — needs .env + toolbox running)
agent = Agent()

# 2. Filter MCP tools by name (needs .env + toolbox running)
agent = Agent(tools=["conversational-analytics", "get-models"])

# 3. Bring your own tools (no MCP needed, no toolbox, no .env for tools)
agent = Agent(tools=[my_langchain_tool_1, my_langchain_tool_2])

# 4. Pure LLM chat, no tools at all
agent = Agent(tools=[])
```

Modes 1-2 trigger the MCP bootstrap (loads `.env`, connects to Toolbox server). Modes 3-4 skip it entirely — you just need safechain for the LLM.

## Usage

### Single prompt

```python
import asyncio
from liteagent import Agent, ConsoleCallback

async def main():
    agent = Agent(
        system_prompt="You are a Looker analytics expert.",
        on_thinking=ConsoleCallback(use_rich=True),
    )
    result = await agent.run_prompt("What models are available?")
    print(result["content"])

asyncio.run(main())
```

### Interactive chat

```python
import asyncio
from liteagent import Agent, Chat, ConsoleCallback

async def main():
    agent = Agent(on_thinking=ConsoleCallback())
    chat = Chat(agent)
    await chat.start()  # interactive CLI loop with /tools, /clear, /help, /quit

asyncio.run(main())
```

### Inside Google ADK (Cortex pattern)

```python
from google.adk.agents import SequentialAgent
from liteagent.adk import LiteAgent

planner = LiteAgent(
    name="Planner",
    system_prompt="Break down the question into steps.",
    output_key="plan",
)

analyst = LiteAgent(
    name="LookerAnalyst",
    system_prompt="Execute Looker queries based on the plan.",
    tool_names=["conversational-analytics", "get-models"],
    output_key="analysis",
)

pipeline = SequentialAgent(
    name="cortex",
    sub_agents=[planner, analyst],
)
```

`LiteAgent` wraps `Agent` as an ADK `BaseAgent`. It runs the ReAct loop, saves the result to session state at `output_key`, and yields ADK events. Install with `pip install liteagent[adk]`.

### Inside LangGraph

```python
from liteagent.langgraph import as_node, as_graph
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState

# Option A: as a node in your graph
node_fn = as_node(system_prompt="You are a Looker expert", tools=["get-models"])
graph = StateGraph(MessagesState)
graph.add_node("analyst", node_fn)

# Option B: pre-built single-agent graph
graph = as_graph(system_prompt="You are a Looker expert")
result = await graph.ainvoke({"messages": [HumanMessage(content="What models?")]})
```

Install with `pip install liteagent[langgraph]`.

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `CIBIS_CONSUMER_KEY` | Yes | Enterprise OAuth key (Vertex AI auth via safechain) |
| `CIBIS_CONSUMER_SECRET` | Yes | Enterprise OAuth secret |
| `CIBIS_CONFIGURATION_ID` | Yes | Enterprise config ID |
| `CONFIG_PATH` | Yes | Path to `config.yml` (default: `config.yml`) |
| `LOOKER_INSTANCE_URL` | If MCP tools | Looker instance URL |
| `LOOKER_CLIENT_ID` | If MCP tools | Looker API client ID |
| `LOOKER_CLIENT_SECRET` | If MCP tools | Looker API client secret |

The CIBIS variables are always needed — safechain uses them to authenticate with Vertex AI. The Looker variables are only needed when using MCP tools (modes 1-2).

## What runs where

```
┌─────────────────────────────────────────────────┐
│ Your .env                                        │
│  CIBIS_*        → safechain → Vertex AI (LLM)  │
│  LOOKER_*       → MCP Toolbox → Looker API      │
│  CONFIG_PATH    → ee_config → model ID          │
└─────────────────────────────────────────────────┘

Terminal 1 (only for MCP tools):
  ./toolbox --tools-file tools.yaml
  Serves Looker MCP tools over localhost

Terminal 2:
  liteagent (or your Python script)
  On first Agent.run():
    1. _bootstrap() loads .env → Config → MCPToolLoader
    2. MCPToolAgent created with model + tools
    3. ReAct loop: LLM → tool calls → results → repeat → final answer
```

## Mapping to chat.py

| chat.py | liteagent | Notes |
|---------|-----------|-------|
| `AgentOrchestrator` | `Agent` | Same ReAct loop, same `max_iterations=15` |
| `ChatSession` | `Chat` | Same history limit (20), same `/tools`, `/clear`, `/help`, `/quit` |
| `ConsoleThinkingCallback` | `ConsoleCallback` | Renamed, identical behavior |
| `ThinkingEvent`, `ThinkingType` | Same | Unchanged |
| `main()` lines 551-580 | `_bootstrap()` | Same config → tools → model resolution |
| `main()` lines 600-641 | `Chat.start()` | Same CLI loop |

If `python chat.py` works with your `.env`, then `liteagent` works with the same `.env`. No additional config.

## Dependencies

**Hard (always needed):**
- `safechain` — LLM access (private package)
- `ee_config` — configuration loader (comes with safechain)
- `langchain-core` — message types (`==0.3.83`, pinned — safechain may override)
- `python-dotenv` — `.env` loading
- `rich` — console output for thinking panels

**Optional:**
- `google-adk` — for `liteagent.adk` adapter (`pip install liteagent[adk]`)
- `langgraph` — for `liteagent.langgraph` adapter (`pip install liteagent[langgraph]`)

**Only for MCP tools:**
- `toolbox` binary — MCP Toolbox server (downloaded by `setup.sh`)
- `tools.yaml` — Toolbox configuration (in repo)
- `LOOKER_*` env vars
