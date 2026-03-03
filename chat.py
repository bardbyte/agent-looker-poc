#!/usr/bin/env python3
"""
DMP-SL-Agent: Data Marketplace Semantic Layer Agent.

Interactive CLI chatbot that demonstrates:
1. Agentic multi-turn reasoning with MCP tools
2. Persistent conversation memory
3. Real-time thinking visualization
4. Autonomous tool orchestration

Usage:
    python -m examples.cli_chat

Commands:
    /tools    - List available tools
    /clear    - Clear conversation history
    /help     - Show help
    /quit     - Exit the chat

Requirements:
    - safechain library (LLM access & MCP tool binding)
    - ee_config library
    - .env file with credentials
    - MCP servers running (e.g., Looker MCP)
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from dotenv import load_dotenv, find_dotenv

# LLM access and MCP tool binding
from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
from ee_config.config import Config


# ============================================================================
# Configuration
# ============================================================================

# Load environment variables
load_dotenv(find_dotenv())

SYSTEM_PROMPT = """You are a Looker analytics agent. You translate natural language questions into \
data answers by orchestrating Looker's semantic layer through MCP tools.

You do NOT write SQL. Looker generates deterministic SQL from its semantic model. Your job is to \
understand intent, select the right fields, and let the tools do the rest.

# Tool Selection Strategy

You have two paths to answer a data question. Choose based on confidence:

**Path A — `conversational-analytics`** (preferred for direct data questions)
Use when the user asks a concrete data question: "What is total revenue by region?" or \
"Show me top 10 customers by spend." This tool handles natural language → Looker query → results \
in one call. Start here. If it fails or returns unexpected results, fall back to Path B.

**Path B — Manual exploration** (for ambiguous questions, schema discovery, or when Path A fails)
1. `get-models` → find the right model
2. `get-explores` → find the right explore within that model
3. `get-dimensions` + `get-measures` → map the user's business terms to Looker field names
4. `query` or `query-sql` → execute with the correct fields
5. Present results with the generated SQL

Use Path B when:
- The user asks "what data is available?" or "what can I query?"
- `conversational-analytics` returned an error or wrong data
- You need to disambiguate between multiple explores or fields
- The user explicitly asks about schema, models, or LookML structure

# Other Tool Groups

- **Saved content**: `get-looks`, `run-look`, `get-dashboards`, `run-dashboard` — when users ask \
about existing reports or dashboards
- **Content creation**: `make-look`, `make-dashboard`, `add-dashboard-element` — when users want \
to save or visualize results
- **LookML projects**: `get-projects`, `get-project-files`, `get-project-file` — when users ask \
about model definitions, view files, or field logic
- **Database connections**: `get-connections`, `get-connection-tables`, \
`get-connection-table-columns` — when users ask about underlying database structure
- **Health**: `health-pulse`, `health-analyze`, `health-vacuum` — for instance diagnostics

# How to Respond

1. **Show your work.** State which model/explore/fields you chose and why. If you used \
`conversational-analytics`, say so.
2. **Show the SQL.** Always include the generated SQL in a code block so the user can verify.
3. **Show the data.** Present results in a table or structured format when possible.
4. **Be honest about failures.** If a tool errors, if you're unsure about field mapping, or if \
the data looks wrong — say so. Offer to try a different approach.
5. **Never fabricate field names, explore names, or data.** If you're not sure a field exists, \
look it up with `get-dimensions` / `get-measures` first.
6. **Handle ambiguity explicitly.** If "revenue" could map to `total_revenue`, `net_revenue`, or \
`gross_revenue`, tell the user what you found and which one you picked.

# Multi-turn Context

You maintain conversation history. If the user says "now break that down by month" or "filter \
that to just California", apply it to the previous query context. Don't re-discover the schema \
from scratch — reuse what you already know from earlier turns."""


# ============================================================================
# Thinking Events - For Real-time Visualization
# ============================================================================

