# Architecture Decision Record: Agent Orchestration Framework

**Status:** Proposed
**Date:** January 2025
**Author:** Platform Engineering
**Stakeholders:** Data Platform Leadership, ML Platform, Enterprise Architecture

---

## Executive Summary

This document evaluates **LangGraph** vs **Google Agent Development Kit (ADK)** for implementing the DMP Semantic Layer Agent — an intelligent system that enables natural language interaction with our enterprise data catalog via Looker.

**Recommendation: LangGraph**

While we are a Google Cloud shop, LangGraph is the superior choice for this use case. This is not a rejection of GCP — it's a recognition that **the best tool for complex stateful workflows happens to run excellently on GCP infrastructure**. We deploy LangGraph on Cloud Run, trace with Cloud Trace, and maintain our GCP-first posture while gaining critical capabilities that ADK cannot yet provide.

---

## Table of Contents

1. [The Problem We're Solving](#the-problem-were-solving)
2. [System Requirements](#system-requirements)
3. [Proposed Architecture](#proposed-architecture)
4. [Framework Comparison](#framework-comparison)
5. [Why LangGraph (Despite Being a GCP Shop)](#why-langgraph-despite-being-a-gcp-shop)
6. [LangGraph Implementation Design](#langgraph-implementation-design)
7. [ADK Implementation (For Comparison)](#adk-implementation-for-comparison)
8. [GCP Integration Strategy](#gcp-integration-strategy)
9. [Risk Analysis](#risk-analysis)
10. [Recommendation](#recommendation)

---

## The Problem We're Solving

Our data consumers fall into two personas with fundamentally different needs:

### Persona 1: Data Consumer (Analyst, Business User)
> "What were our top products by revenue last quarter?"

Needs:
- Natural language → SQL generation
- Schema discovery without knowing the data model
- Business term resolution ("revenue" → `order_items.total_sale_price`)
- Visualization of results

### Persona 2: Data Steward (Data Owner, Governance Lead)
> "I'm the steward for the Marketing BU. Update the description of the `campaign_roi` dimension to reflect our new attribution model."

Needs:
- View all models/tables under their jurisdiction
- Edit metadata (descriptions, labels, tags)
- AI-assisted suggestions for metadata enrichment
- Approval workflows before changes go live
- Git-driven persistence with audit trail

**The challenge:** These aren't two separate systems. They're two modes of the *same* agent, requiring:
- Intent classification and dynamic routing
- Stateful multi-turn conversations
- Human-in-the-loop approval gates
- Long-running workflows that survive session boundaries
- Full explainability and audit trails

---

## System Requirements

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Intent classification with confidence scoring | P0 | Route to correct workflow |
| Multi-model selection with user confirmation | P0 | Show top-N options, let user pick |
| Looker MCP tool orchestration | P0 | get_models, get_explores, query, etc. |
| Synchronous HITL approval (in-chat) | P0 | Quick confirmations during session |
| Asynchronous HITL approval (notifications) | P1 | Multi-stakeholder reviews |
| Git-driven LookML modifications | P0 | Audit trail, CI/CD integration |
| Direct Looker API for runtime metadata | P1 | Fast updates without git cycle |
| State persistence across sessions | P0 | Resume long-running workflows |
| Explainability at every step | P0 | Leadership/compliance requirement |
| Cloud Trace integration | P0 | Production observability |
| Vertex AI / Gemini models | P0 | Enterprise LLM access |

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                  │
│                    (CLI / Web UI / Slack Bot / API)                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LANGGRAPH ORCHESTRATOR                             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         STATE GRAPH                                   │   │
│  │                                                                       │   │
│  │    ┌─────────┐     ┌──────────────┐     ┌─────────────────────┐      │   │
│  │    │ INTAKE  │────▶│   CLASSIFY   │────▶│   ROUTE BY INTENT   │      │   │
│  │    └─────────┘     │    INTENT    │     └─────────────────────┘      │   │
│  │                    └──────────────┘              │                    │   │
│  │                                                  │                    │   │
│  │           ┌──────────────┬───────────┬──────────┴────────┐           │   │
│  │           ▼              ▼           ▼                   ▼           │   │
│  │    ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌─────────────┐     │   │
│  │    │  SCHEMA   │  │  QUERY    │  │ BIZ TERMS │  │  STEWARD    │     │   │
│  │    │ DISCOVERY │  │ GENERATOR │  │  LOOKUP   │  │  WORKFLOW   │     │   │
│  │    └───────────┘  └───────────┘  └───────────┘  └─────────────┘     │   │
│  │           │              │           │                   │           │   │
│  │           │              │           │          ┌────────┴────────┐  │   │
│  │           │              │           │          ▼                 │  │   │
│  │           │              │           │   ┌─────────────┐          │  │   │
│  │           │              │           │   │ EDIT META   │          │  │   │
│  │           │              │           │   └─────────────┘          │  │   │
│  │           │              │           │          │                 │  │   │
│  │           │              │           │          ▼                 │  │   │
│  │           │              │           │   ┌─────────────┐          │  │   │
│  │           │              │           │   │ AI SUGGEST  │          │  │   │
│  │           │              │           │   └─────────────┘          │  │   │
│  │           │              │           │          │                 │  │   │
│  │           │              │           │          ▼                 │  │   │
│  │           │              │           │   ┌─────────────┐          │  │   │
│  │           │              │           │   │   HITL      │◀── Interrupt
│  │           │              │           │   │  APPROVAL   │          │  │   │
│  │           │              │           │   └─────────────┘          │  │   │
│  │           │              │           │          │                 │  │   │
│  │           │              │           │          ▼                 │  │   │
│  │           │              │           │   ┌─────────────┐          │  │   │
│  │           │              │           │   │ GIT COMMIT  │          │  │   │
│  │           │              │           │   └─────────────┘          │  │   │
│  │           │              │           │          │                 │  │   │
│  │           ▼              ▼           ▼          ▼                 │  │   │
│  │    ┌─────────────────────────────────────────────────────────┐   │   │
│  │    │                    MODEL SELECTOR                        │   │   │
│  │    │         (Confidence scoring, user confirmation)          │   │   │
│  │    └─────────────────────────────────────────────────────────┘   │   │
│  │                              │                                    │   │
│  │                              ▼                                    │   │
│  │    ┌─────────────────────────────────────────────────────────┐   │   │
│  │    │                  RESPONSE GENERATOR                      │   │   │
│  │    │        (Viz / SQL / Text + Explainability)               │   │   │
│  │    └─────────────────────────────────────────────────────────┘   │   │
│  │                                                                   │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                      │                                    │
│  ┌───────────────────────────────────┴───────────────────────────────┐   │
│  │                      STATE PERSISTENCE                             │   │
│  │              (Firestore / Cloud SQL checkpointer)                  │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
            │ LOOKER MCP  │   │  GIT REPO   │   │ LOOKER API  │
            │   SERVER    │   │  (LookML)   │   │  (Direct)   │
            └─────────────┘   └─────────────┘   └─────────────┘
```

---

## Framework Comparison

### Head-to-Head Analysis

| Capability | LangGraph | Google ADK | Winner |
|------------|-----------|------------|--------|
| **Complex state machines** | Native graph primitives (nodes, edges, conditions) | Sequential agent with custom routing | LangGraph |
| **Human-in-the-loop** | Built-in `interrupt_before`, `interrupt_after` | Manual implementation required | LangGraph |
| **State persistence** | Native checkpointing to any backend | Custom state management | LangGraph |
| **Async workflows** | Native support with checkpointer resume | Limited | LangGraph |
| **GCP integration** | Via standard clients (works fine) | Native Vertex AI integration | ADK |
| **Observability** | LangSmith + Cloud Trace adapter | Native Cloud Trace | Tie |
| **MCP support** | Via LangChain tools | Native MCP integration | Tie |
| **Gemini models** | Via langchain-google-genai | Native | ADK |
| **Learning curve** | Moderate (graph concepts) | Lower (simpler model) | ADK |
| **Community/ecosystem** | Large, mature | Growing | LangGraph |
| **Production readiness** | Battle-tested | Newer | LangGraph |

### Complexity Mapping

```
                    Simple                              Complex
                      │                                    │
    ┌─────────────────┼────────────────────────────────────┼─────────────────┐
    │                 │                                    │                 │
    │   Single-turn   │   Multi-turn    Conditional   HITL workflows        │
    │   Q&A           │   with memory   branching     with persistence      │
    │                 │                                    │                 │
    │   ◄─── ADK sweet spot ───►                          │                 │
    │                 │                                    │                 │
    │                 │        ◄─────── LangGraph sweet spot ──────────►    │
    │                 │                                    │                 │
    └─────────────────┼────────────────────────────────────┼─────────────────┘
                      │                                    │
                      │            ▲                       │
                      │            │                       │
                      │      OUR SYSTEM                    │
                      │      IS HERE                       │
```

---

## Why LangGraph (Despite Being a GCP Shop)

### The Honest Assessment

Yes, we're a Google Cloud shop. Yes, ADK is Google's framework. But choosing tools based on vendor alignment rather than technical fit is how organizations make expensive mistakes.

**Here's the reality:**

1. **LangGraph runs perfectly on GCP**
   - Deploys to Cloud Run with zero friction
   - Uses Vertex AI Gemini models via `langchain-google-genai`
   - Integrates with Cloud Trace for observability
   - Persists state to Firestore or Cloud SQL

2. **ADK cannot do what we need (yet)**
   - No built-in HITL interrupt/resume patterns
   - No native state persistence across sessions
   - Complex conditional routing requires significant custom code
   - Async approval workflows would be entirely bespoke

3. **The gap is not cosmetic — it's structural**

   Our Data Steward workflow requires:
   ```
   User edits metadata → AI suggests improvements → HITL approval gate
        → (if approved) Git commit → Looker deployment
        → (if rejected) Return to edit with feedback
   ```

   In LangGraph, this is ~20 lines of graph definition.
   In ADK, this is a custom state machine we'd have to build and maintain.

4. **Future-proofing**
   - LangGraph's patterns are becoming industry standard
   - ADK will likely adopt similar patterns over time
   - Our team learns transferable skills either way

### The Business Case

| Factor | LangGraph | ADK |
|--------|-----------|-----|
| Time to MVP | 2-3 weeks | 5-6 weeks |
| Custom code for HITL | ~100 lines | ~800 lines |
| State persistence | Configuration | Custom implementation |
| Risk of bugs in workflow logic | Low (proven patterns) | Higher (custom code) |
| Maintenance burden | Low | Medium-High |

**Net:** LangGraph saves ~3 weeks of development time and reduces ongoing maintenance burden. The "GCP-native" benefit of ADK doesn't offset these concrete costs.

---

## LangGraph Implementation Design

### State Schema

```python
from typing import TypedDict, Literal, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # Conversation
    messages: Annotated[list, add_messages]

    # Intent classification
    intent: Literal["schema", "query", "business_terms", "steward"] | None
    intent_confidence: float

    # User context
    user_role: Literal["consumer", "steward"]
    user_bu: str | None  # Business unit for stewards

    # Model selection
    candidate_models: list[dict]  # [{model, score, reason}]
    selected_model: str | None
    user_confirmed_model: bool

    # Steward workflow
    pending_changes: list[dict]  # Metadata changes to apply
    ai_suggestions: list[dict]   # AI-generated improvement suggestions
    approval_status: Literal["pending", "approved", "rejected"] | None
    approval_type: Literal["sync", "async"] | None

    # Execution
    tool_results: list[dict]

    # Response
    response_type: Literal["viz", "sql", "text", "confirmation"]
    final_response: str | None
    explanation_trace: list[str]  # Step-by-step explainability
```

### Graph Definition

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.base import BaseCheckpointSaver

def create_semantic_layer_agent(checkpointer: BaseCheckpointSaver):
    """Create the DMP Semantic Layer Agent graph."""

    graph = StateGraph(AgentState)

    # ========================================================================
    # NODES
    # ========================================================================

    # Entry point: classify user intent
    graph.add_node("classify_intent", classify_intent_node)

    # Model selection (always shows options)
    graph.add_node("select_models", select_models_node)
    graph.add_node("confirm_model", confirm_model_node)  # HITL for model selection

    # Intent-specific workflows
    graph.add_node("schema_discovery", schema_discovery_node)
    graph.add_node("query_generator", query_generator_node)
    graph.add_node("business_terms", business_terms_node)

    # Steward workflow
    graph.add_node("steward_list_assets", steward_list_assets_node)
    graph.add_node("steward_edit_metadata", steward_edit_metadata_node)
    graph.add_node("steward_ai_suggest", steward_ai_suggest_node)
    graph.add_node("steward_approval", steward_approval_node)  # HITL
    graph.add_node("steward_git_commit", steward_git_commit_node)
    graph.add_node("steward_api_update", steward_api_update_node)

    # Response generation
    graph.add_node("generate_response", generate_response_node)

    # ========================================================================
    # EDGES
    # ========================================================================

    # Start → Intent classification
    graph.add_edge(START, "classify_intent")

    # Intent → Model selection (for most intents)
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "schema": "select_models",
            "query": "select_models",
            "business_terms": "select_models",
            "steward": "steward_list_assets",
        }
    )

    # Model selection → User confirmation (always)
    graph.add_edge("select_models", "confirm_model")

    # After model confirmation → Route to specific workflow
    graph.add_conditional_edges(
        "confirm_model",
        route_after_model_selection,
        {
            "schema": "schema_discovery",
            "query": "query_generator",
            "business_terms": "business_terms",
        }
    )

    # Consumer workflows → Response
    graph.add_edge("schema_discovery", "generate_response")
    graph.add_edge("query_generator", "generate_response")
    graph.add_edge("business_terms", "generate_response")

    # Steward workflow chain
    graph.add_edge("steward_list_assets", "steward_edit_metadata")
    graph.add_edge("steward_edit_metadata", "steward_ai_suggest")
    graph.add_edge("steward_ai_suggest", "steward_approval")

    # After approval → Persist changes
    graph.add_conditional_edges(
        "steward_approval",
        route_after_approval,
        {
            "approved_git": "steward_git_commit",
            "approved_api": "steward_api_update",
            "rejected": "steward_edit_metadata",  # Back to edit
        }
    )

    graph.add_edge("steward_git_commit", "generate_response")
    graph.add_edge("steward_api_update", "generate_response")

    # Response → End
    graph.add_edge("generate_response", END)

    # ========================================================================
    # COMPILE WITH CHECKPOINTER
    # ========================================================================

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["confirm_model", "steward_approval"],  # HITL points
    )
```

### HITL Implementation

```python
from langgraph.types import interrupt, Command

def confirm_model_node(state: AgentState) -> AgentState:
    """
    Present model options to user and wait for selection.

    This node is marked as interrupt_before, so execution pauses here
    and resumes when the user provides input.
    """
    candidates = state["candidate_models"]

    # Format options for user
    options_text = "\n".join([
        f"  [{i+1}] {m['model']} (confidence: {m['score']:.0%})\n"
        f"      Reason: {m['reason']}"
        for i, m in enumerate(candidates)
    ])

    # Interrupt and ask user
    user_selection = interrupt({
        "type": "model_selection",
        "message": f"I found these relevant models:\n\n{options_text}\n\n"
                   f"Which model should I use? (Enter number or 'none' to clarify)",
        "options": [m["model"] for m in candidates],
    })

    # Resume with user's choice
    selected_idx = int(user_selection) - 1
    selected_model = candidates[selected_idx]["model"]

    return {
        **state,
        "selected_model": selected_model,
        "user_confirmed_model": True,
        "explanation_trace": state["explanation_trace"] + [
            f"User selected model: {selected_model}"
        ],
    }


def steward_approval_node(state: AgentState) -> AgentState | Command:
    """
    Request approval for metadata changes.

    Supports both sync (in-chat) and async (notification) approval.
    """
    changes = state["pending_changes"]
    suggestions = state["ai_suggestions"]
    approval_type = state["approval_type"]

    if approval_type == "sync":
        # Synchronous: interrupt and wait
        approval = interrupt({
            "type": "approval_request",
            "message": format_approval_request(changes, suggestions),
            "actions": ["approve", "reject", "modify"],
        })

        if approval["action"] == "approve":
            return {
                **state,
                "approval_status": "approved",
                "explanation_trace": state["explanation_trace"] + [
                    "Changes approved by user"
                ],
            }
        elif approval["action"] == "reject":
            return {
                **state,
                "approval_status": "rejected",
                "explanation_trace": state["explanation_trace"] + [
                    f"Changes rejected. Reason: {approval.get('reason', 'No reason provided')}"
                ],
            }

    else:  # async
        # Create approval request, notify stakeholders, pause workflow
        request_id = create_approval_request(changes, suggestions, state["user_bu"])
        notify_stakeholders(request_id, state["user_bu"])

        # Interrupt with async context
        interrupt({
            "type": "async_approval",
            "request_id": request_id,
            "message": "Approval request created. You'll be notified when approved.",
        })

        # When resumed (via API callback), check approval status
        # This happens in a separate invocation after stakeholder approves
```

### Checkpointing for GCP

```python
from langgraph.checkpoint.base import BaseCheckpointSaver
from google.cloud import firestore

class FirestoreCheckpointer(BaseCheckpointSaver):
    """
    Persist LangGraph state to Firestore.

    Enables:
    - Workflow resumption after user responds to HITL
    - Async approval workflows spanning hours/days
    - Crash recovery
    """

    def __init__(self, collection: str = "langgraph_checkpoints"):
        self.db = firestore.Client()
        self.collection = self.db.collection(collection)

    def get(self, config: dict) -> dict | None:
        thread_id = config["configurable"]["thread_id"]
        doc = self.collection.document(thread_id).get()
        return doc.to_dict() if doc.exists else None

    def put(self, config: dict, checkpoint: dict) -> None:
        thread_id = config["configurable"]["thread_id"]
        self.collection.document(thread_id).set(checkpoint)

    def list(self, config: dict) -> list[dict]:
        # List all checkpoints for a thread (for history/debugging)
        ...
```

---

## ADK Implementation (For Comparison)

Here's how the same system would look in Google ADK — to illustrate why we're recommending LangGraph.

### ADK Agent Definition

```python
from google.adk import Agent, Tool
from google.adk.tools import FunctionTool

# ADK doesn't have native graph primitives, so we build a custom router
class SemanticLayerAgent:
    def __init__(self):
        self.agent = Agent(
            model="gemini-2.0-flash",
            tools=self._build_tools(),
            system_prompt=SYSTEM_PROMPT,
        )
        self.state = {}  # Manual state management
        self.approval_pending = False

    def _build_tools(self) -> list[Tool]:
        return [
            FunctionTool(self.classify_intent),
            FunctionTool(self.select_models),
            FunctionTool(self.get_schema),
            FunctionTool(self.generate_query),
            # ... all other tools
        ]

    async def run(self, user_input: str, session_id: str):
        # Load state from storage (manual)
        self.state = await self._load_state(session_id)

        # Check if we're resuming from HITL
        if self.state.get("awaiting_approval"):
            return await self._handle_approval_response(user_input)

        if self.state.get("awaiting_model_selection"):
            return await self._handle_model_selection(user_input)

        # Normal flow
        response = await self.agent.run(user_input)

        # Check if we need HITL (manual detection)
        if self._needs_model_confirmation(response):
            self.state["awaiting_model_selection"] = True
            self.state["pending_models"] = self._extract_models(response)
            await self._save_state(session_id)
            return self._format_model_options(self.state["pending_models"])

        if self._needs_approval(response):
            self.state["awaiting_approval"] = True
            self.state["pending_changes"] = self._extract_changes(response)
            await self._save_state(session_id)
            return self._format_approval_request(self.state["pending_changes"])

        # Save state and return
        await self._save_state(session_id)
        return response

    async def _handle_model_selection(self, user_input: str):
        """Handle user's model selection (manual HITL)"""
        # Parse user input
        # Update state
        # Resume agent
        # ... 50+ lines of custom code

    async def _handle_approval_response(self, user_input: str):
        """Handle approval/rejection (manual HITL)"""
        # Parse user input
        # If approved: commit to git
        # If rejected: return to edit mode
        # ... 80+ lines of custom code

    async def _load_state(self, session_id: str) -> dict:
        """Load state from Firestore (manual persistence)"""
        # ... 20+ lines

    async def _save_state(self, session_id: str):
        """Save state to Firestore (manual persistence)"""
        # ... 20+ lines
```

### The Comparison

| Aspect | LangGraph | ADK |
|--------|-----------|-----|
| **Graph definition** | Declarative nodes/edges | Implicit in code flow |
| **HITL interrupts** | `interrupt_before=["node"]` | Manual state flags + conditional logic |
| **State persistence** | `checkpointer=FirestoreCheckpointer()` | Manual load/save methods |
| **Conditional routing** | `add_conditional_edges(fn)` | if/elif chains in code |
| **Resume from HITL** | Automatic with checkpointer | Manual state restoration |
| **Async approvals** | Interrupt, resume via API | Custom webhook + state management |
| **Code complexity** | ~200 lines total | ~600+ lines total |
| **Bug surface area** | Low (declarative) | High (imperative) |

### Visual Comparison

**LangGraph:** The workflow IS the code
```python
graph.add_edge("suggest", "approval")
graph.add_conditional_edges("approval", route_fn, {"approved": "commit", "rejected": "edit"})
# Done. The graph handles state, interrupts, resumption.
```

**ADK:** The workflow is buried in conditionals
```python
if state.get("awaiting_approval"):
    if user_input.lower() == "approve":
        state["awaiting_approval"] = False
        result = await self._do_commit(state["pending_changes"])
        await self._save_state(session_id)
        return result
    elif user_input.lower() == "reject":
        state["awaiting_approval"] = False
        state["mode"] = "edit"
        await self._save_state(session_id)
        return "Returning to edit mode..."
# And this pattern repeats for every HITL point...
```

---

## GCP Integration Strategy

LangGraph integrates cleanly with GCP. Here's our deployment architecture:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GOOGLE CLOUD                                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         CLOUD RUN                                    │    │
│  │                                                                      │    │
│  │   ┌─────────────────────────────────────────────────────────────┐   │    │
│  │   │              LANGGRAPH APPLICATION                           │   │    │
│  │   │                                                              │   │    │
│  │   │   ┌────────────┐   ┌────────────┐   ┌────────────┐          │   │    │
│  │   │   │  FastAPI   │   │ LangGraph  │   │ MCP Client │          │   │    │
│  │   │   │   Server   │──▶│   Agent    │──▶│  (Looker)  │          │   │    │
│  │   │   └────────────┘   └────────────┘   └────────────┘          │   │    │
│  │   │                           │                                  │   │    │
│  │   └───────────────────────────┼──────────────────────────────────┘   │    │
│  │                               │                                       │    │
│  └───────────────────────────────┼───────────────────────────────────────┘    │
│                                  │                                            │
│         ┌────────────────────────┼────────────────────────┐                  │
│         ▼                        ▼                        ▼                  │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐            │
│  │  FIRESTORE  │         │ VERTEX AI   │         │ CLOUD TRACE │            │
│  │             │         │             │         │             │            │
│  │ Checkpoints │         │   Gemini    │         │   Traces    │            │
│  │ State       │         │   Models    │         │   Metrics   │            │
│  └─────────────┘         └─────────────┘         └─────────────┘            │
│                                                                              │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐            │
│  │ CLOUD       │         │   SECRET    │         │  CLOUD      │            │
│  │ STORAGE     │         │   MANAGER   │         │  LOGGING    │            │
│  │             │         │             │         │             │            │
│  │ LookML repo │         │ Credentials │         │  Audit logs │            │
│  └─────────────┘         └─────────────┘         └─────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integration Code

```python
# Vertex AI Gemini integration
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),  # Or via ADC
)

# Cloud Trace integration
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
trace.set_tracer_provider(provider)

# LangGraph with tracing
from langsmith import traceable

@traceable(run_type="chain")
async def run_agent(user_input: str, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    return await agent.ainvoke({"messages": [user_input]}, config)
```

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LangGraph breaking changes | Low | Medium | Pin versions, test upgrades in staging |
| LangSmith dependency | Medium | Low | Cloud Trace works independently |
| Team learning curve | Medium | Medium | 2-day workshop, pair programming |
| ADK matures and becomes better | Medium | Low | Migration path exists, patterns transfer |
| Firestore checkpointer issues | Low | High | Test thoroughly, have Cloud SQL backup |

---

## Recommendation

**Proceed with LangGraph.**

### Rationale

1. **Technical fit is compelling.** Our workflow requires stateful, interruptible, multi-path execution. LangGraph provides this natively; ADK requires us to build it.

2. **GCP integration is proven.** LangGraph + Cloud Run + Firestore + Vertex AI is a well-trodden path. We're not pioneering anything risky.

3. **Time-to-value matters.** 2-3 weeks vs 5-6 weeks is significant. We can iterate faster and learn faster.

4. **The "GCP shop" argument is about infrastructure, not libraries.** We use pandas, not a Google DataFrame library. We use FastAPI, not Cloud Endpoints. Using LangGraph while deploying on GCP is entirely consistent with being a GCP shop.

5. **If ADK matures, we can migrate.** The patterns (state machines, HITL, checkpointing) are transferable. We're not locked in.

### Next Steps

1. **Week 1:** Set up LangGraph with Firestore checkpointer, basic intent classification
2. **Week 2:** Implement consumer workflows (schema, query, business terms)
3. **Week 3:** Implement steward workflow with HITL
4. **Week 4:** Integration testing, observability, documentation

### Approval Requested

- [ ] Platform Engineering Lead
- [ ] ML Platform Lead
- [ ] Enterprise Architecture Review

---

*Document version: 1.0*
*Last updated: January 2025*
