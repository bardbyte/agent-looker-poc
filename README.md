# DMP-SL-Agent: Data Marketplace Semantic Layer Agent

> A **production-ready reference implementation** for building agentic systems that interact with enterprise semantic layers via MCP tools, featuring persistent memory and autonomous reasoning.

---

## Executive Summary

This repository provides a **production-ready skeleton** demonstrating how to build autonomous AI agents that connect to enterprise data systems. It showcases:

- **Agentic Architecture** — Autonomous multi-step reasoning with tool orchestration
- **MCP Tool Integration** — Connect to any data system via Model Context Protocol
- **Persistent Memory** — Context-aware sessions for natural conversational workflows
- **Real-Time Observability** — Transparent thinking visualization for debugging and trust

**Business Value**: Enable natural language access to enterprise data without users needing to understand the underlying data models, SQL, or BI tool interfaces.

---

## Why This Matters for Enterprise

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TRADITIONAL APPROACH                            │
│                                                                     │
│   Business User → Learn BI Tool → Understand Data Model → Query    │
│                         ↓                                           │
│              High training cost, slow time-to-insight               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     SEMANTIC LAYER AGENT                            │
│                                                                     │
│   Business User → Ask in Natural Language → Agent Handles Rest     │
│                         ↓                                           │
│              Zero training, instant insights                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        YOUR APPLICATION                              │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      AgentOrchestrator                        │   │
│  │                                                               │   │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │   │
│  │   │   Memory    │    │  Reasoning  │    │  Thinking   │      │   │
│  │   │  (History)  │───▶│    Loop     │───▶│  Callbacks  │      │   │
│  │   └─────────────┘    └─────────────┘    └─────────────┘      │   │
│  │                             │                                 │   │
│  │                             ▼                                 │   │
│  │                    ┌─────────────────┐                        │   │
│  │                    │   LLM + Tools   │ ← Tool-augmented LLM   │   │
│  │                    └─────────────────┘                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                │                                     │
└────────────────────────────────┼─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      MCP TOOL SERVERS                                │
├──────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │
│  │  Looker    │  │ Snowflake  │  │  dbt       │  │  Custom    │     │
│  │  MCP       │  │  MCP       │  │  MCP       │  │  MCP       │     │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘     │
│                                                                      │
│              Any data system with an MCP adapter                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
dmp-sl-agent/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
│
├── src/
│   ├── __init__.py
│   ├── orchestrator.py       # Agentic reasoning loop
│   ├── callbacks.py          # Thinking event system
│   └── session.py            # Conversation & memory management
│
├── config/
│   └── prompts/
│       └── system.py         # System prompts by domain
│
├── examples/
│   ├── cli_chat.py           # Interactive CLI demo
│   ├── api_server.py         # REST API example
│   └── streamlit_app.py      # Web UI example
│
└── tests/
    ├── __init__.py
    ├── test_orchestrator.py
    └── test_callbacks.py
```

---

## Core Components

### 1. Agentic Orchestration Loop

The agent autonomously reasons and acts until it reaches a conclusion:

```python
class AgentOrchestrator:
    """
    Agentic loop that orchestrates reasoning and tool execution.

    The agent:
    1. Receives a user query
    2. Reasons about what tools to call
    3. Executes tools and observes results
    4. Continues reasoning with new context
    5. Provides final answer when ready
    """

    async def run(self, messages: list[dict]) -> dict:
        while iteration < self.max_iterations:
            result = await self.agent.ainvoke(messages)

            if tool_results:
                # Agent called tools - add results to memory, continue
                messages.extend(tool_results)
                continue
            else:
                # Agent reached conclusion
                return result
```

### 2. Thinking Callbacks (Observability)

Pluggable system for real-time visibility into agent reasoning:

```python
class ThinkingCallback(ABC):
    """Abstract interface for thinking event handlers."""

    @abstractmethod
    def on_thinking(self, event: ThinkingEvent) -> None:
        pass

# Implementations
class ConsoleThinkingCallback    # CLI output with rich formatting
class WebSocketThinkingCallback  # Stream to web UI
class LoggingThinkingCallback    # Enterprise logging systems
class MetricsThinkingCallback    # Observability platforms
```

### 3. Conversation Memory

Context-aware sessions that maintain state across interactions:

```python
class ChatSession:
    """Manages conversation history for contextual follow-ups."""

    async def chat(self, user_input: str) -> str:
        # Agent sees full conversation context
        messages = self.history + [{"role": "user", "content": user_input}]
        result = await self.orchestrator.run(messages)
        self.history.append(result)
        return result
