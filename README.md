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
├── requirements.txt          # Python dependencies (version-pinned)
├── setup.sh                  # Automated setup script
├── .env.example              # Environment variable template
├── tools.yaml                # MCP Toolbox configuration
├── chat.py                   # Main agent implementation
└── __init__.py               # Package exports
```

---

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/bardbyte/agent-looker-poc.git
cd agent-looker-poc

# Run the setup script
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Create a Python virtual environment
2. Install all dependencies with correct versions
3. **Verify `langchain-core==0.3.83`** (critical for compatibility)
4. Interactively collect your credentials (CIBIS, Looker)
5. Generate the `.env` file
6. Download and install MCP Toolbox
7. Optionally start the MCP server and chat agent

### Option 2: Manual Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. CRITICAL: Verify langchain-core version
pip show langchain-core | grep Version
# Must be 0.3.83 - if not, run:
pip install langchain-core==0.3.83 --force-reinstall

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Download MCP Toolbox
curl -L -o toolbox https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-darwin-arm64
chmod +x toolbox

# 6. Start MCP server (Terminal 1)
source .env
./toolbox --tools-file tools.yaml

# 7. Run the agent (Terminal 2)
source venv/bin/activate
python chat.py
```

---

## Critical: Dependency Version

> **`langchain-core` must be exactly version `0.3.83`**

The `safechain` library may install an incompatible version of `langchain-core`. The setup script automatically detects and fixes this, but if installing manually:

```bash
# After pip install, verify:
pip show langchain-core | grep Version
# Output should be: Version: 0.3.83

# If not, force reinstall:
pip install langchain-core==0.3.83 --force-reinstall
```

---

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `CIBIS_CONSUMER_KEY` | Enterprise IdaaS consumer key | Yes |
| `CIBIS_CONSUMER_SECRET` | Enterprise IdaaS consumer secret | Yes |
| `CIBIS_CONFIGURATION_ID` | Enterprise IdaaS configuration ID | Yes |
| `CONFIG_PATH` | Path to config.yml | Yes |
| `LOOKER_INSTANCE_URL` | Looker instance URL | Yes |
| `LOOKER_CLIENT_ID` | Looker API client ID | Yes |
| `LOOKER_CLIENT_SECRET` | Looker API client secret | Yes |
| `LOG_LEVEL` | Logging verbosity (INFO/DEBUG) | No |

### tools.yaml

The `tools.yaml` file configures which Looker tools are available:

```yaml
sources:
  my-looker:
    kind: looker
    base_url: $LOOKER_INSTANCE_URL
    client_id: $LOOKER_CLIENT_ID
    client_secret: $LOOKER_CLIENT_SECRET
    verify_ssl: true
    timeout: 120s

toolsets:
  data-exploration:
    - get-models
    - get-explores
    - get-dimensions
    - get-measures
    - get-filters
    - get-parameters
    - query
    - query-sql

  saved-contents:
    - run-look
    - get-dashboards

  lookml-projects:
    - get-projects
    - get-project-files
    - get-project-file
```

---

## Running the Agent

### Two-Terminal Setup

```bash
# Terminal 1: Start MCP Toolbox server
source venv/bin/activate
source .env
./toolbox --tools-file tools.yaml

# Terminal 2: Run chat agent
source venv/bin/activate
python chat.py
```

### Single Command (via setup.sh)

```bash
./setup.sh
# Select "y" when prompted to start services
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

Notice how the agent remembers context — the follow-up query works without repeating the product/revenue context.

---

## Troubleshooting

### langchain-core version mismatch

```
Error: incompatible langchain-core version
```

**Fix:**
```bash
pip install langchain-core==0.3.83 --force-reinstall
```

### MCP Toolbox connection failed

```
Error: Make sure MCP servers are running
```

**Fix:** Ensure the toolbox server is running in a separate terminal:
```bash
./toolbox --tools-file tools.yaml
```

### Looker authentication failed

**Fix:** Verify your Looker credentials in `.env`:
- `LOOKER_INSTANCE_URL` should be the full URL (e.g., `https://company.looker.com`)
- Some instances use port 19999: `https://company.looker.com:19999`

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Agentic loop pattern** | Enables autonomous multi-step discovery and reasoning |
| **Callback-based observability** | Decouples visualization from core logic; supports multiple outputs |
| **Message-based memory** | Compatible with LLM context windows; easy to persist |
| **MCP for tool integration** | Industry standard; vendor-agnostic; extensive ecosystem |

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
