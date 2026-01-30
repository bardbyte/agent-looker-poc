# DMP-SL-Agent V2: LangGraph + SafeChain Design

## Overview

This document outlines the design for V2 of the semantic layer agent, integrating **LangGraph** for orchestration while maintaining **SafeChain** for enterprise LLM access and MCP tool binding.

**Goals:**
1. Schema discovery & visualization (models, explores, dimensions, measures)
2. Intent understanding & field mapping
3. **NL to SQL**: Generate deterministic SQL via Looker MCP (not agent-generated)
4. Explain which fields match the user's question and show the SQL
5. Industry-standard LangGraph patterns
6. All LLM calls through SafeChain
7. Ask clarifying questions when user intent is ambiguous (never guess)

**Out of Scope for this PoC:**
- Query execution (we generate SQL but don't run it)
- Result display/data retrieval
- Data export

**The Key Value Prop:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   "What were total sales by region for Q4?"                                  │
│                        │                                                     │
│                        ▼                                                     │
│              ┌─────────────────┐                                             │
│              │  AGENT FIGURES  │                                             │
│              │  OUT FIELDS     │                                             │
│              └─────────────────┘                                             │
│                        │                                                     │
│                        ▼                                                     │
│   dimensions: ["order_items.region"]                                         │
│   measures: ["order_items.total_sales"]                                      │
│   filters: {"order_items.created_date": "2024-Q4"}                           │
│                        │                                                     │
│                        ▼                                                     │
│              ┌─────────────────┐                                             │
│              │   LOOKER MCP    │                                             │
│              │   GENERATES     │                                             │
│              │   SQL           │                                             │
│              └─────────────────┘                                             │
│                        │                                                     │
│                        ▼                                                     │
│   SELECT                                                                     │
│     order_items.region AS "Region",                                          │
│     SUM(order_items.sale_price) AS "Total Sales"                             │
│   FROM order_items                                                           │
│   WHERE order_items.created_date                                             │
│     BETWEEN '2024-10-01' AND '2024-12-31'                                    │
│   GROUP BY 1                                                                 │
│   ORDER BY 2 DESC                                                            │
│                                                                              │
│   ✅ Deterministic, no hallucination                                         │
│   ✅ Uses Looker's semantic layer for correct joins/aggregations             │
│   ✅ Agent only does field selection, Looker does SQL                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Design Principles

### 1. Explainability at Every Step

The agent MUST explain its reasoning at each stage:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  User: "Show me sales by region for Q4"                                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 🔍 INTENT: I understand you want to query sales data grouped by      │    │
│  │    geographic region, filtered to Q4 (Oct-Dec).                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 📊 SCHEMA: Found relevant fields in 'order_items' explore:           │    │
│  │    • Dimension: order_items.region (matches "by region")             │    │
│  │    • Measure: order_items.total_sales (matches "sales")              │    │
│  │    • Filter: order_items.created_date (for Q4 filter)                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 🎯 MAPPING: Building query with:                                     │    │
│  │    dimensions: ["order_items.region"]                                │    │
│  │    measures: ["order_items.total_sales"]                             │    │
│  │    filters: {"order_items.created_date": "2024-Q4"}                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ ✅ RESULT: Query executed successfully                               │    │
│  │                                                                      │    │
│  │    | Region        | Total Sales |                                   │    │
│  │    |---------------|-------------|                                   │    │
│  │    | North America | $2.4M       |                                   │    │
│  │    | EMEA          | $1.8M       |                                   │    │
│  │    | APAC          | $1.2M       |                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. HITL Only When Uncertain

The agent asks clarifying questions ONLY when:
- User query is ambiguous (multiple possible interpretations)
- Field mapping confidence is low
- Multiple fields could match the same intent

**Never guess. Always ask.**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  User: "Show me revenue"                                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ ❓ CLARIFICATION NEEDED                                              │    │
│  │                                                                      │    │
│  │ I found multiple revenue measures. Which one do you mean?            │    │
│  │                                                                      │    │
│  │   1. order_items.total_revenue - Gross revenue before discounts      │    │
│  │   2. order_items.net_revenue - Revenue after discounts               │    │
│  │   3. order_items.mrr - Monthly recurring revenue                     │    │
│  │                                                                      │    │
│  │ Also, how would you like to group the data?                          │    │
│  │   • By time period (day/week/month/quarter)?                         │    │
│  │   • By region?                                                       │    │
│  │   • By product category?                                             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. Intent-Based Tool Loading

Load only the tools needed for the current intent to minimize context pollution:

```python
TOOL_SETS = {
    "discovery": [
        "get_models",
        "get_explores",
        "get_dimensions",
        "get_measures",
    ],
    "query": [
        "query",           # Execute query via Looker
    ],
    "schema_explore": [
        "get_models",
        "get_explores",
        "get_dimensions",
        "get_measures",
        "get_filters",
    ],
    "lookml": [
        "get_projects",
        "get_project_files",
        "get_project_file",
    ],
}

# Intent → Tools mapping
INTENT_TOOLS = {
    "query": ["discovery", "query"],           # Need to discover schema, then query
    "schema_explore": ["schema_explore"],       # Only need schema tools
    "lookml_explore": ["lookml"],              # Only need LookML tools
}
```

**Benefits:**
- Reduced token usage (fewer tools in context)
- Less confusion for LLM (focused tool set)
- Faster responses (smaller context)

---

## Critical Design Principle: Agent Does NOT Generate SQL

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WRONG APPROACH ❌                                  │
│                                                                              │
│   User Query → Agent generates SQL → Execute                                 │
│                     ↑                                                        │
│              Prone to hallucination                                          │
│              (invents field names, wrong syntax)                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           RIGHT APPROACH ✅                                  │
│                                                                              │
│   User Query → Agent selects fields → Looker MCP query() → Looker SQL       │
│                     ↑                         ↑                              │
│              Maps intent to schema      Looker generates                     │
│              Asks questions if unclear  deterministic SQL                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The agent's job is FIELD SELECTION, not SQL generation.**

Looker's semantic layer handles:
- SQL generation
- Join logic
- Aggregation rules
- Access controls

Our agent handles:
- Understanding user intent
- Mapping natural language → Looker fields
- Asking clarifying questions when ambiguous
- Calling `query(dimensions=[...], measures=[...], filters=[...])`

---

## Architecture

### The Agent's Core Intelligence: Model Discovery & Selection

The user doesn't know which Looker model contains their data. **The agent figures this out.**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LOOKER PROJECT STRUCTURE                             │
│                                                                              │
│   project: "enterprise_analytics"                                            │
│   ├── model: "sales"                                                         │
│   │   ├── explore: "order_items" (revenue, orders, products)                 │
│   │   └── explore: "customers" (customer data, segments)                     │
│   ├── model: "marketing"                                                     │
│   │   ├── explore: "campaigns" (ad spend, impressions)                       │
│   │   └── explore: "attribution" (conversion tracking)                       │
│   └── model: "finance"                                                       │
│       └── explore: "gl_entries" (accounting data)                            │
│                                                                              │
│   User asks: "What were total sales by region?"                              │
│   Agent must figure out: sales model → order_items explore → region, revenue │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Full Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER QUERY                                      │
│                    "What were total sales by region?"                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LANGGRAPH ORCHESTRATOR                               │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                          STATE                                       │   │
│   │  • messages: full conversation history (for follow-ups)              │   │
│   │  • project_schema: all models/explores (session cached)              │   │
│   │  • selected_model: which model(s) agent chose                        │   │
│   │  • selected_explore: which explore(s) to query                       │   │
│   │  • selected_fields: dimensions/measures for query                    │   │
│   │  • confidence: how confident in selections                           │   │
│   │  • explanation_trace: reasoning at each step                         │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│                              GRAPH FLOW                                      │
│                                                                              │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│   │ DISCOVER │    │ CLASSIFY │    │  SELECT  │    │  SELECT  │             │
│   │ PROJECT  │───▶│  INTENT  │───▶│  MODEL   │───▶│  FIELDS  │             │
│   │ (once)   │    │          │    │          │    │          │             │
│   └──────────┘    └──────────┘    └──────────┘    └──────────┘             │
│        │               │               │               │                    │
│   [Explain]       [Explain]       [Explain]       [Explain]                │
│   "Found 3       "You want to    "Best match:    "Using:                   │
│    models..."     query sales     sales model,    region (dim)             │
│                   by region"      order_items     total_sales (msr)"       │
│                                   explore"                                  │
│                                                        │                    │
│                                                        ▼                    │
│                                               ┌──────────────┐              │
│                                               │   CONFIDENT? │              │
│                                               └──────────────┘              │
│                                                 │          │                │
│                                            LOW  │          │ HIGH           │
│                                                 ▼          ▼                │
│                                          ┌─────────┐  ┌─────────┐          │
│                                          │   ASK   │  │ EXECUTE │          │
│                                          │  USER   │  │  QUERY  │          │
│                                          └─────────┘  └─────────┘          │
│                                               │            │                │
│                                          [Explain]    [Explain]            │
│                                          "Multiple    "Querying            │
│                                           options,     Looker..."          │
│                                           which?"                          │
│                                               │            │                │
│                                               └─────┬──────┘                │
│                                                     ▼                       │
│                                              ┌───────────┐                  │
│                                              │  FORMAT   │                  │
│                                              │  RESULTS  │                  │
│                                              └───────────┘                  │
│                                                     │                       │
│                                                [Explain]                    │
│                                                "Here's a                    │
│                                                 summary..."                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                     ┌────────────────────────────────┐
                     │          LOOKER MCP            │
                     │                                │
                     │  generate_sql(                 │
                     │    model="sales",              │
                     │    explore="order_items",      │
                     │    dimensions=["region"],      │
                     │    measures=["total_sales"],   │
                     │    filters={...}               │
                     │  )                             │
                     │         ↓                      │
                     │  Returns deterministic SQL     │
                     │  (NO execution in this PoC)    │
                     └────────────────────────────────┘
```

---

## Final Graph Definition

This is the complete LangGraph state machine for the PoC:

```
                                    START
                                      │
                                      ▼
                            ┌─────────────────┐
                            │    DISCOVER     │ ◄─── Run once at session start
                            │    PROJECT      │      Cache schema for session
                            └─────────────────┘
                                      │
                                      │ [Explain: "Found 3 models, 7 explores..."]
                                      ▼
                            ┌─────────────────┐
                            │    CLASSIFY     │ ◄─── What does user want?
                            │     INTENT      │
                            └─────────────────┘
                                      │
                                      │ [Explain: "You want to query sales data"]
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
       ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
       │   SCHEMA    │         │   QUERY     │         │   FIELD     │
       │   EXPLORE   │         │   BUILD     │         │   EXPLAIN   │
       └─────────────┘         └─────────────┘         └─────────────┘
              │                       │                       │
              │                       ▼                       │
              │               ┌─────────────┐                 │
              │               │   SELECT    │                 │
              │               │   MODEL     │                 │
              │               └─────────────┘                 │
              │                       │                       │
              │                       │ [Explain: "Best match: sales model"]
              │                       ▼                       │
              │               ┌─────────────┐                 │
              │               │   SELECT    │                 │
              │               │   FIELDS    │                 │
              │               └─────────────┘                 │
              │                       │                       │
              │                       │ [Explain: "Using region, total_sales"]
              │                       ▼                       │
              │               ┌─────────────┐                 │
              │               │ CONFIDENCE  │                 │
              │               │   CHECK     │                 │
              │               └─────────────┘                 │
              │                       │                       │
              │            ┌──────────┴──────────┐            │
              │            │                     │            │
              │         LOW│                     │HIGH        │
              │            ▼                     ▼            │
              │     ┌─────────────┐       ┌─────────────┐     │
              │     │  ASK USER   │       │  GENERATE   │     │
              │     │  CLARIFY    │       │    SQL      │     │
              │     └─────────────┘       └─────────────┘     │
              │            │                     │            │
              │            │ [User responds]     │ [Looker MCP]
              │            │                     │            │
              │            └──────────┬──────────┘            │
              │                       │                       │
              │                       ▼                       │
              │               ┌─────────────┐                 │
              └──────────────▶│   FORMAT    │◀────────────────┘
                              │   RESPONSE  │
                              └─────────────┘
                                      │
                                      │ [Show SQL + explanation]
                                      ▼
                                     END
```

### Node Descriptions

| Node | Purpose | Tools Used | Output |
|------|---------|------------|--------|
| **DISCOVER_PROJECT** | Load all models/explores/fields from Looker | `get_models`, `get_explores`, `get_dimensions`, `get_measures` | Cached schema |
| **CLASSIFY_INTENT** | Determine what user wants (query, explore schema, explain field) | None (LLM only) | Intent type |
| **SCHEMA_EXPLORE** | Show schema tree or explore details | None (uses cached schema) | Visual schema |
| **QUERY_BUILD** | Start building a query from NL | None | Entry to query flow |
| **SELECT_MODEL** | Pick which model(s) match the user's question | None (LLM + cached schema) | Selected model |
| **SELECT_FIELDS** | Map user intent to dimensions/measures | None (LLM + cached schema) | Field selections |
| **CONFIDENCE_CHECK** | Is the field mapping confident? | None | Route decision |
| **ASK_USER_CLARIFY** | Ask clarifying questions | None | Wait for user input |
| **GENERATE_SQL** | Get deterministic SQL from Looker | `query_sql` or equivalent | SQL string |
| **FIELD_EXPLAIN** | Explain a specific dimension/measure | None (uses cached schema) | Field details |
| **FORMAT_RESPONSE** | Format and present final output | None | User-facing response |

### State Schema (Final)

```python
from typing import TypedDict, Literal, Annotated
from langgraph.graph.message import add_messages

class ProjectSchema(TypedDict):
    """Cached schema from Looker - discovered once per session."""
    models: list[dict]           # [{name, label, explores: [...]}]
    explores: dict[str, dict]    # {explore_name: {dimensions, measures, ...}}


class FieldSelection(TypedDict):
    """Selected fields for a query."""
    model: str
    explore: str
    dimensions: list[str]
    measures: list[str]
    filters: dict[str, str]


class AgentState(TypedDict):
    """Complete state for the semantic layer agent."""

    # ─────────────────────────────────────────────────────────────────────
    # Conversation
    # ─────────────────────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]  # Full conversation history

    # ─────────────────────────────────────────────────────────────────────
    # Schema (session cached)
    # ─────────────────────────────────────────────────────────────────────
    project_schema: ProjectSchema | None     # All models/explores/fields
    schema_loaded: bool                      # Whether schema is cached

    # ─────────────────────────────────────────────────────────────────────
    # Intent
    # ─────────────────────────────────────────────────────────────────────
    intent: Literal[
        "query",           # User wants to build a query / get SQL
        "schema_overview", # User wants to see available data
        "explore_details", # User wants details on an explore
        "field_explain",   # User wants to understand a field
        "clarify",         # Agent needs more info from user
    ] | None

    # ─────────────────────────────────────────────────────────────────────
    # Query Building
    # ─────────────────────────────────────────────────────────────────────
    field_selection: FieldSelection | None   # What we're querying
    confidence: float                        # 0.0 - 1.0, how sure are we?
    clarifying_questions: list[str]          # Questions to ask if uncertain

    # ─────────────────────────────────────────────────────────────────────
    # Output
    # ─────────────────────────────────────────────────────────────────────
    generated_sql: str | None                # SQL from Looker MCP
    explanation_trace: list[str]             # Step-by-step reasoning
    final_response: str | None               # Formatted response to user
```

### Graph Code (Final)

```python
from langgraph.graph import StateGraph, START, END

def create_semantic_layer_agent():
    """Create the DMP Semantic Layer Agent graph."""

    graph = StateGraph(AgentState)

    # ═══════════════════════════════════════════════════════════════════════
    # NODES
    # ═══════════════════════════════════════════════════════════════════════

    graph.add_node("discover_project", discover_project_node)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("schema_explore", schema_explore_node)
    graph.add_node("select_model", select_model_node)
    graph.add_node("select_fields", select_fields_node)
    graph.add_node("confidence_check", confidence_check_node)
    graph.add_node("ask_clarify", ask_clarify_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("field_explain", field_explain_node)
    graph.add_node("format_response", format_response_node)

    # ═══════════════════════════════════════════════════════════════════════
    # EDGES
    # ═══════════════════════════════════════════════════════════════════════

    # Start → Discover (if not cached) → Classify
    graph.add_edge(START, "discover_project")
    graph.add_edge("discover_project", "classify_intent")

    # Classify → Route by intent
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "query": "select_model",
            "schema_overview": "schema_explore",
            "explore_details": "schema_explore",
            "field_explain": "field_explain",
        }
    )

    # Query flow: Model → Fields → Confidence → SQL or Clarify
    graph.add_edge("select_model", "select_fields")
    graph.add_edge("select_fields", "confidence_check")

    graph.add_conditional_edges(
        "confidence_check",
        route_by_confidence,
        {
            "high": "generate_sql",
            "low": "ask_clarify",
        }
    )

    # After clarification → back to classify (user gave more info)
    graph.add_edge("ask_clarify", "classify_intent")

    # After SQL generation → format response
    graph.add_edge("generate_sql", "format_response")

    # Schema exploration → format response
    graph.add_edge("schema_explore", "format_response")
    graph.add_edge("field_explain", "format_response")

    # Response → End
    graph.add_edge("format_response", END)

    # ═══════════════════════════════════════════════════════════════════════
    # COMPILE
    # ═══════════════════════════════════════════════════════════════════════

    return graph.compile()


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def route_by_intent(state: AgentState) -> str:
    """Route to appropriate node based on classified intent."""
    return state["intent"]


