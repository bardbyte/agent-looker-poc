#!/usr/bin/env python3
"""
DMP-SL-Agent V2 CLI: LangGraph-based Semantic Layer Agent.

Interactive CLI that demonstrates:
1. LangGraph orchestration with SafeChain LLM/tools
2. Schema discovery and caching
3. Natural language to SQL via Looker MCP
4. Full explainability at every step

Usage:
    python -m src.cli

Commands:
    /schema   - Show available data schema
    /explain  - Show last query's explanation trace
    /clear    - Clear conversation history
    /help     - Show help
    /quit     - Exit
"""

import asyncio
from typing import Optional
from dotenv import load_dotenv, find_dotenv

from langchain_core.messages import HumanMessage

from ee_config.config import Config

from .adapter import SafeChainAdapter
from .graph import create_agent
from .state import AgentState, create_initial_state


# Load environment variables
load_dotenv(find_dotenv())


class ChatSession:
    """Manages an interactive chat session with the LangGraph agent."""

    def __init__(self, agent, adapter: SafeChainAdapter):
        self.agent = agent
        self.adapter = adapter
        self.state: AgentState = create_initial_state()
        self.last_trace: list[str] = []

    async def chat(self, user_input: str) -> str:
        """
        Process user input and return agent response.

        Args:
            user_input: The user's message

        Returns:
            The agent's response
        """
        # Add user message to state
        messages = list(self.state.get("messages", []))
        messages.append(HumanMessage(content=user_input))

        # Create input state
        input_state = {
            **self.state,
            "messages": messages,
            "current_query": user_input,
            "final_response": None,
            "error": None,
        }

        # Run the graph
        try:
            result = await self.agent.ainvoke(input_state)

            # Update session state with results
            self.state = {
                **self.state,
                "messages": result.get("messages", messages),
                "project_schema": result.get("project_schema", self.state.get("project_schema")),
                "schema_loaded": result.get("schema_loaded", self.state.get("schema_loaded")),
            }

            # Store trace for /explain command
            self.last_trace = result.get("explanation_trace", [])

            # Get response
            response = result.get("final_response", "I couldn't generate a response.")
            return response

        except Exception as e:
            return f"❌ Error: {str(e)}"

    def show_trace(self) -> str:
        """Show the explanation trace from the last query."""
        if not self.last_trace:
            return "No trace available. Run a query first."

        lines = [
            "📜 **EXPLANATION TRACE**",
            "",
        ]
        for item in self.last_trace:
            lines.append(f"  {item}")

        return "\n".join(lines)

    def clear_history(self):
        """Clear conversation history (but keep schema cache)."""
        self.state = {
            **create_initial_state(),
            "project_schema": self.state.get("project_schema"),
            "schema_loaded": self.state.get("schema_loaded"),
        }
        self.last_trace = []


def show_help():
    """Display help information."""
    print("""
╭─────────────────────────────────────────────────────────────────╮
│                    DMP-SL-AGENT V2 COMMANDS                      │
├─────────────────────────────────────────────────────────────────┤
│  /schema    - Show available data schema                         │
│  /explain   - Show explanation trace from last query             │
│  /clear     - Clear conversation history                         │
│  /help      - Show this help message                             │
│  /quit      - Exit the chat                                      │
├─────────────────────────────────────────────────────────────────┤
│                      EXAMPLE QUERIES                             │
├─────────────────────────────────────────────────────────────────┤
│  "What data is available?"                                       │
│  "Show me the order_items explore"                               │
│  "What is total_revenue?"                                        │
│  "Show me total sales by region for Q4"                          │
│  "Filter that to just North America"                             │
╰─────────────────────────────────────────────────────────────────╯
""")


async def main():
    """Run the interactive CLI."""
    print("""
╔═════════════════════════════════════════════════════════════════╗
║                                                                   ║
║           DMP-SL-Agent V2 - LangGraph Edition                     ║
║                                                                   ║
║           Natural Language to SQL via Looker                      ║
║           Powered by LangGraph + SafeChain                        ║
║                                                                   ║
╚═════════════════════════════════════════════════════════════════╝
""")

    # Step 1: Load configuration
    print("[1/4] Loading configuration...")
    try:
        config = Config.from_env()
        print("      ✓ Configuration loaded")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        print("      Make sure .env file exists with required variables")
        return

    # Step 2: Create SafeChain adapter
    print("[2/4] Initializing SafeChain adapter...")
    try:
        adapter = SafeChainAdapter(config)
        print("      ✓ Adapter created")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        return

    # Step 3: Load MCP tools
    print("[3/4] Loading MCP tools...")
    try:
        tools = await adapter.load_tools()
        print(f"      ✓ Loaded {len(tools)} tools")
        tool_names = adapter.get_tool_names()
        print(f"      Tools: {', '.join(tool_names[:5])}{'...' if len(tool_names) > 5 else ''}")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        print("      Make sure MCP servers are running")
        return

    # Step 4: Create LangGraph agent
    print("[4/4] Creating LangGraph agent...")
    try:
        agent = create_agent(adapter)
        print("      ✓ Agent ready")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        return

    # Create chat session
    session = ChatSession(agent, adapter)

    # Show help
    show_help()

    # Main chat loop
    print("\nType your question or command. Use /quit to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() == "/quit":
                print("\nGoodbye!")
                break

            elif user_input.lower() == "/help":
                show_help()
                continue

            elif user_input.lower() == "/clear":
                session.clear_history()
                print("\n[Conversation history cleared]\n")
                continue

            elif user_input.lower() == "/explain":
                print()
                print(session.show_trace())
                print()
                continue

            elif user_input.lower() == "/schema":
                # Trigger schema overview
                user_input = "What data is available?"

            # Chat with the agent
            print()  # Space before response

            try:
                response = await session.chat(user_input)
                print("─" * 60)
                print(response)
                print("─" * 60)
                print()
            except Exception as e:
                print(f"\n❌ Error: {e}")
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
    """Entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
