#!/usr/bin/env python3
"""
DMP-SL-Agent V2: Multi-Skill Data Steward Assistant for Looker.

A LangGraph agent with four specialized skills:
1. Schema Explorer - Explain data, fields, relationships
2. SQL Generator - Generate SQL via Looker's query_sql
3. Model Advisor - Analyze metadata, suggest optimizations
4. Data Dictionary - Suggest business terms, field descriptions

Focused on: prj-d-lumi-gpt project.
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


class Skill(str, Enum):
    """Available agent skills."""
    SCHEMA_EXPLORER = "schema_explorer"
    SQL_GENERATOR = "sql_generator"
    MODEL_ADVISOR = "model_advisor"
    DATA_DICTIONARY = "data_dictionary"
    CLARIFICATION = "clarification"


SKILL_DESCRIPTIONS = {
    Skill.SCHEMA_EXPLORER: "Explore and explain the data schema, fields, and relationships",
    Skill.SQL_GENERATOR: "Generate SQL queries using Looker's semantic layer",
    Skill.MODEL_ADVISOR: "Analyze model structure and suggest optimizations",
    Skill.DATA_DICTIONARY: "Explain and suggest business terms for fields",
}


SYSTEM_PROMPT = f"""You are a Data Steward Assistant for the Looker project: {TARGET_PROJECT}

## Your Mission
Help users understand, query, and optimize their semantic layer. You have FOUR specialized skills:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SKILL 1: SCHEMA EXPLORER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks: "What data is available?", "Show me the schema", "What fields exist?"

Your approach:
1. Use get_models to find models in {TARGET_PROJECT}
2. Use get_explores to list available explores
3. Use get_dimensions and get_measures to show fields
4. Explain relationships between explores and what questions each can answer

Output format:
- List explores with clear descriptions
- Group dimensions/measures by category
- Explain what business questions each explore can answer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 SKILL 2: SQL GENERATOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks: "Generate SQL for...", "Show me [metric] by [dimension]", "Query..."

Your approach:
1. Identify required dimensions, measures, and filters from the question
2. Use get_dimensions and get_measures to find exact field names
3. Use query_sql to generate SQL - LOOKER GENERATES IT, NOT YOU!
4. Explain what the SQL does

CRITICAL: NEVER write SQL yourself. Always use query_sql tool.

Output format:
- Show the generated SQL
- Explain each part (SELECT, FROM, WHERE, GROUP BY)
- Suggest follow-up queries if relevant

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛠️ SKILL 3: MODEL ADVISOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks: "Is my model optimal?", "What explores am I missing?", "Analyze my schema"

Your approach:
1. Fetch all explores, dimensions, and measures
2. Analyze the metadata for:
   - Field naming consistency (snake_case, prefixes)
   - Dimension vs measure balance
   - Missing aggregations (no count? no sum?)
   - Potential derived fields or calculated measures
   - Explore coverage gaps
3. Provide actionable recommendations

Output format:
- Current state summary
- Issues found (with severity: 🔴 High, 🟡 Medium, 🟢 Low)
- Specific recommendations with examples
- Questions the current model CAN answer well
- Questions the current model CANNOT answer (gaps)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📖 SKILL 4: DATA DICTIONARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks: "What does [field] mean?", "Suggest business terms", "Document this"

Your approach:
1. Fetch field metadata (dimensions/measures)
2. Analyze field names to infer meaning
3. Suggest business-friendly descriptions
4. Identify fields needing better documentation

Output format:
- Field name → Suggested business term
- Suggested description/documentation
- Related fields that should be documented together

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Available MCP Tools
- get_projects: List available projects
- get_project_files: See files in a project
- get_models: List LookML models
- get_explores: List explores in a model
- get_dimensions: Get dimensions for an explore
- get_measures: Get measures for an explore
- get_filters: Get available filters
- query_sql: Generate SQL for a query (CRITICAL for SQL generation!)

## Your Workflow

### Step 1: Identify Intent
Before taking action, determine which skill is needed:
- Schema questions → SCHEMA EXPLORER
- SQL/query/data requests → SQL GENERATOR
- Optimization/analysis requests → MODEL ADVISOR
- Documentation/term questions → DATA DICTIONARY
- Unclear → Try best effort, then ask for clarification

