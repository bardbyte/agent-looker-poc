"""Agent orchestrator and chat session.

Extracted from chat.py lines 218-650.

LLM access is always through safechain's MCPToolAgent.
Tools are optional — pass tool objects, MCP name strings, or omit entirely.
"""

import argparse
import asyncio
import sys
from typing import Any, Callable

from .thinking import (
    ThinkingCallback,
    ThinkingEvent,
    ThinkingType,
    ConsoleCallback,
    _wrap_callback,
)

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."

# Sentinel to distinguish "not provided" from "explicitly empty"
_UNSET = object()


class Agent:
    """ReAct agent loop with optional tool execution.

    LLM calls always go through safechain's MCPToolAgent.

    Tool binding modes:
        Agent()                                 # load ALL MCP tools (same as chat.py)
        Agent(tools=["ca", "get-models"])       # filter MCP tools by name
        Agent(tools=[my_tool_1, my_tool_2])     # bring your own LangChain tools
        Agent(tools=[])                         # no tools, pure LLM chat
    """

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        *,
        model: str | None = None,
        tools: list | None = _UNSET,
        max_iterations: int = 15,
        on_thinking: ThinkingCallback | Callable[[ThinkingEvent], None] | None = None,
    ):
        self.system_prompt = system_prompt
        self._model_override = model
        self.max_iterations = max_iterations

        if on_thinking is not None and not isinstance(on_thinking, ThinkingCallback):
            on_thinking = _wrap_callback(on_thinking)
        self.thinking_callback: ThinkingCallback | None = on_thinking

        # Determine what the caller passed
        self._raw_tools = tools
        if tools is _UNSET:
            # Not provided → load all MCP tools (matches chat.py default)
            self._mode = "mcp_all"
        elif tools is None or (isinstance(tools, list) and len(tools) == 0):
            # Explicitly empty → no tools, pure LLM
            self._mode = "none"
        elif isinstance(tools, list) and len(tools) > 0 and isinstance(tools[0], str):
            # List of name strings → filter MCP tools
            self._mode = "mcp_filter"
        else:
            # Tool objects → use directly, skip MCP bootstrap
            self._mode = "objects"

        # Resolved at first run
        self._agent = None
        self._tools: list = []
        self._model_id: str | None = None

    async def _ensure_ready(self) -> None:
        """Lazy init: resolve model + tools, create MCPToolAgent."""
        if self._agent is not None:
            return

        if self._mode == "objects":
            # Tool objects passed directly — skip MCP bootstrap
            self._tools = list(self._raw_tools)
            self._model_id = self._model_override

            # Resolve model from config if not overridden
            if not self._model_id:
                self._model_id = await self._resolve_model_from_config()

        elif self._mode == "none":
            # Explicit no-tools — skip MCP bootstrap
            self._tools = []
            self._model_id = self._model_override

            if not self._model_id:
                self._model_id = await self._resolve_model_from_config()

        else:
            # Need MCP bootstrap (mcp_all or mcp_filter)
            from . import _bootstrap
            await _bootstrap()
            from . import _mcp_tools as all_tools, _model_id as resolved_model

            self._model_id = self._model_override or resolved_model

            if self._mode == "mcp_filter":
                filter_set = set(self._raw_tools)
                self._tools = [t for t in all_tools if t.name in filter_set]
            else:
                # mcp_all — same as chat.py default
                self._tools = list(all_tools)

        from safechain.tools.mcp import MCPToolAgent
        self._agent = MCPToolAgent(self._model_id, self._tools)

    @staticmethod
    async def _resolve_model_from_config() -> str:
        """Try to get model ID from ee_config. Falls back to gemini-pro."""
        try:
            from dotenv import load_dotenv, find_dotenv
            load_dotenv(find_dotenv())
            from ee_config.config import Config
            config = Config.from_env()
            model = (
                getattr(config, "model_id", None)
                or getattr(config, "model", None)
                or getattr(config, "llm_model", None)
            )
            if model:
                return model
        except Exception as e:
            print(f"[liteagent] Could not load model from config: {e}", file=sys.stderr)
        return "gemini-pro"

    def _emit(self, event: ThinkingEvent) -> None:
        """Emit a thinking event if callback is configured."""
        if self.thinking_callback:
            self.thinking_callback.on_thinking(event)

    @staticmethod
    def _to_langchain_messages(messages: list[dict]) -> list:
        """Convert dict messages to LangChain message objects."""
        from langchain_core.messages import (
            HumanMessage, AIMessage, ToolMessage, SystemMessage,
        )

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

    async def run(self, messages: list[dict]) -> dict[str, Any]:
        """Run the ReAct orchestration loop.

        Args:
            messages: Conversation messages as dicts with 'role' and 'content'.

        Returns:
            Dict with 'content' (final answer) and 'thinking_events'.
        """
        await self._ensure_ready()

        # Ensure system message is present
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        thinking_events: list[ThinkingEvent] = []
        content = ""
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            agent_input = self._to_langchain_messages(messages)

            try:
                result = await self._agent.ainvoke(agent_input)
            except Exception as e:
                error_event = ThinkingEvent(
                    type=ThinkingType.ERROR,
                    content=f"Agent error: {e}",
                )
                self._emit(error_event)
                thinking_events.append(error_event)
                return {
                    "content": f"I encountered an error: {e}",
                    "thinking_events": thinking_events,
                }

            # Parse the result
            if isinstance(result, dict):
                content = result.get("content", "")
                tool_results = result.get("tool_results", [])
            else:
                content = getattr(result, "content", str(result))
                tool_results = []

            # If there were tool calls, process them and continue
            if tool_results:
                for tool_result in tool_results:
                    tool_name = tool_result.get("tool", "unknown")

                    self._emit(ThinkingEvent(
                        type=ThinkingType.TOOL_CALL,
                        content=f"Executing: {tool_name}",
                        metadata={"tool_name": tool_name},
                    ))

                    if "error" in tool_result:
                        event = ThinkingEvent(
                            type=ThinkingType.ERROR,
                            content=f"Error: {tool_result['error']}",
                            metadata={"tool_name": tool_name},
                        )
                    else:
                        result_str = str(tool_result.get("result", ""))
                        display = result_str[:500] + "..." if len(result_str) > 500 else result_str
                        event = ThinkingEvent(
                            type=ThinkingType.TOOL_RESULT,
                            content=display,
                            metadata={"tool_name": tool_name},
                        )

                    self._emit(event)
                    thinking_events.append(event)

                if content:
                    messages.append({"role": "assistant", "content": content})
                    self._emit(ThinkingEvent(type=ThinkingType.REASONING, content=content))

                for tool_result in tool_results:
                    tool_name = tool_result.get("tool", "unknown")
                    tool_content = (
                        f"Error: {tool_result['error']}"
                        if "error" in tool_result
                        else str(tool_result.get("result", ""))
                    )
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_content,
                        "tool_call_id": f"call_{iteration}_{tool_name}",
                    })

                continue

            # No tool calls — final answer
            if content:
                self._emit(ThinkingEvent(type=ThinkingType.FINAL_ANSWER, content=content))
                thinking_events.append(ThinkingEvent(type=ThinkingType.FINAL_ANSWER, content=content))

            return {
                "content": content,
                "thinking_events": thinking_events,
            }

        # Max iterations reached
        return {
            "content": f"Reached maximum iterations ({self.max_iterations}). Last response: {content}",
            "thinking_events": thinking_events,
        }

    async def run_prompt(self, prompt: str) -> dict[str, Any]:
        """Convenience: run a single user prompt.

        Args:
            prompt: The user's message string.

        Returns:
            Same dict as run().
        """
        return await self.run([{"role": "user", "content": prompt}])


