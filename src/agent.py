#!/usr/bin/env python3
"""
DMP-SL-Agent V2: Simplified LangGraph Agent for Looker.

A light LangGraph implementation that:
1. Discovers the project schema once
2. Uses SafeChain's MCPToolAgent for query processing (like chat.py)
3. Formats responses with explainability

Focused on: prj-d-lumi-gpt project, NL to SQL generation.
"""

import asyncio
import json
from typing import TypedDict, Annotated, Any
from dataclasses import dataclass, field
from enum import Enum

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from dotenv import load_dotenv, find_dotenv
from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
from ee_config.config import Config

load_dotenv(find_dotenv())


# ============================================================================
# Configuration
# ============================================================================

TARGET_PROJECT = "prj-d-lumi-gpt"

SYSTEM_PROMPT = f"""You are a data analyst assistant for the Looker project: {TARGET_PROJECT}

## Your Mission
Help users explore data and generate SQL queries using Looker's semantic layer.
You work ONLY with the {TARGET_PROJECT} project.

## Available Tools
You have access to Looker MCP tools:
- get_projects: List available projects
- get_project_files: See files in a project (views, models)
- get_models: List LookML models
- get_explores: List explores in a model
- get_dimensions: Get dimensions for an explore
- get_measures: Get measures for an explore
- get_filters: Get available filters
- query_sql: Generate SQL for a query (THIS IS KEY - use it to generate SQL!)

## Your Workflow

### For schema/data questions:
1. Use get_models to find the model in {TARGET_PROJECT}
2. Use get_explores to see available explores
3. Use get_dimensions/get_measures to show available fields
4. Explain clearly what data is available

### For data queries (NL to SQL):
1. First understand what the user wants (metrics, dimensions, filters)
2. Use get_dimensions and get_measures to find the right fields
3. Use query_sql to generate the SQL - Looker generates it, not you!
4. Present the SQL with clear explanation of what it does

## Critical Rules
1. ALWAYS use query_sql tool for SQL generation - NEVER write SQL yourself
2. ALWAYS explain your reasoning as you work
3. If unsure about field names, use get_dimensions/get_measures first
4. Focus only on {TARGET_PROJECT} project
5. Be concise but thorough

## Response Style
- Show your thinking process
- When showing SQL, explain what each part does
- Use formatting for readability
"""


# ============================================================================
# State
# ============================================================================

class AgentState(TypedDict):
    """Minimal state for the light LangGraph agent."""
    messages: Annotated[list, add_messages]
    schema_cache: dict | None  # Cached project schema
    schema_loaded: bool
    thinking_trace: list[str]  # For explainability
    final_response: str | None


# ============================================================================
# Thinking Events (from chat.py)
# ============================================================================

class ThinkingType(str, Enum):
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class ThinkingEvent:
    type: ThinkingType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Agent Core
# ============================================================================