```

---

## How It Works

The agent follows an autonomous reasoning pattern:

```
User: "Show me top products by revenue"
         │
         ▼
    ┌─────────────────────────────────────────┐
    │ Agent reasons: "I need to discover      │
    │ available models first"                 │
    │                                         │
    │ → Calls get_models()                    │
    │ → Observes: [sales, ecommerce, ...]     │
    │                                         │
    │ Agent reasons: "sales model looks       │
    │ relevant, let me explore it"            │
    │                                         │
    │ → Calls get_explores(model="sales")     │
    │ → Observes: [orders, products, ...]     │
    │                                         │
    │ Agent reasons: "I found revenue         │
    │ metrics, now I can query"               │
    │                                         │
    │ → Calls query(dimensions, measures)     │
    │ → Observes: [{product: X, rev: $1M}...] │
    │                                         │
    │ Agent concludes: "Here are your         │
    │ top products..."                        │
    └─────────────────────────────────────────┘
         │
         ▼
    Final Answer to User
```

---

## Quick Start

### 1. Clone and Install

```bash
git clone <repo-url>
cd dmp-sl-agent
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run the Demo

```bash
python -m examples.cli_chat
```

---

## Example Session

```
You: What were our top 5 products by revenue last quarter?

╭─────────── Tool Call: get_models ───────────╮
│ Discovering available data models...        │
╰─────────────────────────────────────────────╯

╭─────────── Tool Call: get_explores ─────────╮
│ Finding relevant explores in sales model... │
╰─────────────────────────────────────────────╯

╭─────────── Tool Call: get_measures ─────────╮
│ Identifying revenue metrics...              │
╰─────────────────────────────────────────────╯

╭─────────── Tool Call: query ────────────────╮
│ Executing: SELECT product, SUM(revenue)...  │
╰─────────────────────────────────────────────╯

╭─────────── Answer ──────────────────────────╮
│ Here are your top 5 products by revenue     │
│ for Q4 2024:                                │
│                                             │
│ 1. Enterprise Suite    - $2.4M              │
│ 2. Pro Analytics       - $1.8M              │
│ 3. Team Collaboration  - $1.2M              │
│ 4. Data Connector      - $890K              │
│ 5. Reporting Add-on    - $650K              │
╰─────────────────────────────────────────────╯

You: How does that compare to last year?

╭─────────── Tool Call: query ────────────────╮
│ Executing with date filter for Q4 2023...   │
╰─────────────────────────────────────────────╯

╭─────────── Answer ──────────────────────────╮
│ Comparing Q4 2024 vs Q4 2023:               │
│                                             │
│ Enterprise Suite: +18% ($2.4M vs $2.0M)     │
│ Pro Analytics:    +12% ($1.8M vs $1.6M)     │
│ ...                                         │
╰─────────────────────────────────────────────╯
```

Notice how the agent remembers context — the follow-up query "How does that compare to last year?" works without repeating the product/revenue context.

---

## Enterprise Integration Patterns

### Pattern 1: REST API Service

```python
from fastapi import FastAPI
from src import AgentOrchestrator

app = FastAPI()

@app.post("/query")
async def query(request: QueryRequest):
    orchestrator = AgentOrchestrator(
        model_id="gemini-pro",
        tools=await load_mcp_tools(),
    )
    return await orchestrator.run([
        {"role": "user", "content": request.question}
    ])
```

### Pattern 2: Streaming Web UI

```python
class WebSocketThinkingCallback(ThinkingCallback):
    def __init__(self, websocket):
        self.ws = websocket

    def on_thinking(self, event: ThinkingEvent):
        asyncio.create_task(self.ws.send_json({
            "type": event.type.value,
            "content": event.content,
        }))
```

### Pattern 3: Custom Domain Tools

```python
# Load MCP tools from configured servers
tools = await MCPToolLoader.load_tools(config)

# Add domain-specific tools
tools.extend([
    create_compliance_check_tool(),
    create_data_masking_tool(),
    create_audit_logging_tool(),
])
```

---

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `IDAAS_CLIENT_ID` | Enterprise auth client ID | Yes |
| `IDAAS_CLIENT_SECRET` | Enterprise auth secret | Yes |
| `MODEL_API_KEY` | LLM API key | Yes |
| `MCP_SERVER_URL` | MCP server endpoint | Yes |
| `LOG_LEVEL` | Logging verbosity | No |

### System Prompts

Customize agent behavior for your domain:

```python
# config/prompts/system.py

FINANCE_PROMPT = """You are a financial analyst assistant.
Always verify compliance requirements before querying sensitive data.
..."""

SALES_PROMPT = """You are a sales analytics assistant.
Focus on revenue, pipeline, and conversion metrics.
..."""
```

---

## Setting Up Looker MCP Locally

### Prerequisites

1. **Looker API Credentials** — Get a Client ID and Secret from your Looker Admin panel:
   - Go to Admin → Users → Edit User → API Keys
   - Create a new API key pair

2. **Looker Base URL** — Your instance URL (e.g., `https://yourcompany.looker.com`)
   - Note: Some instances use port 19999 for API (`https://yourcompany.looker.com:19999`)

