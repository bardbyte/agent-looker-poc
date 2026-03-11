"""liteagent — lightweight agent abstraction over MCP tools.

Core is a direct extraction of chat.py (AgentOrchestrator + ChatSession).
Framework adapters (adk, langgraph) are optional thin wrappers.

LLM access is always through safechain (MCPToolAgent).
Tools are optional — pass LangChain-compatible tool objects, MCP tool name
strings (filtered from auto-loaded MCP tools), or omit to load all MCP tools.
Pass tools=[] explicitly for pure LLM with no tools.
"""

from .thinking import (
    ThinkingEvent,
    ThinkingType,
    ThinkingCallback,
    ConsoleCallback,
)
from .agent import Agent, Chat

__all__ = [
    "Agent",
    "Chat",
    "ThinkingEvent",
    "ThinkingType",
    "ThinkingCallback",
    "ConsoleCallback",
]

# ---------------------------------------------------------------------------
# Lazy bootstrap — loads MCP tools & model from .env + config on first use.
# Called when Agent needs MCP tools (tools=None or tool name strings).
# Skipped when tool objects are passed directly or tools=[].
# ---------------------------------------------------------------------------

_mcp_tools = None
_model_id = None
_bootstrapped = False


async def _bootstrap():
    """Load MCP tools and model ID from environment. Called once lazily."""
    global _mcp_tools, _model_id, _bootstrapped
    if _bootstrapped:
        return

    import sys

    print("[1/3] Loading configuration...", file=sys.stderr)
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())

    from ee_config.config import Config
    config = Config.from_env()
    print("      done", file=sys.stderr)

    print("[2/3] Loading MCP tools...", file=sys.stderr)
    from safechain.tools.mcp import MCPToolLoader
    _mcp_tools = await MCPToolLoader.load_tools(config)
    print(f"      {len(_mcp_tools)} tools loaded", file=sys.stderr)

    print("[3/3] Resolving model...", file=sys.stderr)
    _model_id = (
        getattr(config, "model_id", None)
        or getattr(config, "model", None)
        or getattr(config, "llm_model", None)
        or "gemini-pro"
    )
    print(f"      {_model_id}", file=sys.stderr)

    _bootstrapped = True