class LumiAgent:
    """
    Simplified agent for prj-d-lumi-gpt project.

    Uses SafeChain for LLM + tools, with light LangGraph structure.
    """

    def __init__(self, config: Config = None):
        self.config = config or Config.from_env()
        self.tools = None
        self.agent = None
        self.schema_cache = None
        self.thinking_events: list[ThinkingEvent] = []

    async def initialize(self):
        """Load tools and create agent."""
        print("[1/2] Loading MCP tools...")
        self.tools = await MCPToolLoader.load_tools(self.config)
        print(f"      ✓ Loaded {len(self.tools)} tools")

        print("[2/2] Creating agent...")
        model_id = (
            getattr(self.config, 'model_id', None) or
            getattr(self.config, 'model', None) or
            "gemini-pro"
        )
        self.agent = MCPToolAgent(model_id, self.tools)
        print("      ✓ Agent ready")

    def _emit(self, event: ThinkingEvent):
        """Record and display thinking event."""
        self.thinking_events.append(event)
        self._display_event(event)

    def _display_event(self, event: ThinkingEvent):
        """Display thinking event to console."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            console = Console()

            styles = {
                ThinkingType.REASONING: ("blue", "💭 Thinking"),
                ThinkingType.TOOL_CALL: ("yellow", "🔧 Tool Call"),
                ThinkingType.TOOL_RESULT: ("green", "📋 Result"),
                ThinkingType.FINAL_ANSWER: ("cyan", "✅ Answer"),
                ThinkingType.ERROR: ("red", "❌ Error"),
            }

            style, title = styles.get(event.type, ("white", "Event"))
            if event.type == ThinkingType.TOOL_CALL:
                title = f"🔧 {event.metadata.get('tool_name', 'Tool')}"

            console.print(Panel(
                event.content[:500] + "..." if len(event.content) > 500 else event.content,
                title=title,
                style=style,
                expand=False,
            ))
        except ImportError:
            # Fallback without rich
            print(f"\n[{event.type.value}] {event.content[:200]}")

    def _to_langchain_messages(self, messages: list[dict]) -> list:
        """Convert dict messages to LangChain format."""
        lc_messages = [SystemMessage(content=SYSTEM_PROMPT)]

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
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

    async def process(self, user_input: str, history: list[dict] = None) -> dict:
        """
        Process user input through the ReAct loop.

        Returns:
            dict with 'response' and 'thinking_events'
        """
        self.thinking_events = []
        history = history or []

        # Build messages
        messages = history + [{"role": "user", "content": user_input}]

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Convert to LangChain format
            lc_messages = self._to_langchain_messages(messages)

            try:
                result = await self.agent.ainvoke(lc_messages)
            except Exception as e:
                self._emit(ThinkingEvent(
                    type=ThinkingType.ERROR,
                    content=f"Agent error: {str(e)}"
                ))
                return {
                    "response": f"Error: {str(e)}",
                    "thinking_events": self.thinking_events,
                }

            # Parse result
            if isinstance(result, dict):
                content = result.get("content", "")
                tool_results = result.get("tool_results", [])
            else:
                content = getattr(result, "content", str(result))
                tool_results = []

            # Process tool calls
            if tool_results:
                for tr in tool_results:
                    tool_name = tr.get("tool", "unknown")

                    self._emit(ThinkingEvent(
                        type=ThinkingType.TOOL_CALL,
                        content=f"Calling: {tool_name}",
                        metadata={"tool_name": tool_name}
                    ))

                    if "error" in tr:
                        self._emit(ThinkingEvent(
                            type=ThinkingType.ERROR,
                            content=f"Tool error: {tr['error']}"
                        ))
                    else:
                        result_str = str(tr.get("result", ""))
                        display = result_str[:300] + "..." if len(result_str) > 300 else result_str
                        self._emit(ThinkingEvent(
                            type=ThinkingType.TOOL_RESULT,
                            content=display
                        ))

                    # Add to messages
                    tool_content = tr.get("error", "") or str(tr.get("result", ""))
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_content,
                        "tool_call_id": f"call_{iteration}_{tool_name}",
                    })

                if content:
                    self._emit(ThinkingEvent(
                        type=ThinkingType.REASONING,
                        content=content
                    ))
                    messages.append({"role": "assistant", "content": content})

                continue

            # No tool calls - final answer
            if content:
                self._emit(ThinkingEvent(
                    type=ThinkingType.FINAL_ANSWER,
                    content=content
                ))

            return {
                "response": content,
                "thinking_events": self.thinking_events,
                "messages": messages,
            }

        return {
            "response": "Reached max iterations",
            "thinking_events": self.thinking_events,
        }


# ============================================================================
# CLI
# ============================================================================

async def main():
    """Run the interactive CLI."""
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                     ║
║          DMP-SL-Agent V2 - Lumi Project Assistant                   ║
║                                                                     ║
║          Project: prj-d-lumi-gpt                                    ║
║          NL to SQL via Looker Semantic Layer                        ║
║                                                                     ║
╚═══════════════════════════════════════════════════════════════════╝
""")

    # Initialize agent
    agent = LumiAgent()
    await agent.initialize()

    history = []

    print("""
Commands:
  /clear  - Clear conversation history
  /quit   - Exit

Example queries:
  "What data is available in this project?"
  "Show me the explores and their fields"
  "Generate SQL to show [your question]"
""")

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "/quit":
                print("\nGoodbye!")
                break

            if user_input.lower() == "/clear":
                history = []
                print("\n[History cleared]")
                continue

            print()  # Space before output

            result = await agent.process(user_input, history)

            # Update history
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result["response"]})

            # Keep history manageable
            if len(history) > 20:
                history = history[-20:]

            print("\n" + "─" * 60)
            print(f"Response: {result['response']}")
            print("─" * 60)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
