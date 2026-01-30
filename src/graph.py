"""
LangGraph definition for the Semantic Layer Agent.

This module defines the state machine that orchestrates the agent's behavior.
"""

from langgraph.graph import StateGraph, START, END
from functools import partial

from .state import AgentState
from .adapter import SafeChainAdapter
from .nodes import (
    discover_project_node,
    classify_intent_node,
    select_model_node,
    select_fields_node,
    confidence_check_node,
    ask_clarify_node,
    generate_sql_node,
    schema_explore_node,
    field_explain_node,
    format_response_node,
)
from .nodes.confidence import route_by_confidence


def create_agent(adapter: SafeChainAdapter):
    """
    Create the Semantic Layer Agent graph.

    Args:
        adapter: SafeChainAdapter instance for LLM and tool access

    Returns:
        Compiled LangGraph StateGraph
    """
    graph = StateGraph(AgentState)

    # ═══════════════════════════════════════════════════════════════════════
    # NODES
    # Bind adapter to nodes that need it
    # ═══════════════════════════════════════════════════════════════════════

    graph.add_node(
        "discover_project",
        partial(_wrap_node, discover_project_node, adapter)
    )
    graph.add_node(
        "classify_intent",
        partial(_wrap_node, classify_intent_node, adapter)
    )
    graph.add_node(
        "select_model",
        partial(_wrap_node, select_model_node, adapter)
    )
    graph.add_node(
        "select_fields",
        partial(_wrap_node, select_fields_node, adapter)
    )
    graph.add_node(
        "confidence_check",
        partial(_wrap_node, confidence_check_node, None)
    )
    graph.add_node(
        "ask_clarify",
        partial(_wrap_node, ask_clarify_node, None)
    )
    graph.add_node(
        "generate_sql",
        partial(_wrap_node, generate_sql_node, adapter)
    )
    graph.add_node(
        "schema_explore",
        partial(_wrap_node, schema_explore_node, adapter)
    )
    graph.add_node(
        "field_explain",
        partial(_wrap_node, field_explain_node, adapter)
    )
    graph.add_node(
        "format_response",
        partial(_wrap_node, format_response_node, None)
    )

    # ═══════════════════════════════════════════════════════════════════════
    # EDGES
    # ═══════════════════════════════════════════════════════════════════════

    # Start → Discover schema (runs once, then cached)
    graph.add_edge(START, "discover_project")

    # Discover → Classify intent
    graph.add_edge("discover_project", "classify_intent")

    # Classify → Route by intent
    graph.add_conditional_edges(
        "classify_intent",
        _route_by_intent,
        {
            "query": "select_model",
            "follow_up": "select_model",
            "schema_overview": "schema_explore",
            "explore_details": "schema_explore",
            "field_explain": "field_explain",
        }
    )

    # Query flow: Model → Fields → Confidence check
    graph.add_edge("select_model", "select_fields")
    graph.add_edge("select_fields", "confidence_check")

    # Confidence check → Route by confidence
    graph.add_conditional_edges(
        "confidence_check",
        route_by_confidence,
        {
            "high": "generate_sql",
            "low": "ask_clarify",
        }
    )

    # SQL generation → Format response
    graph.add_edge("generate_sql", "format_response")

    # Clarification → End (user will respond, starting new invocation)
    graph.add_edge("ask_clarify", "format_response")

    # Schema exploration → Format response
    graph.add_edge("schema_explore", "format_response")

    # Field explanation → Format response
    graph.add_edge("field_explain", "format_response")

    # Format response → End
    graph.add_edge("format_response", END)

    # ═══════════════════════════════════════════════════════════════════════
    # COMPILE
    # ═══════════════════════════════════════════════════════════════════════

    return graph.compile()


async def _wrap_node(node_func, adapter, state: AgentState) -> dict:
    """
    Wrapper to handle async nodes and adapter injection.

    Args:
        node_func: The node function to call
        adapter: SafeChainAdapter (or None if not needed)
        state: Current agent state

    Returns:
        State updates from the node
    """
    import asyncio

    if adapter is not None:
        if asyncio.iscoroutinefunction(node_func):
            return await node_func(state, adapter)
        else:
            return node_func(state, adapter)
    else:
        if asyncio.iscoroutinefunction(node_func):
            return await node_func(state)
        else:
            return node_func(state)


def _route_by_intent(state: AgentState) -> str:
    """Route to appropriate node based on classified intent."""
    intent = state.get("intent", "query")

    # Handle errors
    if state.get("error"):
        return "query"  # Default to query flow

    return intent if intent in [
        "query",
        "follow_up",
        "schema_overview",
        "explore_details",
        "field_explain",
    ] else "query"