class Chat:
    """Interactive chat session with conversation history.

    Equivalent to chat.py's ChatSession.
    """

    def __init__(self, agent: Agent):
        self.agent = agent
        self.conversation_history: list[dict] = []

    def show_tools(self) -> None:
        """Display available tools."""
        print("\n" + "=" * 60)
        print("AVAILABLE TOOLS")
        print("=" * 60)

        tools = self.agent._tools or []
        if not tools:
            print("No tools bound.")
            print("=" * 60 + "\n")
            return

        for tool in tools:
            desc = tool.description[:55] + "..." if len(tool.description) > 55 else tool.description
            print(f"  - {tool.name}")
            print(f"    {desc}")

        print("\n" + "=" * 60)
        print(f"Total: {len(tools)} tools")
        print("=" * 60 + "\n")

    def show_help(self) -> None:
        """Display help information."""
        print("""
\u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e
\u2502                     CHAT COMMANDS                           \u2502
\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2524
\u2502  /tools   - List available tools                            \u2502
\u2502  /clear   - Clear conversation history                      \u2502
\u2502  /help    - Show this help message                          \u2502
\u2502  /quit    - Exit the chat                                   \u2502
\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f
""")

    def clear(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        print("\n[Conversation history cleared]\n")

    async def send(self, message: str) -> str:
        """Send a message and get a response.

        Args:
            message: The user's message.

        Returns:
            The agent's response string.
        """
        messages = self.conversation_history + [{"role": "user", "content": message}]

        print()  # Space before thinking output
        result = await self.agent.run(messages)
        final_answer = result.get("content", "I couldn't generate a response.")

        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": final_answer})

        # Keep history manageable (last 20 messages)
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return final_answer

    async def start(self) -> None:
        """Run the interactive CLI chat loop."""
        await self.agent._ensure_ready()

        print("""
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551            liteagent \u2014 Interactive Chat                      \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
""")

        self.show_tools()
        self.show_help()

        print("Type your question or command. Use /quit to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() == "/quit":
                    print("\nGoodbye!")
                    break
                elif user_input.lower() == "/tools":
                    self.show_tools()
                    continue
                elif user_input.lower() == "/clear":
                    self.clear()
                    continue
                elif user_input.lower() == "/help":
                    self.show_help()
                    continue

                try:
                    response = await self.send(user_input)
                    print(f"\n{'─' * 60}")
                    print(f"Assistant: {response}")
                    print(f"{'─' * 60}\n")
                except Exception as e:
                    print(f"\nError: {e}")
                    import traceback
                    traceback.print_exc()
                    print()

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except EOFError:
                print("\n\nGoodbye!")
                break


def _cli_entry() -> None:
    """CLI entry point with argparse."""
    parser = argparse.ArgumentParser(
        prog="liteagent",
        description="Lightweight agent with MCP tool orchestration",
    )
    parser.add_argument(
        "--system", "-s",
        default=DEFAULT_SYSTEM_PROMPT,
        help="System prompt for the agent",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model ID override (default: from config)",
    )
    args = parser.parse_args()

    agent = Agent(
        system_prompt=args.system,
        model=args.model,
        on_thinking=ConsoleCallback(use_rich=True),
    )
    chat = Chat(agent)
    asyncio.run(chat.start())
