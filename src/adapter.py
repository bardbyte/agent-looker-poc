"""
SafeChain Adapter for LangGraph.

This adapter wraps SafeChain's MCPToolAgent to work with LangGraph nodes.
It maintains the enterprise authentication and tool binding while allowing
LangGraph to orchestrate the flow.
"""

from typing import Any
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
from ee_config.config import Config


class SafeChainAdapter:
    """
    Adapter to use SafeChain's LLM and tools within LangGraph nodes.

    SafeChain handles:
    - Enterprise authentication (IdaaS/CIBIS)
    - LLM access (Gemini via Vertex AI)
    - MCP tool loading and binding

    This adapter provides:
    - Tool filtering by name (for intent-based loading)
    - Message format conversion
    - Clean interface for LangGraph nodes
    """

    def __init__(self, config: Config, model_id: str | None = None):
        """
        Initialize the adapter.

        Args:
            config: SafeChain configuration (from Config.from_env())
            model_id: Optional model ID override
        """
        self.config = config
        self.model_id = model_id or self._get_model_id(config)
        self._all_tools: list = []
        self._tools_loaded = False
        self._agent_cache: dict[str, MCPToolAgent] = {}

    def _get_model_id(self, config: Config) -> str:
        """Extract model ID from config."""
        return (
            getattr(config, 'model_id', None) or
            getattr(config, 'model', None) or
            getattr(config, 'llm_model', None) or
            "gemini-pro"
        )

    async def load_tools(self) -> list:
        """
        Load all available tools from MCP servers.

        Returns:
            List of tool objects
        """
        if not self._tools_loaded:
            self._all_tools = await MCPToolLoader.load_tools(self.config)
            self._tools_loaded = True
        return self._all_tools

    def get_tools(self) -> list:
        """Get all loaded tools."""
        return self._all_tools

    def get_tool_names(self) -> list[str]:
        """Get names of all loaded tools."""
        return [tool.name for tool in self._all_tools]

    def filter_tools(self, tool_names: list[str]) -> list:
        """
        Filter tools by name.

        Args:
            tool_names: List of tool names to include

        Returns:
            Filtered list of tool objects
        """
        return [t for t in self._all_tools if t.name in tool_names]

    def _get_agent(self, tool_names: list[str] | None = None) -> MCPToolAgent:
        """
        Get or create an MCPToolAgent with specific tools.

        Args:
            tool_names: Tools to include. If None, uses all tools.

        Returns:
            MCPToolAgent instance
        """
        # Create cache key
        cache_key = ",".join(sorted(tool_names)) if tool_names else "__all__"

        if cache_key not in self._agent_cache:
            tools = self.filter_tools(tool_names) if tool_names else self._all_tools
            self._agent_cache[cache_key] = MCPToolAgent(self.model_id, tools)

        return self._agent_cache[cache_key]

    def _to_langchain_messages(self, messages: list[dict]) -> list:
        """Convert dict messages to LangChain message objects."""
        lc_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
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

    async def invoke(
        self,
        messages: list[dict],
        tool_names: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Invoke SafeChain with messages and optional tool filtering.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tool_names: Optional list of tool names to allow (intent-based filtering)
            system_prompt: Optional system prompt to prepend

        Returns:
            Dict with 'content' and optionally 'tool_results'
        """
        # Prepend system prompt if provided
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        # Convert to LangChain format
        lc_messages = self._to_langchain_messages(messages)

        # Get appropriate agent
        agent = self._get_agent(tool_names)

        # Invoke
        result = await agent.ainvoke(lc_messages)

        # Parse result
        if isinstance(result, dict):
            return {
                "content": result.get("content", ""),
                "tool_results": result.get("tool_results", []),
            }
        else:
            return {
                "content": getattr(result, "content", str(result)),
                "tool_results": [],
            }

    async def invoke_tool(self, tool_name: str, **kwargs) -> Any:
        """
        Directly invoke a specific tool.

        Args:
            tool_name: Name of the tool to invoke
            **kwargs: Arguments to pass to the tool

        Returns:
            Tool result
        """
        tool = next((t for t in self._all_tools if t.name == tool_name), None)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        return await tool.ainvoke(kwargs)


# Tool sets for intent-based loading
TOOL_SETS = {
    "discovery": [
        "get_models",
        "get_explores",
        "get_dimensions",
        "get_measures",
    ],
    "query": [
        "query_sql",
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


def get_tools_for_intent(intent: str) -> list[str]:
    """
    Get tool names appropriate for a given intent.

    Args:
        intent: The classified intent

    Returns:
        List of tool names to load
    """
    intent_to_toolsets = {
        "query": ["discovery", "query"],
        "schema_overview": ["schema_explore"],
        "explore_details": ["schema_explore"],
        "field_explain": ["schema_explore"],
        "follow_up": ["discovery", "query"],
    }

    toolsets = intent_to_toolsets.get(intent, ["discovery"])
    tools = []
    for ts in toolsets:
        tools.extend(TOOL_SETS.get(ts, []))

    return list(set(tools))  # Deduplicate