### Option 1: Using MCP Toolbox Binary (Recommended)

```bash
# 1. Download MCP Toolbox (v0.14.0+)
# macOS ARM64
curl -L -o toolbox https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-darwin-arm64
chmod +x toolbox

# macOS Intel
curl -L -o toolbox https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-darwin-amd64
chmod +x toolbox

# Linux
curl -L -o toolbox https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-linux-amd64
chmod +x toolbox
```

```bash
# 2. Run the server
export LOOKER_BASE_URL="https://yourcompany.looker.com"
export LOOKER_CLIENT_ID="your-client-id"
export LOOKER_CLIENT_SECRET="your-client-secret"

./toolbox --stdio --prebuilt looker
```

### Option 2: Using NPX (No Download)

```bash
npx -y @anthropic-ai/toolbox-server --prebuilt looker --stdio
```

Set environment variables before running:
```bash
export LOOKER_BASE_URL="https://yourcompany.looker.com"
export LOOKER_CLIENT_ID="your-client-id"
export LOOKER_CLIENT_SECRET="your-client-secret"
```

### MCP Configuration File

Create `.mcp.json` in project root:

```json
{
  "mcpServers": {
    "looker": {
      "command": "./toolbox",
      "args": ["--stdio", "--prebuilt", "looker"],
      "env": {
        "LOOKER_BASE_URL": "https://yourcompany.looker.com",
        "LOOKER_CLIENT_ID": "your-client-id",
        "LOOKER_CLIENT_SECRET": "your-client-secret",
        "LOOKER_VERIFY_SSL": "true"
      }
    }
  }
}
```

### Available Tools

Once running, the Looker MCP exposes these tools:

| Tool | Description |
|------|-------------|
| `get_models` | List available LookML models |
| `get_explores` | Get explores within a model |
| `get_dimensions` | Get dimensions for an explore |
| `get_measures` | Get measures for an explore |
| `query` | Execute a query against Looker |
| `get_projects` | List LookML projects |
| `get_project_files` | List files in a project |

### Verify Connection

```bash
# Test the MCP server is responding
echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | ./toolbox --stdio --prebuilt looker
```

---

## Technical Notes

### LLM Access

The agent accesses the LLM through SafeChain, which handles enterprise authentication (IdaaS) and model routing. MCP tools are bound to the LLM using SafeChain's tool adapter layer.

### Tool Binding

```python
from safechain.tools.mcp import MCPToolLoader, MCPToolAgent

# Load tools from MCP servers
tools = await MCPToolLoader.load_tools(config)

# Create tool-augmented agent
agent = MCPToolAgent(model_id, tools)
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Agentic loop pattern** | Enables autonomous multi-step discovery and reasoning |
| **Callback-based observability** | Decouples visualization from core logic; supports multiple outputs |
| **Message-based memory** | Compatible with LLM context windows; easy to persist |
| **MCP for tool integration** | Industry standard; vendor-agnostic; extensive ecosystem |

---

## Extending the PoC

### Add New Data Sources

1. Deploy an MCP server for your data source
2. Add server URL to configuration
3. Agent automatically discovers new tools

### Add Custom Reasoning

```python
# Override the orchestrator for domain-specific logic
class ComplianceAwareOrchestrator(AgentOrchestrator):
    async def run(self, messages):
        # Pre-check: Verify user permissions
        await self.verify_data_access(messages)

        # Run standard orchestration
        result = await super().run(messages)

        # Post-check: Audit logging
        await self.log_query_audit(messages, result)

        return result
```

### Production Hardening

- [ ] Add rate limiting and quotas
- [ ] Implement query result caching
- [ ] Add circuit breakers for MCP servers
- [ ] Set up distributed tracing
- [ ] Configure alerting on error rates

---

## Performance Considerations

| Metric | Typical Range | Optimization |
|--------|---------------|--------------|
| Query latency | 2-10s | Cache frequent queries |
| Token usage | 1-5K per query | Tune max_iterations |
| Memory footprint | ~50MB | Limit conversation history |

---

## Security Notes

- All credentials managed via environment variables
- MCP tools enforce row-level security at source
- Conversation history can be encrypted at rest
- Audit trail available via thinking callbacks

---

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Looker MCP via MCP Toolbox](https://googleapis.github.io/genai-toolbox/how-to/connect-ide/looker_mcp/)
- [Google Cloud: Looker MCP Server](https://cloud.google.com/blog/products/business-intelligence/introducing-looker-mcp-server)
- [Looker MCP Documentation](https://docs.cloud.google.com/looker/docs/connect-ide-to-looker-using-mcp-toolbox)
- [ReAct: Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)

---

## License

Internal use only. See LICENSE file for details.

---

*Enterprise-grade agentic AI patterns for the Data Marketplace*
