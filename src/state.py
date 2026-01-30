"""
State schema for the Semantic Layer Agent.

This defines the TypedDict that flows through the LangGraph state machine.
"""

from typing import TypedDict, Literal, Annotated
from langgraph.graph.message import add_messages


class ProjectSchema(TypedDict):
    """Schema discovered from Looker - cached for the session."""
    models: list[dict]           # [{name, label, explores: [...]}]
    explores: dict[str, dict]    # {explore_name: {model, dimensions, measures, description}}


class FieldSelection(TypedDict):
    """Selected fields for building a query."""
    model: str
    explore: str
    dimensions: list[str]
    measures: list[str]
    filters: dict[str, str]


class AgentState(TypedDict):
    """
    Complete state for the Semantic Layer Agent.

    This state flows through all nodes in the LangGraph.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Conversation (full history for multi-turn support)
    # ─────────────────────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ─────────────────────────────────────────────────────────────────────
    # Schema (session cached - loaded once at start)
    # ─────────────────────────────────────────────────────────────────────
    project_schema: ProjectSchema | None
    schema_loaded: bool

    # ─────────────────────────────────────────────────────────────────────
    # Current user query (extracted from last message)
    # ─────────────────────────────────────────────────────────────────────
    current_query: str | None

    # ─────────────────────────────────────────────────────────────────────
    # Intent classification
    # ─────────────────────────────────────────────────────────────────────
    intent: Literal[
        "query",            # User wants to build a query / get SQL
        "schema_overview",  # User wants to see available data
        "explore_details",  # User wants details on a specific explore
        "field_explain",    # User wants to understand a specific field
        "follow_up",        # User is refining a previous query
    ] | None

    # ─────────────────────────────────────────────────────────────────────
    # Query Building
    # ─────────────────────────────────────────────────────────────────────
    field_selection: FieldSelection | None
    confidence: float              # 0.0 - 1.0, how confident in field mapping
    clarifying_questions: list[str] | None  # Questions to ask if uncertain
    needs_clarification: bool

    # ─────────────────────────────────────────────────────────────────────
    # Output
    # ─────────────────────────────────────────────────────────────────────
    generated_sql: str | None
    explanation_trace: list[str]   # Step-by-step reasoning for explainability
    final_response: str | None

    # ─────────────────────────────────────────────────────────────────────
    # Error handling
    # ─────────────────────────────────────────────────────────────────────
    error: str | None


def create_initial_state() -> AgentState:
    """Create a fresh initial state for a new session."""
    return AgentState(
        messages=[],
        project_schema=None,
        schema_loaded=False,
        current_query=None,
        intent=None,
        field_selection=None,
        confidence=0.0,
        clarifying_questions=None,
        needs_clarification=False,
        generated_sql=None,
        explanation_trace=[],
        final_response=None,
        error=None,
    )