def route_by_confidence(state: AgentState) -> str:
    """Route based on confidence in field selection."""
    if state["confidence"] >= 0.8:
        return "high"
    return "low"
```

### Multi-Turn Conversation Support

The agent remembers context for natural follow-ups:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Turn 1:                                                                     │
│  User: "Show me sales by region"                                             │
│  Agent: [discovers sales model, queries, shows results]                      │
│                                                                              │
│  Turn 2:                                                                     │
│  User: "Filter that to Q4 only"                                              │
│  Agent: [remembers previous query, adds Q4 filter, re-executes]              │
│         "Adding filter: created_date = Q4 2024 to your previous query..."    │
│                                                                              │
│  Turn 3:                                                                     │
│  User: "Also break it down by product category"                              │
│  Agent: [remembers both previous turns, adds dimension]                      │
│         "Adding dimension: product_category to your query..."                │
│                                                                              │
│  Turn 4:                                                                     │
│  User: "Now show me marketing spend for the same regions"                    │
│  Agent: [detects NEW model needed, but remembers region context]             │
│         "Switching to marketing model for ad spend data..."                  │
│         "Keeping your region filter: [North America, EMEA, APAC]"            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Schema Exploration & Visualization

Users can ask about the schema itself, not just query data:

**"What data is available?"** → Show visual schema tree

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📁 PROJECT: enterprise_analytics                                            │
│                                                                              │
│  ├── 📊 MODEL: sales                                                         │
│  │   │                                                                       │
│  │   ├── 🔍 EXPLORE: order_items                                             │
│  │   │   ├── 📐 Dimensions (12)                                              │
│  │   │   │   ├── order_items.order_id                                        │
│  │   │   │   ├── order_items.region                                          │
│  │   │   │   ├── order_items.product_category                                │
│  │   │   │   ├── order_items.created_date                                    │
│  │   │   │   └── ... (+8 more)                                               │
│  │   │   │                                                                   │
│  │   │   └── 📏 Measures (8)                                                 │
│  │   │       ├── order_items.total_sales                                     │
│  │   │       ├── order_items.order_count                                     │
│  │   │       ├── order_items.avg_order_value                                 │
│  │   │       └── ... (+5 more)                                               │
│  │   │                                                                       │
│  │   └── 🔍 EXPLORE: customers                                               │
│  │       ├── 📐 Dimensions (15)                                              │
│  │       └── 📏 Measures (6)                                                 │
│  │                                                                           │
│  ├── 📊 MODEL: marketing                                                     │
│  │   └── 🔍 EXPLORE: campaigns                                               │
│  │       ├── 📐 Dimensions (10)                                              │
│  │       └── 📏 Measures (12)                                                │
│  │                                                                           │
│  └── 📊 MODEL: finance                                                       │
│      └── 🔍 EXPLORE: gl_entries                                              │
│          ├── 📐 Dimensions (20)                                              │
│          └── 📏 Measures (15)                                                │
│                                                                              │
│  💡 Ask about any field: "What is total_sales?" or "Explain region"          │
│  💡 Drill into a model: "Show me the sales model" or "What's in order_items?"│
└─────────────────────────────────────────────────────────────────────────────┘
```