### Step 2: Announce Your Approach
Always tell the user:
"I'll use [SKILL NAME] to help with this. Here's my approach: [brief plan]"

### Step 3: Execute with Transparency
Show your thinking as you work. Use tools and explain results.

### Step 4: Deliver Structured Output
Format your response according to the skill's output format.

## Behavior Guidelines

1. **Best Effort First**: If the query is ambiguous, make your best interpretation and proceed.
   Only ask clarifying questions if you truly cannot determine intent after analysis.

2. **Always Explain**: Show your reasoning. Users should understand WHY you're doing each step.

3. **Be Proactive**: If you notice issues while working (e.g., missing measures), mention them.

4. **Stay Focused**: Only work with {TARGET_PROJECT}. Politely redirect if asked about other projects.

5. **Suggest Next Steps**: After answering, suggest related questions or actions.

## Response Style
- Use clear headers and formatting
- Show tool calls and their purposes
- Provide actionable insights, not just data dumps
- Be concise but thorough
"""


# ============================================================================
# State
# ============================================================================

class AgentState(TypedDict):
    """State for the multi-skill agent."""
    messages: Annotated[list, add_messages]
    current_skill: str | None
    schema_cache: dict | None
    thinking_trace: list[str]
    final_response: str | None


# ============================================================================
# Thinking Events
# ============================================================================

class ThinkingType(str, Enum):
    INTENT = "intent"
    SKILL = "skill"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ANALYSIS = "analysis"
    RECOMMENDATION = "recommendation"
    CLARIFICATION = "clarification"
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
    Multi-skill Data Steward Assistant for prj-d-lumi-gpt.

    Skills:
    - Schema Explorer: Explain data, fields, relationships
    - SQL Generator: Generate SQL via Looker's query_sql
    - Model Advisor: Analyze and suggest optimizations
    - Data Dictionary: Business terms and documentation
    """

    def __init__(self, config: Config = None):
        self.config = config or Config.from_env()
        self.tools = None
        self.agent = None
        self.schema_cache = None
        self.thinking_events: list[ThinkingEvent] = []
        self.console = None

    async def initialize(self):
        """Load tools and create agent."""
        self._init_console()

        self._print_step(1, 2, "Loading MCP tools...")
        self.tools = await MCPToolLoader.load_tools(self.config)
        self._print_success(f"Loaded {len(self.tools)} tools")

        self._print_step(2, 2, "Creating agent...")
        model_id = (
            getattr(self.config, 'model_id', None) or
            getattr(self.config, 'model', None) or
            "gemini-pro"
        )
        self.agent = MCPToolAgent(model_id, self.tools)
        self._print_success("Agent ready with 4 skills")

        self._display_skills()

    def _init_console(self):
        """Initialize rich console."""
        try:
            from rich.console import Console
            self.console = Console()
        except ImportError:
            self.console = None

    def _print_step(self, current: int, total: int, message: str):
        """Print a setup step."""
        print(f"[{current}/{total}] {message}")

    def _print_success(self, message: str):
        """Print success message."""
        print(f"      ✓ {message}")

    def _display_skills(self):
        """Display available skills."""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel

            console = Console()

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Skill", style="bold")
            table.add_column("Description")
            table.add_column("Trigger Examples", style="dim")

            table.add_row(
                "📊 Schema Explorer",
                "Explore data schema and relationships",
                '"What data is available?" "Show explores"'
            )
            table.add_row(
                "🔍 SQL Generator",
                "Generate SQL via Looker semantic layer",
                '"Generate SQL for..." "Show sales by region"'
            )
            table.add_row(
                "🛠️ Model Advisor",
                "Analyze and optimize model structure",
                '"Is my model optimal?" "What am I missing?"'
            )
            table.add_row(
                "📖 Data Dictionary",
                "Business terms and documentation",
                '"What does X mean?" "Suggest descriptions"'
            )

            console.print(Panel(table, title="Available Skills", border_style="blue"))

        except ImportError:
            print("\nAvailable Skills:")
            print("  📊 Schema Explorer - Explore data schema")
            print("  🔍 SQL Generator - Generate SQL queries")
            print("  🛠️ Model Advisor - Analyze model structure")
            print("  📖 Data Dictionary - Business terms")

    def _emit(self, event: ThinkingEvent):
        """Record and display thinking event."""
        self.thinking_events.append(event)
        self._display_event(event)

    def _display_event(self, event: ThinkingEvent):
        """Display thinking event with rich formatting."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text

            console = Console()

            styles = {
                ThinkingType.INTENT: ("magenta", "🎯 Intent Detected"),
                ThinkingType.SKILL: ("cyan", "⚡ Skill Activated"),
                ThinkingType.REASONING: ("blue", "💭 Thinking"),
                ThinkingType.TOOL_CALL: ("yellow", "🔧 Tool Call"),
                ThinkingType.TOOL_RESULT: ("green", "📋 Result"),
                ThinkingType.ANALYSIS: ("blue", "📊 Analysis"),
                ThinkingType.RECOMMENDATION: ("magenta", "💡 Recommendation"),
                ThinkingType.CLARIFICATION: ("yellow", "❓ Clarification Needed"),
                ThinkingType.FINAL_ANSWER: ("cyan", "✅ Answer"),
                ThinkingType.ERROR: ("red", "❌ Error"),
            }

            style, title = styles.get(event.type, ("white", "Event"))

            # Custom titles for specific events
            if event.type == ThinkingType.TOOL_CALL:
                title = f"🔧 {event.metadata.get('tool_name', 'Tool')}"
            elif event.type == ThinkingType.SKILL:
                skill_name = event.metadata.get('skill', 'Unknown')
                title = f"⚡ {skill_name}"

            # Truncate long content
            content = event.content
            if len(content) > 500:
                content = content[:500] + "\n... [truncated]"

            console.print(Panel(
                content,
                title=title,
                style=style,
                expand=False,
            ))

        except ImportError:
            # Fallback without rich
            prefix = {
                ThinkingType.INTENT: "🎯 INTENT",
                ThinkingType.SKILL: "⚡ SKILL",
                ThinkingType.REASONING: "💭 THINKING",
                ThinkingType.TOOL_CALL: "🔧 TOOL",
                ThinkingType.TOOL_RESULT: "📋 RESULT",
                ThinkingType.ANALYSIS: "📊 ANALYSIS",
                ThinkingType.RECOMMENDATION: "💡 RECOMMEND",
                ThinkingType.CLARIFICATION: "❓ CLARIFY",
                ThinkingType.FINAL_ANSWER: "✅ ANSWER",
                ThinkingType.ERROR: "❌ ERROR",
            }.get(event.type, "EVENT")

            print(f"\n[{prefix}] {event.content[:300]}")

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

    def _detect_skill(self, user_input: str) -> Skill:
        """Heuristic skill detection for display purposes."""
        input_lower = user_input.lower()

        # SQL Generator triggers
        sql_triggers = ["sql", "query", "generate", "show me", "get me", "fetch",
                       "how many", "total", "count", "sum", "average", "by"]
        if any(t in input_lower for t in sql_triggers):
            if "by" in input_lower or "how many" in input_lower:
                return Skill.SQL_GENERATOR

        # Model Advisor triggers
        advisor_triggers = ["optimal", "optimize", "missing", "improve", "analyze",
                          "review", "audit", "gaps", "suggestions", "recommend"]
        if any(t in input_lower for t in advisor_triggers):
            return Skill.MODEL_ADVISOR

        # Data Dictionary triggers
        dict_triggers = ["mean", "definition", "describe", "document", "business term",
                        "what is", "what does", "explain field"]
        if any(t in input_lower for t in dict_triggers):
            return Skill.DATA_DICTIONARY

        # Schema Explorer (default for exploration)
        schema_triggers = ["schema", "explore", "available", "fields", "dimensions",
                          "measures", "model", "what data", "show schema"]
        if any(t in input_lower for t in schema_triggers):
            return Skill.SCHEMA_EXPLORER

        # Default to schema explorer for ambiguous queries
        return Skill.SCHEMA_EXPLORER

    async def process(self, user_input: str, history: list[dict] = None) -> dict:
        """
        Process user input through the multi-skill agent.

        Returns:
            dict with 'response', 'thinking_events', and 'skill_used'
        """
        self.thinking_events = []
        history = history or []

        # Detect and display skill (heuristic - LLM makes final decision)
        detected_skill = self._detect_skill(user_input)
        self._emit(ThinkingEvent(
            type=ThinkingType.INTENT,
            content=f"Query: \"{user_input}\"\nDetected intent: {SKILL_DESCRIPTIONS.get(detected_skill, 'Unknown')}",
            metadata={"query": user_input}
        ))

        self._emit(ThinkingEvent(
            type=ThinkingType.SKILL,
            content=f"Activating {detected_skill.value.replace('_', ' ').title()} skill",
            metadata={"skill": detected_skill.value}
        ))

        # Build messages
        messages = history + [{"role": "user", "content": user_input}]

        max_iterations = 15  # Allow more iterations for complex analysis
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
                    "skill_used": detected_skill.value,
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
                        display = result_str[:400] + "..." if len(result_str) > 400 else result_str
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
                    # Detect if this is analysis or reasoning
                    event_type = ThinkingType.REASONING
                    if any(word in content.lower() for word in ["recommend", "suggest", "should", "could improve"]):
                        event_type = ThinkingType.ANALYSIS

                    self._emit(ThinkingEvent(
                        type=event_type,
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
                "skill_used": detected_skill.value,
            }

        return {
            "response": "Reached max iterations. The query may be too complex.",
            "thinking_events": self.thinking_events,
            "skill_used": detected_skill.value,
        }


# ============================================================================
# CLI
# ============================================================================

def print_banner():
    """Print the startup banner."""
    print("""
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║          DMP-SL-Agent V2 - Data Steward Assistant                         ║
║                                                                           ║
║          Project: prj-d-lumi-gpt                                          ║
║          Multi-Skill Semantic Layer Agent                                 ║
║                                                                           ║
║          Skills:                                                          ║
║            📊 Schema Explorer    🔍 SQL Generator                         ║
║            🛠️ Model Advisor      📖 Data Dictionary                       ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
""")


async def main():
    """Run the interactive CLI."""
    print_banner()

    # Initialize agent
    agent = LumiAgent()
    await agent.initialize()

    history = []

    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Commands:
  /clear  - Clear conversation history
  /skills - Show available skills
  /quit   - Exit

Example queries by skill:

  📊 Schema Explorer:
     "What data is available in this project?"
     "Show me the explores and their fields"

  🔍 SQL Generator:
     "Generate SQL to show total sales by region"
     "How many users signed up last month?"

  🛠️ Model Advisor:
     "Is my model structure optimal?"
     "What explores or measures am I missing?"

  📖 Data Dictionary:
     "What does the user_id field mean?"
     "Suggest business terms for my fields"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

    while True:
        try:
            user_input = input("\n🧑 You: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "/quit":
                print("\n👋 Goodbye!")
                break

            if user_input.lower() == "/clear":
                history = []
                print("\n🗑️  [History cleared]")
                continue

            if user_input.lower() == "/skills":
                agent._display_skills()
                continue

            print()  # Space before output

            result = await agent.process(user_input, history)

            # Update history
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result["response"]})

            # Keep history manageable
            if len(history) > 20:
                history = history[-20:]

            # Final response separator
            try:
                from rich.console import Console
                from rich.panel import Panel
                from rich.markdown import Markdown

                console = Console()
                console.print("\n")
                console.print(Panel(
                    Markdown(result["response"]),
                    title=f"🤖 Agent Response ({result.get('skill_used', 'unknown')})",
                    border_style="green",
                    expand=False,
                ))
            except ImportError:
                print("\n" + "═" * 70)
                print(f"🤖 Agent Response ({result.get('skill_used', 'unknown')}):")
                print("─" * 70)
                print(result["response"])
                print("═" * 70)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
