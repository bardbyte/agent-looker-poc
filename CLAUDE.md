# CLAUDE.md - Agent Development Guide

This document captures learnings from building agents with SafeChain and MCP tools.

## Project Context

This is a PoC for a **Data Steward Assistant** that connects to Looker's semantic layer via MCP (Model Context Protocol). The agent does NOT generate SQL itself - Looker MCP generates deterministic SQL; the agent handles intent detection, field selection, and explainability.

## SafeChain Integration

### Core Pattern

SafeChain provides enterprise LLM access and MCP tool binding. Here's the minimal integration:

```python
from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
from ee_config.config import Config

# Load config from environment
config = Config.from_env()

# Load MCP tools (async)
tools = await MCPToolLoader.load_tools(config)

# Create agent with model and tools
model_id = getattr(config, 'model_id', None) or "gemini-pro"
agent = MCPToolAgent(model_id, tools)

# Invoke with LangChain messages
from langchain_core.messages import HumanMessage, SystemMessage
messages = [SystemMessage(content="..."), HumanMessage(content="user query")]
result = await agent.ainvoke(messages)
```

### Result Parsing

```python
if isinstance(result, dict):
    content = result.get("content", "")
    tool_results = result.get("tool_results", [])
else:
    content = getattr(result, "content", str(result))
    tool_results = []

# Tool results structure
for tr in tool_results:
    tool_name = tr.get("tool", "unknown")
    if "error" in tr:
        error = tr["error"]
    else:
        result_data = tr.get("result", "")
```

### Dependencies (CRITICAL)

```
safechain
langgraph==0.2.50
langchain-core==0.3.83  # MUST be exact version - installed AFTER safechain
mcp==1.0.0
httpx-sse==0.4.0
rich==13.0.0
```

**Important**: `langchain-core==0.3.83` must be this exact version. SafeChain may install an incompatible version - override it.

## MCP Tools Configuration

### tools.yaml

```yaml
sources:
  my-looker:
    kind: looker
    base_url: $LOOKER_INSTANCE_URL
    client_id: $LOOKER_CLIENT_ID
    client_secret: $LOOKER_CLIENT_SECRET
```

### Available Looker MCP Tools

- `get_projects` - List available projects
- `get_project_files` - See files in a project (views, models)
- `get_models` - List LookML models
- `get_explores` - List explores in a model
- `get_dimensions` - Get dimensions for an explore
- `get_measures` - Get measures for an explore
- `get_filters` - Get available filters
- `query_sql` - Generate SQL for a query (Looker generates it!)

## Agent Architecture Patterns

### ReAct Loop (Recommended)

Simple while loop with tool execution:

```python
async def process(self, user_input: str, history: list[dict] = None) -> dict:
    messages = history + [{"role": "user", "content": user_input}]
    max_iterations = 15
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        lc_messages = self._to_langchain_messages(messages)
        result = await self.agent.ainvoke(lc_messages)

        # Parse and check for tool calls
        if tool_results:
            # Process tools, add to messages, continue loop
            continue

        # No tool calls = final answer
        return {"response": content}
```

### Multi-Skill Architecture

Define skills with triggers and workflows:

```python
class Skill(str, Enum):
    SCHEMA_EXPLORER = "schema_explorer"
    SQL_GENERATOR = "sql_generator"
    MODEL_ADVISOR = "model_advisor"
    DATA_DICTIONARY = "data_dictionary"

def _detect_skill(self, user_input: str) -> Skill:
    """Heuristic detection - LLM makes final decision."""
    input_lower = user_input.lower()

    if any(t in input_lower for t in ["sql", "query", "how many"]):
        return Skill.SQL_GENERATOR
    # ... more triggers

    return Skill.SCHEMA_EXPLORER  # default
```

### Thinking Events (Explainability)

```python
class ThinkingType(str, Enum):
    INTENT = "intent"
    SKILL = "skill"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"

@dataclass
class ThinkingEvent:
    type: ThinkingType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

def _emit(self, event: ThinkingEvent):
    """Record and display thinking event."""
    self.thinking_events.append(event)
    self._display_event(event)  # Rich panel output
```

### Rich Terminal Display

```python
from rich.console import Console
from rich.panel import Panel

console = Console()
console.print(Panel(
    content,
    title="🔧 Tool Call",
    style="yellow",
    expand=False,
))
```

## System Prompt Structure

```python
SYSTEM_PROMPT = f"""You are a [ROLE] for [CONTEXT]

## Your Mission
[Clear objective]

## Available Tools
[List tools with descriptions]

## Your Workflow
### Step 1: [Phase]
[Instructions]

## Critical Rules
1. [Most important rule]
2. [Second rule]

## Response Style
- [Format guidelines]
"""
```

## File Structure (Recommended)

```
project/
├── run_v2.py           # Entry point
├── src/
│   └── agent.py        # Main agent (~400-600 lines)
├── chat.py             # V1 / reference implementation
├── docs/
│   ├── ARCHITECTURE_DECISION.md
│   └── V2_DESIGN.md
├── requirements.txt
├── setup.sh
├── tools.yaml          # MCP config
├── .env.example
└── CLAUDE.md           # This file
```

## Common Patterns

### Message Conversion

```python
def _to_langchain_messages(self, messages: list[dict]) -> list:
    lc_messages = [SystemMessage(content=SYSTEM_PROMPT)]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            lc_messages.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
                name=msg.get("name", ""),
            ))

    return lc_messages
```

### Async Initialization

```python
class Agent:
    def __init__(self, config=None):
        self.config = config or Config.from_env()
        self.tools = None
        self.agent = None

    async def initialize(self):
        self.tools = await MCPToolLoader.load_tools(self.config)
        self.agent = MCPToolAgent(model_id, self.tools)
```

### CLI Pattern

```python
async def main():
    agent = Agent()
    await agent.initialize()

    history = []
    while True:
        user_input = input("You: ").strip()
        if user_input == "/quit":
            break

        result = await agent.process(user_input, history)
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": result["response"]})

        # Keep history manageable
        if len(history) > 20:
            history = history[-20:]

def run():
    asyncio.run(main())
```

## Key Learnings

1. **Keep it simple**: Start with a single ReAct loop, add complexity only when needed
2. **LLM makes decisions**: Use heuristics for display, but let the LLM decide via system prompt
3. **Tools do the work**: Agent selects and calls tools; tools (like Looker) generate SQL
4. **Explainability matters**: Show thinking events so users understand the process
5. **Version lock dependencies**: `langchain-core==0.3.83` is critical
6. **Best effort first**: Try to answer, only ask clarifying questions when truly stuck

## Environment Variables

```bash
# .env
LOOKER_INSTANCE_URL=https://your-instance.looker.com
LOOKER_CLIENT_ID=your_client_id
LOOKER_CLIENT_SECRET=your_client_secret
MODEL_ID=gemini-pro  # or other supported model
```

## Running the Agent

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run MCP Toolbox (separate terminal)
./toolbox --tools_file tools.yaml

# Run agent
python run_v2.py
```