**"Show me the order_items explore"** → Detailed explore view

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔍 EXPLORE: order_items (in sales model)                                    │
│                                                                              │
│  📝 Description: "Individual line items from customer orders. Primary        │
│     source of revenue and product analytics."                                │
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════════│
│  📐 DIMENSIONS                                                               │
│  ═══════════════════════════════════════════════════════════════════════════│
│  │ Field                    │ Type     │ Description                        │
│  ├──────────────────────────┼──────────┼────────────────────────────────────│
│  │ order_items.order_id     │ string   │ Unique order identifier            │
│  │ order_items.region       │ string   │ Geographic sales region            │
│  │ order_items.product_cat  │ string   │ Product category (Electronics,     │
│  │                          │          │ Clothing, Home, etc.)              │
│  │ order_items.created_date │ date     │ Order creation timestamp           │
│  │ order_items.status       │ string   │ Order status (pending, shipped,    │
│  │                          │          │ delivered, cancelled)              │
│  │ order_items.customer_id  │ string   │ FK to customers explore            │
│  └──────────────────────────┴──────────┴────────────────────────────────────│
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════════│
│  📏 MEASURES                                                                 │
│  ═══════════════════════════════════════════════════════════════════════════│
│  │ Field                    │ Type     │ Description                        │
│  ├──────────────────────────┼──────────┼────────────────────────────────────│
│  │ order_items.total_sales  │ sum      │ Sum of sale_price across all items │
│  │ order_items.order_count  │ count    │ Count of distinct orders           │
│  │ order_items.avg_order_val│ average  │ Average revenue per order          │
│  │ order_items.gross_margin │ number   │ Total revenue minus COGS           │
│  └──────────────────────────┴──────────┴────────────────────────────────────│
│                                                                              │
│  💡 "Query total_sales by region" to use these fields                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**"What is total_sales?"** → Field explanation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📏 MEASURE: order_items.total_sales                                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Type:        SUM                                                     │    │
│  │ SQL:         SUM(${sale_price})                                      │    │
│  │ Description: "Total revenue from all order line items. Calculated    │    │
│  │              as the sum of individual item sale prices before        │    │
│  │              discounts or returns."                                  │    │
│  │                                                                      │    │
│  │ Used in:     order_items explore                                     │    │
│  │ Model:       sales                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  📊 COMMON USAGE PATTERNS:                                                   │
│  • "total_sales by region" - Revenue breakdown by geography                  │
│  • "total_sales by product_category" - Revenue by product type               │
│  • "total_sales over created_date" - Revenue trend over time                 │
│                                                                              │
│  🔗 RELATED MEASURES:                                                        │
│  • order_items.net_sales - Revenue after discounts                           │
│  • order_items.gross_margin - Revenue minus cost                             │
│  • order_items.avg_order_value - Per-order average                           │
│                                                                              │
│  💡 Try: "Show me total_sales by region for last quarter"                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**"What dimensions can I use with total_sales?"** → Compatibility view

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📏 total_sales can be grouped by these dimensions:                          │
│                                                                              │
│  📅 TIME DIMENSIONS:                                                         │
│  ├── created_date (date, date_week, date_month, date_quarter, date_year)     │
│  └── shipped_date (date, date_week, date_month)                              │
│                                                                              │
│  🌍 GEOGRAPHIC DIMENSIONS:                                                   │
│  ├── region (North America, EMEA, APAC, LATAM, ANZ)                          │
│  ├── country                                                                 │
│  └── city                                                                    │
│                                                                              │
│  📦 PRODUCT DIMENSIONS:                                                      │
│  ├── product_category (Electronics, Clothing, Home, Sports)                  │
│  ├── product_name                                                            │
│  └── brand                                                                   │
│                                                                              │
│  👤 CUSTOMER DIMENSIONS (via join):                                          │
│  ├── customer_segment (Enterprise, SMB, Consumer)                            │
│  └── customer_acquisition_source                                             │
│                                                                              │
│  💡 Example: "total_sales by region and product_category for Q4"             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Intent Types for Schema Exploration

