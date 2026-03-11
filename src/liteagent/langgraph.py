"""LangGraph adapter — exposes Agent as a LangGraph node or graph.

Usage:
    from liteagent.langgraph import as_node, as_graph

    # Option A: Use as a node in your own StateGraph
    node_fn = as_node(system_prompt="You are a Looker expert", tools=["get-models"])
    graph = StateGraph(MessagesState)
    graph.add_node("looker", node_fn)

    # Option B: Get a pre-built runnable graph
    graph = as_graph(system_prompt="You are a Looker expert")
    result = await graph.ainvoke({"messages": [HumanMessage(content="What models?")]})

Requires: pip install liteagent[langgraph]
"""

from __future__ import annotations

from typing import Any

from .agent import Agent


def _require_langgraph():
    try:
        import langgraph  # noqa: F401
    except ImportError:
        raise ImportError(
            "langgraph is required for the LangGraph adapter. "
            "Install it with: pip install liteagent[langgraph]"
        )


def as_node(
    system_prompt: str = "You are a helpful assistant.",
    *,
    tools: list | None = None,
    model: str | None = None,
    max_iterations: int = 15,
):
    """Return an async function suitable as a LangGraph node.

    The returned function takes MessagesState (dict with "messages" key)
    and returns updated state with the agent's response appended.
    """
    agent = Agent(
        system_prompt=system_prompt,
        model=model,
        tools=tools,
        max_iterations=max_iterations,
    )

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage, AIMessage

        # Convert LangChain messages to dicts
        messages = []
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": msg.content})
            elif isinstance(msg, dict):
                messages.append(msg)
            else:
                messages.append({"role": "user", "content": str(msg.content)})

        result = await agent.run(messages)
        answer = result.get("content", "")

        return {"messages": state.get("messages", []) + [AIMessage(content=answer)]}

    return _node


def as_graph(
    system_prompt: str = "You are a helpful assistant.",
    *,
    tools: list | None = None,
    model: str | None = None,
    max_iterations: int = 15,
):
    """Return a compiled LangGraph StateGraph with a single agent node.

    The graph accepts MessagesState and runs the agent's ReAct loop.
    """
    _require_langgraph()

    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import MessagesState

    node_fn = as_node(
        system_prompt=system_prompt,
        tools=tools,
        model=model,
        max_iterations=max_iterations,
    )

    graph = StateGraph(MessagesState)
    graph.add_node("agent", node_fn)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)

    return graph.compile()