class ThinkingType(str, Enum):
    """Types of thinking events for visualization."""
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class ThinkingEvent:
    """Represents a thinking event from the agent."""
    type: ThinkingType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ThinkingCallback(ABC):
    """Abstract callback for receiving thinking events."""

    @abstractmethod
    def on_thinking(self, event: ThinkingEvent) -> None:
        """Called when a thinking event occurs."""
        pass


class ConsoleThinkingCallback(ThinkingCallback):
    """Callback that prints thinking events to console with rich formatting."""

    def __init__(self, use_rich: bool = True):
        self.use_rich = use_rich
        self._console = None

        if use_rich:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                self.use_rich = False

    def on_thinking(self, event: ThinkingEvent) -> None:
        """Print thinking event to console."""
        if self.use_rich and self._console:
            self._print_rich(event)
        else:
            self._print_plain(event)

    def _print_rich(self, event: ThinkingEvent) -> None:
        """Print with rich formatting."""
        from rich.panel import Panel
        from rich.markdown import Markdown

        styles = {
            ThinkingType.REASONING: ("bold blue", "Thinking"),
            ThinkingType.TOOL_CALL: ("bold yellow", "Tool Call"),
            ThinkingType.TOOL_RESULT: ("bold green", "Tool Result"),
            ThinkingType.FINAL_ANSWER: ("bold cyan", "Answer"),
            ThinkingType.ERROR: ("bold red", "Error"),
        }

        style, title = styles.get(event.type, ("white", "Event"))

        if event.type == ThinkingType.TOOL_CALL:
            tool_name = event.metadata.get("tool_name", "unknown")
            title = f"Tool Call: {tool_name}"

        content = event.content
        if event.type in [ThinkingType.REASONING, ThinkingType.FINAL_ANSWER]:
            try:
                content = Markdown(event.content)
            except Exception:
                pass

        self._console.print(Panel(
            content,
            title=title,
            style=style,
            expand=False,
        ))

    def _print_plain(self, event: ThinkingEvent) -> None:
        """Print without rich formatting."""
        prefixes = {
            ThinkingType.REASONING: "[THINKING]",
            ThinkingType.TOOL_CALL: "[TOOL CALL]",
            ThinkingType.TOOL_RESULT: "[TOOL RESULT]",
            ThinkingType.FINAL_ANSWER: "[ANSWER]",
            ThinkingType.ERROR: "[ERROR]",
        }

        prefix = prefixes.get(event.type, "[EVENT]")

        if event.type == ThinkingType.TOOL_CALL:
            tool_name = event.metadata.get("tool_name", "unknown")
            prefix = f"[TOOL CALL: {tool_name}]"

        print(f"\n{prefix}")
        print("-" * 50)
        print(event.content)
        print("-" * 50)


# ============================================================================
# Agent Orchestrator - Agentic Loop with Tool Execution
# ============================================================================