```python
INTENTS = {
    # Data querying
    "query": "User wants to retrieve/analyze data",

    # Schema exploration
    "schema_overview": "Show full project structure (models, explores)",
    "explore_details": "Show details of a specific explore",
    "field_explain": "Explain what a dimension or measure means",
    "field_suggest": "Suggest which fields to use for a concept",

    # Clarification
    "clarify": "User query is ambiguous, need more info",
    "follow_up": "User is refining a previous query",
}
```

### SQL Output Formatting

When the agent generates SQL, it presents it with full context:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ✅ SQL GENERATED                                                            │
│                                                                              │
│  📋 YOUR QUESTION:                                                           │
│  "What were total sales by region for Q4?"                                   │
│                                                                              │
│  🎯 FIELD MAPPING:                                                           │
│  • "sales" → order_items.total_sales (SUM of sale_price)                     │
│  • "by region" → order_items.region (geographic dimension)                   │
│  • "Q4" → order_items.created_date BETWEEN Oct 1 - Dec 31                    │
│                                                                              │
│  📊 QUERY STRUCTURE:                                                         │
│  • Model: sales                                                              │
│  • Explore: order_items                                                      │
│  • Dimensions: [region]                                                      │
│  • Measures: [total_sales]                                                   │
│  • Filters: {created_date: "2024-Q4"}                                        │
│                                                                              │
│  💾 GENERATED SQL:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SELECT                                                              │    │
│  │    order_items.region AS "Region",                                   │    │
│  │    SUM(order_items.sale_price) AS "Total Sales"                      │    │
│  │  FROM schema.order_items AS order_items                              │    │
│  │  WHERE                                                               │    │
│  │    order_items.created_date >= '2024-10-01'                          │    │
│  │    AND order_items.created_date < '2025-01-01'                       │    │
│  │  GROUP BY 1                                                          │    │
│  │  ORDER BY 2 DESC                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  💡 This SQL was generated by Looker's semantic layer, not the AI agent.     │
│  💡 Copy this SQL to run in your preferred query tool.                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Schema-Grounded SQL Generation

**Problem:** LLMs hallucinate field names, table names, and SQL syntax.

**Solution:** The agent can ONLY reference fields it has discovered from the Looker MCP.

```
┌─────────────────────────────────────────────────────────────────┐
│                    SCHEMA GROUNDING FLOW                         │
│                                                                  │
│   1. DISCOVER: Call Looker MCP to get actual schema              │
│      get_explores() → get_dimensions() → get_measures()          │
│                           │                                      │
│                           ▼                                      │
│   2. CACHE: Store discovered schema in state                     │
│      state.discovered_schema = {                                 │
│        "explores": [...],                                        │
│        "dimensions": ["order_items.region", "order_items.date"], │
│        "measures": ["order_items.total_sales", ...]              │
│      }                                                           │
│                           │                                      │
│                           ▼                                      │
│   3. CONSTRAIN: LLM prompt includes ONLY discovered fields       │
│      "You may ONLY use these dimensions: {dimensions}"           │
│      "You may ONLY use these measures: {measures}"               │
│                           │                                      │
│                           ▼                                      │
│   4. VALIDATE: Check generated SQL against schema                │
│      Every field in SQL must exist in discovered_schema          │
│      If validation fails → retry with error feedback             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2. SafeChain Integration with LangGraph

**Challenge:** SafeChain's `MCPToolAgent` bundles LLM + tools. LangGraph wants to orchestrate.

**Solution:** Create a thin adapter that lets LangGraph invoke SafeChain for LLM calls.

```python
# Adapter pattern: LangGraph node calls SafeChain
class SafeChainAdapter:
    """Adapter to use SafeChain's LLM within LangGraph nodes."""

    def __init__(self, model_id: str, tools: list):
        self.agent = MCPToolAgent(model_id, tools)

    async def invoke(self, messages: list, allowed_tools: list[str] = None):
        """
        Invoke SafeChain with optional tool filtering.

        Args:
            messages: Conversation history
            allowed_tools: If provided, only allow these tools
                          (for schema-grounded generation)
        """
        # Filter tools if specified
        if allowed_tools:
            filtered_tools = [t for t in self.tools if t.name in allowed_tools]
            agent = MCPToolAgent(self.model_id, filtered_tools)
        else:
            agent = self.agent

        return await agent.ainvoke(messages)