class AgentOrchestrator:
    """
    Orchestration layer that wraps MCPToolAgent to provide multi-turn reasoning.

    MCPToolAgent does single-pass execution (LLM call → tool execution → return).
    This orchestrator adds the ReAct loop:

        User Query
            ↓
        ┌─────────────────┐
        │  MCPToolAgent   │ ← LLM + Tool Execution
        └─────────────────┘
            ↓
        Tool Results?
            ├─ YES → Add results to context → Loop back
            └─ NO  → Return final answer

    This enables multi-step reasoning:
    1. LLM decides to call get_models → gets results
    2. LLM sees results, calls get_explores → gets results
    3. LLM sees results, calls query → gets results
    4. LLM presents final answer (no more tool calls)
    """

    def __init__(
        self,
        model_id: str,
        tools: list,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = 15,
        thinking_callback: ThinkingCallback | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            model_id: The model identifier for the LLM.
            tools: List of tools loaded via MCPToolLoader.
            system_prompt: System prompt for the agent.
            max_iterations: Maximum LLM calls before stopping (prevents infinite loops).
            thinking_callback: Optional callback for real-time thinking visualization.
        """
        self.model_id = model_id
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.thinking_callback = thinking_callback

        # Create the MCPToolAgent with tool bindings
        self.agent = MCPToolAgent(model_id, tools)

    def _emit(self, event: ThinkingEvent) -> None:
        """Emit a thinking event if callback is configured."""
        if self.thinking_callback:
            self.thinking_callback.on_thinking(event)

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

    async def run(self, messages: list[dict]) -> dict:
        """
        Run the ReAct orchestration loop.

        Args:
            messages: List of conversation messages as dicts with 'role' and 'content'.

        Returns:
            Dict with:
                - 'content': The final answer string
                - 'thinking_events': List of ThinkingEvent objects
        """
        # Ensure system message is present
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        thinking_events = []
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            # Convert to LangChain message format for the agent
            agent_input = self._to_langchain_messages(messages)

            # Call MCPToolAgent - it handles LLM call and tool execution
            try:
                result = await self.agent.ainvoke(agent_input)
            except Exception as e:
                error_event = ThinkingEvent(
                    type=ThinkingType.ERROR,
                    content=f"Agent error: {str(e)}",
                )
                self._emit(error_event)
                thinking_events.append(error_event)
                return {
                    "content": f"I encountered an error: {str(e)}",
                    "thinking_events": thinking_events,
                }

            # Parse the result
            if isinstance(result, dict):
                content = result.get("content", "")
                tool_results = result.get("tool_results", [])
            else:
                # Result might be an AIMessage or string
                content = getattr(result, "content", str(result))
                tool_results = []

            # If there were tool calls, process them and continue the loop
            if tool_results:
                for tool_result in tool_results:
                    tool_name = tool_result.get("tool", "unknown")

                    # Emit tool call event
                    self._emit(ThinkingEvent(
                        type=ThinkingType.TOOL_CALL,
                        content=f"Executing: {tool_name}",
                        metadata={"tool_name": tool_name},
                    ))

                    # Emit tool result event
                    if "error" in tool_result:
                        event = ThinkingEvent(
                            type=ThinkingType.ERROR,
                            content=f"Error: {tool_result['error']}",
                            metadata={"tool_name": tool_name},
                        )
                    else:
                        result_str = str(tool_result.get("result", ""))
                        # Truncate long results for display
                        display = result_str[:500] + "..." if len(result_str) > 500 else result_str
                        event = ThinkingEvent(
                            type=ThinkingType.TOOL_RESULT,
                            content=display,
                            metadata={"tool_name": tool_name},
                        )

                    self._emit(event)
                    thinking_events.append(event)

                # Add assistant's reasoning to messages (if any)
                if content:
                    messages.append({"role": "assistant", "content": content})
                    self._emit(ThinkingEvent(type=ThinkingType.REASONING, content=content))

                # Add tool results to messages for the next iteration
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

                # Continue loop - LLM will see tool results and decide next action
                continue

            # No tool calls - this is the final answer
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


# ============================================================================
# Chat Session - Conversation Management
# ============================================================================

class ChatSession:
    """Manages an interactive chat session with conversation history."""

    def __init__(self, orchestrator: AgentOrchestrator):
        self.orchestrator = orchestrator
        self.conversation_history: list[dict] = []

    def show_tools(self):
        """Display available MCP tools."""
        print("\n" + "=" * 60)
        print("AVAILABLE TOOLS")
        print("=" * 60)

        if not self.orchestrator.tools:
            print("No tools available.")
            return

        # Group tools by category
        categories = {
            "Models & Explores": [],
            "Fields": [],
            "Queries": [],
            "Looks & Dashboards": [],
            "Projects & Files": [],
            "Other": [],
        }

        for tool in self.orchestrator.tools:
            name = tool.name.lower()
            if "model" in name or "explore" in name:
                categories["Models & Explores"].append(tool)
            elif "dimension" in name or "measure" in name or "filter" in name:
                categories["Fields"].append(tool)
            elif "query" in name:
                categories["Queries"].append(tool)
            elif "look" in name or "dashboard" in name:
                categories["Looks & Dashboards"].append(tool)
            elif "project" in name or "file" in name:
                categories["Projects & Files"].append(tool)
            else:
                categories["Other"].append(tool)

        for category, tools in categories.items():
            if tools:
                print(f"\n{category}:")
                for tool in tools:
                    desc = tool.description[:55] + "..." if len(tool.description) > 55 else tool.description
                    print(f"  - {tool.name}")
                    print(f"    {desc}")

        print("\n" + "=" * 60)
        print(f"Total: {len(self.orchestrator.tools)} tools")
        print("=" * 60 + "\n")

    def show_help(self):
        """Display help information."""
        print("""
╭─────────────────────────────────────────────────────────────╮
│                     CHAT COMMANDS                           │
├─────────────────────────────────────────────────────────────┤
│  /tools   - List all available MCP tools                    │
│  /clear   - Clear conversation history                      │
│  /help    - Show this help message                          │
│  /quit    - Exit the chat                                   │
├─────────────────────────────────────────────────────────────┤
│                   EXAMPLE QUERIES                           │
├─────────────────────────────────────────────────────────────┤
│  "What models are available?"                               │
│  "Show me the explores in the ecommerce model"              │
│  "What dimensions are in the order_items explore?"          │
│  "Query total sales by region for last month"               │
│  "Show me total revenue by product category"                │
╰─────────────────────────────────────────────────────────────╯
""")

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print("\n[Conversation history cleared]\n")

    async def chat(self, user_input: str) -> str:
        """
        Send a message and get a response.

        Args:
            user_input: The user's message.

        Returns:
            The agent's response.
        """
        # Build messages with conversation history
        messages = self.conversation_history + [{"role": "user", "content": user_input}]

        print()  # Space before thinking output

        # Run the orchestrator
        result = await self.orchestrator.run(messages)

        # Extract the final answer
        final_answer = result.get("content", "I couldn't generate a response.")

        # Update conversation history
        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": final_answer})

        # Keep history manageable (last 20 messages)
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return final_answer


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Run the interactive chat."""
    print("""
╔═════════════════════════════════════════════════════════════╗
║                                                             ║
║       DMP-SL-Agent - Semantic Layer Assistant               ║
║                                                             ║
║      Natural Language to SQL with Looker & Gemini           ║
║                                                             ║
╚═════════════════════════════════════════════════════════════╝
""")

    # Step 1: Load configuration
    print("[1/3] Loading configuration...")
    try:
        config = Config.from_env()
        print("      ✓ Configuration loaded")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        print("      Make sure .env file exists with required variables")
        return

    # Step 2: Load tools from MCP servers
    print("[2/3] Loading MCP tools...")
    try:
        tools = await MCPToolLoader.load_tools(config)
        print(f"      ✓ Loaded {len(tools)} tools")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        print("      Make sure MCP servers are running")
        return

    # Step 3: Initialize the orchestrator
    print("[3/3] Initializing agent...")

    # Get model_id from config
    model_id = (
        getattr(config, 'model_id', None) or
        getattr(config, 'model', None) or
        getattr(config, 'llm_model', None) or
        "gemini-pro"
    )

    thinking_callback = ConsoleThinkingCallback(use_rich=True)

    orchestrator = AgentOrchestrator(
        model_id=model_id,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        max_iterations=15,
        thinking_callback=thinking_callback,
    )
    print("      ✓ Agent ready")

    # Create chat session
    session = ChatSession(orchestrator)

    # Show tools and help on startup
    session.show_tools()
    session.show_help()

    # Main chat loop
    print("Type your question or command. Use /quit to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() == "/quit":
                print("\nGoodbye!")
                break
            elif user_input.lower() == "/tools":
                session.show_tools()
                continue
            elif user_input.lower() == "/clear":
                session.clear_history()
                continue
            elif user_input.lower() == "/help":
                session.show_help()
                continue

            # Chat with the agent
            try:
                response = await session.chat(user_input)
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


def run():
    """Entry point for the script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