```

### 3. Project Structure

```
src/
├── __init__.py
├── agent.py                 # Main entry point, creates the graph
├── state.py                 # AgentState TypedDict
├── adapter.py               # SafeChain adapter for LangGraph
│
├── nodes/                   # LangGraph node functions
│   ├── __init__.py
│   ├── classify.py          # Intent classification
│   ├── discover.py          # Schema discovery from Looker
│   ├── select.py            # Field selection for query
│   ├── generate.py          # SQL generation (schema-grounded)
│   └── validate.py          # SQL validation against schema
│
├── prompts/                 # Prompt templates
│   ├── __init__.py
│   ├── classifier.py        # Intent classification prompts
│   ├── selector.py          # Field selection prompts
│   └── generator.py         # SQL generation prompts
│
└── tools/                   # Tool configurations
    ├── __init__.py
    └── looker.py            # Looker MCP tool definitions
```

---

## State Schema

```python
from typing import TypedDict, Literal, Annotated
from langgraph.graph.message import add_messages

class DiscoveredSchema(TypedDict):
    """Schema discovered from Looker MCP."""
    model: str
    explores: list[dict]          # [{name, label, description}]
    dimensions: list[dict]        # [{name, type, label, description}]
    measures: list[dict]          # [{name, type, label, description}]
    filters: list[dict]           # Available filter fields


class AgentState(TypedDict):
    """State for the semantic layer agent."""

    # Conversation
    messages: Annotated[list, add_messages]

    # Intent
    intent: Literal["query", "schema_explore", "clarify"] | None

    # Schema (grounding)
    target_model: str                        # The specific Looker model
    target_explore: str | None               # Selected explore
    discovered_schema: DiscoveredSchema | None
    schema_cached: bool                      # Avoid re-discovering

    # Query building
    selected_dimensions: list[str]           # Fields chosen for SELECT
    selected_measures: list[str]             # Aggregations chosen
    selected_filters: dict[str, str]         # WHERE conditions

    # Output
    generated_sql: str | None
    validation_errors: list[str]
    validation_passed: bool

    # Response
    final_response: str | None
    explanation: str | None                  # How we built the query
```

---

## Graph Definition

```python
from langgraph.graph import StateGraph, START, END

def create_agent(safechain_adapter, target_model: str):
    """Create the semantic layer agent graph."""

    graph = StateGraph(AgentState)

    # ================================================================
    # NODES
    # ================================================================

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("discover_schema", discover_schema_node)
    graph.add_node("explore_schema", explore_schema_node)      # For "schema_explore" intent
    graph.add_node("select_fields", select_fields_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("format_response", format_response_node)

    # ================================================================
    # EDGES
    # ================================================================

    # Start → Classify
    graph.add_edge(START, "classify_intent")

    # Classify → Route by intent
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "query": "discover_schema",
            "schema_explore": "discover_schema",
            "clarify": "format_response",
        }
    )

    # Discover → Route by intent (schema is shared)
    graph.add_conditional_edges(
        "discover_schema",
        lambda s: s["intent"],
        {
            "query": "select_fields",
            "schema_explore": "explore_schema",
        }
    )

    # Schema explore → Response
    graph.add_edge("explore_schema", "format_response")

    # Query path: Select → Generate → Validate
    graph.add_edge("select_fields", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")

    # Validate → Retry or Respond
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validation,
        {
            "pass": "format_response",
            "retry": "generate_sql",      # Retry with error feedback
            "fail": "format_response",    # Give up, explain why
        }
    )

    # Response → End
    graph.add_edge("format_response", END)

    return graph.compile()
```

---

## Node Implementations

### 1. Classify Intent

```python
# nodes/classify.py

from prompts.classifier import CLASSIFICATION_PROMPT

async def classify_intent_node(state: AgentState, adapter: SafeChainAdapter) -> dict:
    """Classify user intent: query, schema_explore, or clarify."""

    messages = state["messages"]
    user_query = messages[-1].content

    # Use SafeChain LLM for classification
    result = await adapter.invoke([
        {"role": "system", "content": CLASSIFICATION_PROMPT},
        {"role": "user", "content": user_query},
    ])

    # Parse classification
    intent = parse_intent(result["content"])  # "query" | "schema_explore" | "clarify"

    return {
        "intent": intent,
    }
```

### 2. Discover Schema

```python
# nodes/discover.py

async def discover_schema_node(state: AgentState, adapter: SafeChainAdapter) -> dict:
    """Discover schema from Looker MCP. Cache to avoid repeated calls."""

    # Skip if already cached
    if state.get("schema_cached"):
        return {}

    target_model = state["target_model"]

    # Call Looker MCP tools via SafeChain
    # The adapter routes these to MCPToolAgent

    # 1. Get explores in the model
    explores_result = await adapter.invoke([
        {"role": "user", "content": f"Get all explores in model {target_model}"}
    ], allowed_tools=["get_explores"])

    explores = parse_explores(explores_result)

    # 2. For each explore, get dimensions and measures
    all_dimensions = []
    all_measures = []

    for explore in explores:
        dims = await adapter.invoke([
            {"role": "user", "content": f"Get dimensions for explore {explore['name']}"}
        ], allowed_tools=["get_dimensions"])

        measures = await adapter.invoke([
            {"role": "user", "content": f"Get measures for explore {explore['name']}"}
        ], allowed_tools=["get_measures"])

        all_dimensions.extend(parse_dimensions(dims))
        all_measures.extend(parse_measures(measures))

    return {
        "discovered_schema": {
            "model": target_model,
            "explores": explores,
            "dimensions": all_dimensions,
            "measures": all_measures,
        },
        "schema_cached": True,
    }
```

### 3. Generate SQL (Schema-Grounded)

```python
# nodes/generate.py

from prompts.generator import SQL_GENERATION_PROMPT

async def generate_sql_node(state: AgentState, adapter: SafeChainAdapter) -> dict:
    """Generate SQL using ONLY discovered schema fields."""

    schema = state["discovered_schema"]
    user_query = state["messages"][-1].content
    validation_errors = state.get("validation_errors", [])

    # Build the grounded prompt
    prompt = SQL_GENERATION_PROMPT.format(
        user_query=user_query,
        model=schema["model"],
        available_dimensions=format_fields(schema["dimensions"]),
        available_measures=format_fields(schema["measures"]),
        selected_dimensions=state["selected_dimensions"],
        selected_measures=state["selected_measures"],
        previous_errors="\n".join(validation_errors) if validation_errors else "None",
    )

    # Generate SQL via SafeChain
    result = await adapter.invoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Generate the SQL query."},
    ])

    sql = extract_sql(result["content"])

    return {
        "generated_sql": sql,
    }
```

### 4. Validate SQL

```python
# nodes/validate.py

def validate_sql_node(state: AgentState) -> dict:
    """Validate that generated SQL only uses discovered fields."""

    sql = state["generated_sql"]
    schema = state["discovered_schema"]

    # Extract field references from SQL
    referenced_fields = extract_field_references(sql)

    # Check each field exists in schema
    valid_fields = set(
        [d["name"] for d in schema["dimensions"]] +
        [m["name"] for m in schema["measures"]]
    )

    errors = []
    for field in referenced_fields:
        if field not in valid_fields:
            errors.append(f"Unknown field: {field}")

    # Also validate SQL syntax (basic checks)
    syntax_errors = validate_sql_syntax(sql)
    errors.extend(syntax_errors)

    return {
        "validation_errors": errors,
        "validation_passed": len(errors) == 0,
    }


def route_after_validation(state: AgentState) -> str:
    """Route based on validation result."""

    if state["validation_passed"]:
        return "pass"

    # Allow up to 2 retries
    retry_count = state.get("retry_count", 0)
    if retry_count < 2:
        return "retry"

    return "fail"
```

---

## Prompts

### Classification Prompt

```python
# prompts/classifier.py

CLASSIFICATION_PROMPT = """You are an intent classifier for a data query system.

Classify the user's message into one of these intents:

1. **query** - User wants to retrieve data or generate SQL
   Examples: "Show me sales by region", "What were total orders last month?"

2. **schema_explore** - User wants to understand the data model
   Examples: "What dimensions are available?", "Tell me about the orders table"

3. **clarify** - User's request is ambiguous or needs more information
   Examples: "Yes", "The second one", "More details please"

Respond with ONLY the intent name: query, schema_explore, or clarify
"""
```

### SQL Generation Prompt

```python
# prompts/generator.py

SQL_GENERATION_PROMPT = """You are a SQL generator for Looker.

## CRITICAL RULES
1. You may ONLY use fields from the provided schema
2. NEVER invent or guess field names
3. If a field doesn't exist, say so instead of guessing

## User Question
{user_query}

## Target Model
{model}

## Available Dimensions (you may ONLY use these)
{available_dimensions}

## Available Measures (you may ONLY use these)
{available_measures}

## Selected Fields for This Query
Dimensions: {selected_dimensions}
Measures: {selected_measures}

## Previous Validation Errors (if retrying)
{previous_errors}

Generate a Looker-compatible SQL query. Use the exact field names as shown above.
Output ONLY the SQL, wrapped in ```sql``` blocks.
"""
```

---

## Dependencies

```python
# requirements.txt additions

# LangGraph - orchestration framework
langgraph==0.2.50

# LangChain core (must match SafeChain's expected version)
langchain-core==0.3.83
```

---

## Questions to Resolve

Before implementation:

1. **Target Model Details**
   - Model name?
   - Key explores?
   - Sample dimensions/measures?

2. **Caching Strategy**
   - Cache schema in memory (session-level)?
   - Cache in Firestore (persistent)?
   - Cache expiry?

3. **Error Handling**
   - What if Looker MCP is unavailable?
   - What if the model doesn't exist?
   - Max retries for validation failures?

4. **Testing**
   - Unit tests for each node?
   - Integration tests with mock Looker?
   - End-to-end tests?

---

## Next Steps

1. [ ] Get target model details from Looker instance
2. [ ] Set up project structure (`src/`, `nodes/`, etc.)
3. [ ] Implement SafeChain adapter
4. [ ] Implement nodes one by one
5. [ ] Wire up the graph
6. [ ] Test with real Looker MCP
7. [ ] Iterate on prompts for accuracy

---

*Design v0.1 - Ready for review*
