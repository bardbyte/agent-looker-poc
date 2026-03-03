#!/usr/bin/env python3
"""
Conversational Analytics Agent — built on chat.py's agentic loop.

Repurposes chat.py's AgentOrchestrator + MCPToolAgent to interact with the
Looker MCP tools as a conversational analytics interface, then evaluates
the tool's functionality and accuracy through structured eval runs.

The eval flow:
  1. Schema Discovery — agent introspects the Looker project via MCP tools
  2. Query Generation — agent generates eval queries grounded in the real schema
  3. Eval Execution — each query runs through the agent independently
  4. Scoring — each response is scored on 7 metrics
  5. Report — aggregated results exported to JSON

Modes:
    Interactive:  python chat_ca.py                — chat with the CA agent
    Eval:         python chat_ca.py --eval         — full eval pipeline
    Custom:       python chat_ca.py --eval --eval-file queries.json

Commands (interactive mode):
    /tools    - List available MCP tools
    /clear    - Clear conversation history
    /eval     - Run evaluation pipeline
    /log      - Show the interaction log for this session
    /export   - Export interaction log to JSON
    /help     - Show help
    /quit     - Exit
"""

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, find_dotenv

# Reuse everything from chat.py — same agent, same MCP tools, same loop
from chat import (
    AgentOrchestrator,
    ChatSession,
    ConsoleThinkingCallback,
    ThinkingCallback,
    ThinkingEvent,
    ThinkingType,
)
from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
from ee_config.config import Config

load_dotenv(find_dotenv())

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# ============================================================================
# System Prompts
# ============================================================================

CA_SYSTEM_PROMPT = """You are a Conversational Analytics agent that translates natural language \
questions into Looker queries and returns data answers.

## Your Capabilities
You have access to Looker MCP tools that let you:
- Discover models, explores, dimensions, and measures
- Run queries and generate SQL
- Access saved Looks and Dashboards
- Read LookML project files

## Your Workflow

When a user asks a data question in natural language:

1. **Interpret**: Understand what data the user is asking for
2. **Discover**: Use `get-models` → `get-explores` to find the right explore
3. **Map Fields**: Use `get-dimensions` and `get-measures` to map the user's \
business terms to actual Looker fields
4. **Query**: Use `query` or `query-sql` with the mapped dimensions/measures
5. **Answer**: Present the data clearly, show the SQL, explain what you did

## Important
- Always show which model, explore, dimensions, and measures you chose and WHY
- Show the generated SQL
- If a question is ambiguous, explain the ambiguity and pick the most likely interpretation
- If you can't find matching fields, explain what you looked for and what was available
- Report any errors or unexpected results honestly"""

SCHEMA_DISCOVERY_PROMPT = """You are a schema discovery agent. Your job is to fully introspect \
the Looker instance and return a complete inventory of what's available.

Do the following in order:
1. Call `get-models` to list all models
2. For each model, call `get-explores` to list its explores
3. For each explore, call `get-dimensions` and `get-measures`

After you have gathered everything, respond with a structured summary in this EXACT format:

```json
{
  "models": [
    {
      "name": "model_name",
      "explores": [
        {
          "name": "explore_name",
          "dimensions": [
            {"name": "dim_name", "type": "string", "label": "Dim Label", "description": "..."}
          ],
          "measures": [
            {"name": "meas_name", "type": "count", "label": "Meas Label", "description": "..."}
          ]
        }
      ]
    }
  ]
}
```

Include ALL models, explores, dimensions, and measures. Do not skip any. \
Return ONLY the JSON block, no other text."""

QUERY_GENERATION_PROMPT = """You are an evaluation query generator. Given a Looker schema, \
generate natural language questions that a business user would ask.

## Schema
{schema_json}

## Requirements
Generate exactly {count} queries organized into these categories (roughly equal distribution):

1. **Discovery** — questions about what data/models/fields are available
2. **Simple aggregation** — single measure, no grouping or single grouping dimension
3. **Field mapping** — use business terms (not Looker field names) that the agent must map
4. **Time-based** — questions involving date dimensions, trends, recent data
5. **Multi-dimensional** — 2+ dimensions, comparisons, top-N
6. **Cross-explore** — questions that span multiple explores or require joins
7. **Edge cases** — ambiguous questions, nonexistent fields, vague requests

For each query, include:
- The natural language question
- Which model/explore it targets
- The expected dimensions and measures (Looker field names)
- The category

## Output Format
Return a JSON array:
```json
[
  {{
    "query": "What is the total revenue by product category?",
    "category": "simple_aggregation",
    "target_model": "ecommerce",
    "target_explore": "order_items",
    "expected_dimensions": ["products.category"],
    "expected_measures": ["order_items.total_sale_price"],
    "difficulty": "easy"
  }}
]
```

Use ONLY real field names from the schema above. For edge case queries, \
expected fields can be empty. Return ONLY the JSON array."""


# ============================================================================
# Eval Metrics — what we score each response on
# ============================================================================

@dataclass
class EvalScores:
    """Evaluation scores for a single interaction.

    Each metric is 0.0-1.0 where 1.0 is perfect.
    """
    # Did the agent use appropriate tools in a logical order?
    # (discovery before query, get-dimensions before query-sql, etc.)
    tool_selection: float = 0.0

    # Did the agent reference real fields that exist in the schema?
    # Penalizes hallucinated field names.
    field_accuracy: float = 0.0

    # Did the agent produce SQL? Is it structurally valid?
    sql_generation: float = 0.0

    # Did the answer actually address the question asked?
    answer_completeness: float = 0.0

    # Did the agent make up fields, explores, or data that don't exist?
    # 1.0 = no hallucination, 0.0 = pure hallucination
    hallucination: float = 0.0

    # When a tool call failed, did the agent try a different approach?
    error_recovery: float = 0.0

    # Efficiency: fewer unnecessary tool calls = higher score
    efficiency: float = 0.0

    @property
    def overall(self) -> float:
        """Weighted overall score."""
        weights = {
            "tool_selection": 0.15,
            "field_accuracy": 0.20,
            "sql_generation": 0.15,
            "answer_completeness": 0.20,
            "hallucination": 0.15,
            "error_recovery": 0.05,
            "efficiency": 0.10,
        }
        return sum(
            getattr(self, metric) * weight
            for metric, weight in weights.items()
        )

    def to_dict(self) -> dict:
        return {
            "tool_selection": round(self.tool_selection, 3),
            "field_accuracy": round(self.field_accuracy, 3),
            "sql_generation": round(self.sql_generation, 3),
            "answer_completeness": round(self.answer_completeness, 3),
            "hallucination": round(self.hallucination, 3),
            "error_recovery": round(self.error_recovery, 3),
            "efficiency": round(self.efficiency, 3),
            "overall": round(self.overall, 3),
        }


# ============================================================================
# Interaction Log — captures everything the agent does for evaluation
# ============================================================================

@dataclass
class EvalQuery:
    """A generated evaluation query with expected outcomes."""
    query: str
    category: str
    target_model: str = ""
    target_explore: str = ""
    expected_dimensions: list[str] = field(default_factory=list)
    expected_measures: list[str] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass
class InteractionRecord:
    """A single query→response interaction with full tool trace and scores."""
    query: str
    answer: str
    eval_query: EvalQuery | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    thinking_events: list[dict[str, str]] = field(default_factory=list)
    iterations: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    scores: EvalScores | None = None

    def to_dict(self) -> dict:
        d = {
            "query": self.query,
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "thinking_events": self.thinking_events,
            "iterations": self.iterations,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }
        if self.eval_query:
            d["eval_query"] = {
                "category": self.eval_query.category,
                "target_model": self.eval_query.target_model,
                "target_explore": self.eval_query.target_explore,
                "expected_dimensions": self.eval_query.expected_dimensions,
                "expected_measures": self.eval_query.expected_measures,
                "difficulty": self.eval_query.difficulty,
            }
        if self.scores:
            d["scores"] = self.scores.to_dict()
        return d


class LoggingThinkingCallback(ThinkingCallback):
    """
    Wraps ConsoleThinkingCallback to capture events into an InteractionRecord.

    This is what lets us see exactly what the agent did — which tools it called,
    what results came back, how it reasoned — so we can evaluate accuracy.
    """

    def __init__(self, console_callback: ConsoleThinkingCallback, verbose: bool = True):
        self.console_callback = console_callback
        self.verbose = verbose
        self.current_record: InteractionRecord | None = None

    def start_recording(self, query: str) -> InteractionRecord:
        self.current_record = InteractionRecord(query=query, answer="")
        return self.current_record

    def stop_recording(self) -> InteractionRecord | None:
        record = self.current_record
        self.current_record = None
        return record

    def on_thinking(self, event: ThinkingEvent) -> None:
        if self.current_record:
            self.current_record.thinking_events.append({
                "type": event.type.value,
                "content": event.content[:1000],
                "metadata": {k: str(v)[:200] for k, v in event.metadata.items()},
            })

            if event.type == ThinkingType.TOOL_CALL:
                self.current_record.tool_calls.append({
                    "tool": event.metadata.get("tool_name", "unknown"),
                    "iteration": len(self.current_record.tool_calls) + 1,
                })
                self.current_record.iterations += 1

            if event.type == ThinkingType.TOOL_RESULT:
                if self.current_record.tool_calls:
                    self.current_record.tool_calls[-1]["result_preview"] = event.content[:500]
                    self.current_record.tool_calls[-1]["has_error"] = (
                        "error" in event.content.lower()[:100]
                    )

            if event.type == ThinkingType.ERROR:
                if self.current_record.tool_calls:
                    self.current_record.tool_calls[-1]["has_error"] = True

            if event.type == ThinkingType.FINAL_ANSWER:
                self.current_record.answer = event.content

        if self.verbose:
            self.console_callback.on_thinking(event)


# ============================================================================
# Scorer — evaluates each interaction against the 7 metrics
# ============================================================================

class EvalScorer:
    """Scores an InteractionRecord against the 7 evaluation metrics."""

    # Expected tool usage patterns for different query categories
    DISCOVERY_TOOLS = {"get-models", "get-explores", "get-dimensions", "get-measures",
                       "get-filters", "get-parameters", "get-projects", "get-project-files",
                       "get-project-file", "get-dashboards", "run-look"}
    QUERY_TOOLS = {"query", "query-sql"}
    SCHEMA_TOOLS = {"get-dimensions", "get-measures", "get-filters", "get-parameters"}

    def __init__(self, known_fields: set[str] | None = None,
                 known_explores: set[str] | None = None,
                 known_models: set[str] | None = None):
        """
        Args:
            known_fields: Set of valid Looker field names from schema discovery
            known_explores: Set of valid explore names
            known_models: Set of valid model names
        """
        self.known_fields = known_fields or set()
        self.known_explores = known_explores or set()
        self.known_models = known_models or set()

    def score(self, record: InteractionRecord) -> EvalScores:
        scores = EvalScores()
        scores.tool_selection = self._score_tool_selection(record)
        scores.field_accuracy = self._score_field_accuracy(record)
        scores.sql_generation = self._score_sql_generation(record)
        scores.answer_completeness = self._score_answer_completeness(record)
        scores.hallucination = self._score_hallucination(record)
        scores.error_recovery = self._score_error_recovery(record)
        scores.efficiency = self._score_efficiency(record)
        return scores

    def _score_tool_selection(self, record: InteractionRecord) -> float:
        """Did the agent pick appropriate tools in a logical order?"""
        tools_used = [tc["tool"] for tc in record.tool_calls]
        if not tools_used:
            # No tools at all — bad for data questions, ok for edge cases
            if record.eval_query and record.eval_query.category == "edge_case":
                return 0.8  # Reasonable to not call tools for nonsense queries
            return 0.2

        score = 0.5  # Base: it used some tools

        # Did it do discovery before querying?
        query_indices = [i for i, t in enumerate(tools_used) if t in self.QUERY_TOOLS]
        schema_indices = [i for i, t in enumerate(tools_used) if t in self.SCHEMA_TOOLS]

        if query_indices and schema_indices:
            # Schema discovery should come before query execution
            if min(schema_indices) < min(query_indices):
                score += 0.3
            else:
                score += 0.1  # Queried before understanding schema

        # Did it use get-models/get-explores for discovery?
        if "get-models" in tools_used or "get-explores" in tools_used:
            score += 0.1

        # Did it eventually query if the question asked for data?
        if record.eval_query and record.eval_query.expected_measures:
            if any(t in self.QUERY_TOOLS for t in tools_used):
                score += 0.1

        return min(score, 1.0)

    def _score_field_accuracy(self, record: InteractionRecord) -> float:
        """Did the agent reference real fields from the schema?"""
        if not record.eval_query or not record.eval_query.expected_dimensions + record.eval_query.expected_measures:
            return 1.0  # No expected fields to check against

        expected = set(record.eval_query.expected_dimensions + record.eval_query.expected_measures)
        answer_lower = record.answer.lower()

        # Check how many expected fields appear in the answer
        found = sum(1 for f in expected if f.lower() in answer_lower)

        # Also check tool results for field references
        for tc in record.tool_calls:
            result = tc.get("result_preview", "").lower()
            found += sum(1 for f in expected if f.lower() in result and f.lower() not in answer_lower)

        if expected:
            return min(found / len(expected), 1.0)
        return 1.0

    def _score_sql_generation(self, record: InteractionRecord) -> float:
        """Did the agent produce SQL? Is it structurally valid?"""
        answer = record.answer

        # Look for SQL in the answer
        sql_patterns = [
            r'```sql\s*(.*?)```',
            r'`(SELECT\s.*?)`',
            r'(SELECT\s+.+?FROM\s+.+?)(?:\n\n|\Z)',
        ]
        sql_found = None
        for pattern in sql_patterns:
            match = re.search(pattern, answer, re.DOTALL | re.IGNORECASE)
            if match:
                sql_found = match.group(1)
                break

        # Also check if query/query-sql tool was called
        query_tool_used = any(tc["tool"] in self.QUERY_TOOLS for tc in record.tool_calls)

        if not sql_found and not query_tool_used:
            # No SQL at all — only ok for discovery/edge case queries
            if record.eval_query and record.eval_query.category in ("discovery", "edge_case"):
                return 0.8
            return 0.1

        score = 0.5  # Found SQL or used query tool

        if sql_found:
            sql_upper = sql_found.upper()
            # Basic structural checks
            if "SELECT" in sql_upper:
                score += 0.15
            if "FROM" in sql_upper:
                score += 0.15
            if "GROUP BY" in sql_upper or "ORDER BY" in sql_upper:
                score += 0.1
            # Penalize obvious errors
            if "ERROR" in sql_upper or "SYNTAX" in sql_upper:
                score -= 0.2

        if query_tool_used:
            score += 0.1

        return max(min(score, 1.0), 0.0)

    def _score_answer_completeness(self, record: InteractionRecord) -> float:
        """Did the answer address the question?"""
        if not record.answer:
            return 0.0

        answer_lower = record.answer.lower()
        query_lower = record.query.lower()
        score = 0.3  # Base: there is an answer

        # Length check — very short answers are usually incomplete
        if len(record.answer) > 100:
            score += 0.1
        if len(record.answer) > 300:
            score += 0.1

        # Does the answer contain data or results?
        if any(marker in answer_lower for marker in ["result", "total", "count", "show", "found"]):
            score += 0.1

        # Does the answer reference the question's key terms?
        query_words = set(re.findall(r'\b[a-z]{4,}\b', query_lower))
        answer_words = set(re.findall(r'\b[a-z]{4,}\b', answer_lower))
        if query_words:
            overlap = len(query_words & answer_words) / len(query_words)
            score += overlap * 0.2

        # Does the answer explain what it did?
        if any(w in answer_lower for w in ["model", "explore", "dimension", "measure", "sql"]):
            score += 0.1

        # Error responses
        if "error" in answer_lower and "encountered" in answer_lower:
            score = max(score - 0.3, 0.1)

        return min(score, 1.0)

    def _score_hallucination(self, record: InteractionRecord) -> float:
        """1.0 = no hallucination, 0.0 = pure hallucination."""
        if not self.known_fields and not self.known_explores:
            return 1.0  # Can't check without schema

        answer_lower = record.answer.lower()
        hallucination_count = 0
        checks = 0

        # Check if referenced explores exist
        explore_pattern = r'explore[:\s]+["\']?(\w+)["\']?'
        for match in re.finditer(explore_pattern, answer_lower):
            explore_name = match.group(1)
            checks += 1
            if explore_name not in {e.lower() for e in self.known_explores}:
                # Might be a substring — be lenient
                if not any(explore_name in e.lower() for e in self.known_explores):
                    hallucination_count += 1

        # Check field references in tool call args
        for tc in record.tool_calls:
            result = tc.get("result_preview", "")
            if "not found" in result.lower() or "does not exist" in result.lower():
                hallucination_count += 1
                checks += 1

        if checks == 0:
            return 1.0

        return max(1.0 - (hallucination_count / checks), 0.0)

    def _score_error_recovery(self, record: InteractionRecord) -> float:
        """When a tool call failed, did the agent try a different approach?"""
        error_calls = [tc for tc in record.tool_calls if tc.get("has_error")]

        if not error_calls:
            return 1.0  # No errors to recover from

        # Check if there were tool calls after the error
        last_error_idx = max(
            i for i, tc in enumerate(record.tool_calls) if tc.get("has_error")
        )
        calls_after_error = record.tool_calls[last_error_idx + 1:]

        if calls_after_error:
            return 0.8  # Tried something after the error
        elif record.answer and "error" not in record.answer.lower():
            return 0.6  # Gave an answer despite error (maybe recovered in reasoning)
        else:
            return 0.2  # Gave up

    def _score_efficiency(self, record: InteractionRecord) -> float:
        """Fewer unnecessary tool calls = higher score."""
        n = len(record.tool_calls)

        if n == 0:
            return 0.5  # No tools — could be efficient or could be lazy

        # Ideal: 2-5 tool calls for a typical query
        if 2 <= n <= 5:
            return 1.0
        elif n == 1:
            return 0.8  # Maybe skipped discovery
        elif 6 <= n <= 8:
            return 0.6
        elif 9 <= n <= 12:
            return 0.3
        else:
            return 0.1  # 13+ tool calls is excessive

        return min(max(score, 0.0), 1.0)


# ============================================================================
# CA Chat Session — extends ChatSession with logging + eval
# ============================================================================

class CAChatSession(ChatSession):
    """
    Extends ChatSession with interaction logging and evaluation capabilities.
    """

    def __init__(self, orchestrator: AgentOrchestrator, logging_callback: LoggingThinkingCallback):
        super().__init__(orchestrator)
        self.logging_callback = logging_callback
        self.interaction_log: list[InteractionRecord] = []

    async def chat(self, user_input: str, eval_query: EvalQuery | None = None) -> str:
        """Chat with full interaction logging."""
        record = self.logging_callback.start_recording(user_input)

        start = time.time()
        response = await super().chat(user_input)
        elapsed = (time.time() - start) * 1000

        record = self.logging_callback.stop_recording()
        if record:
            record.latency_ms = elapsed
            record.answer = response
            record.eval_query = eval_query
            self.interaction_log.append(record)

        return response

    def show_log(self) -> None:
        if not self.interaction_log:
            print("\n  No interactions logged yet.\n")
            return

        print(f"\n{'=' * 60}")
        print(f"INTERACTION LOG ({len(self.interaction_log)} queries)")
        print(f"{'=' * 60}")

        for i, record in enumerate(self.interaction_log, 1):
            print(f"\n--- Query {i} ---")
            print(f"  Q: {record.query}")
            print(f"  Tools called: {len(record.tool_calls)}")
            for tc in record.tool_calls:
                err = " [ERROR]" if tc.get("has_error") else ""
                print(f"    -> {tc['tool']}{err}")
            print(f"  Iterations: {record.iterations}")
            print(f"  Latency: {record.latency_ms:.0f}ms")
            if record.scores:
                print(f"  Score: {record.scores.overall:.1%}")
            if record.error:
                print(f"  Error: {record.error}")
            print(f"  Answer: {record.answer[:200]}{'...' if len(record.answer) > 200 else ''}")

        print(f"\n{'=' * 60}\n")

    def export_log(self) -> Path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = OUTPUT_DIR / f"ca_eval_{ts}.json"
        data = self._build_export()
        path.write_text(json.dumps(data, indent=2))
        print(f"\n  Exported to {path}\n")
        return path

    def _build_export(self) -> dict:
        scored = [r for r in self.interaction_log if r.scores]
        return {
            "session_queries": len(self.interaction_log),
            "total_tool_calls": sum(len(r.tool_calls) for r in self.interaction_log),
            "avg_latency_ms": round(
                sum(r.latency_ms for r in self.interaction_log) / len(self.interaction_log), 1
            ) if self.interaction_log else 0,
            "avg_overall_score": round(
                sum(r.scores.overall for r in scored) / len(scored), 3
            ) if scored else None,
            "metric_averages": self._avg_metrics(scored) if scored else None,
            "interactions": [r.to_dict() for r in self.interaction_log],
        }

    @staticmethod
    def _avg_metrics(records: list[InteractionRecord]) -> dict:
        if not records:
            return {}
        metrics = ["tool_selection", "field_accuracy", "sql_generation",
                    "answer_completeness", "hallucination", "error_recovery", "efficiency"]
        return {
            m: round(sum(getattr(r.scores, m) for r in records) / len(records), 3)
            for m in metrics
        }

    def show_help(self) -> None:
        print("""
╭──────────────────────────────────────────────────────────────╮
│              CONVERSATIONAL ANALYTICS AGENT                   │
├──────────────────────────────────────────────────────────────┤
│  /tools   - List all available MCP tools                      │
│  /clear   - Clear conversation history                        │
│  /eval    - Run full evaluation pipeline                      │
│  /log     - Show interaction log for this session             │
│  /export  - Export interaction log to JSON                    │
│  /help    - Show this help message                            │
│  /quit    - Exit                                              │
├──────────────────────────────────────────────────────────────┤
│                     EXAMPLE QUERIES                           │
├──────────────────────────────────────────────────────────────┤
│  "What models are available?"                                 │
│  "Show me all explores and their fields"                      │
│  "How many orders were placed last month?"                    │
│  "What is the total revenue by product category?"             │
│  "Show me the top 10 customers by spend"                      │
│  "What are the available dimensions in the users explore?"    │
╰──────────────────────────────────────────────────────────────╯
""")


# ============================================================================
# Eval Pipeline — schema discovery → query generation → execution → scoring
# ============================================================================

async def discover_schema(session: CAChatSession) -> dict:
    """
    Phase 1: Use the agent itself to introspect the Looker project.

    This runs through the same AgentOrchestrator / MCP tool loop that chat.py
    uses, so we're testing the real tool interaction path.
    """
    print(f"\n{'=' * 60}")
    print("PHASE 1: Schema Discovery")
    print(f"{'=' * 60}\n")

    response = await session.chat(SCHEMA_DISCOVERY_PROMPT)
    session.clear_history()  # Don't carry discovery context into eval queries

    # Parse the schema from the agent's response
    json_match = re.search(r'```json\s*(.*?)```', response, re.DOTALL)
    if not json_match:
        json_match = re.search(r'\{[\s\S]*"models"[\s\S]*\}', response)

    schema = {}
    if json_match:
        try:
            raw = json_match.group(1) if json_match.lastindex else json_match.group(0)
            schema = json.loads(raw)
        except json.JSONDecodeError:
            print("  [WARNING] Could not parse schema JSON from agent response")

    # Extract known entities for the scorer
    known_fields = set()
    known_explores = set()
    known_models = set()

    for model in schema.get("models", []):
        model_name = model.get("name", "")
        known_models.add(model_name)
        for explore in model.get("explores", []):
            explore_name = explore.get("name", "")
            known_explores.add(explore_name)
            for dim in explore.get("dimensions", []):
                known_fields.add(dim.get("name", ""))
            for meas in explore.get("measures", []):
                known_fields.add(meas.get("name", ""))

    print(f"  Discovered: {len(known_models)} models, {len(known_explores)} explores, "
          f"{len(known_fields)} fields")

    # Pop the discovery interaction out of the eval log — it's setup, not an eval query
    if session.interaction_log:
        session.interaction_log.pop()

    return {
        "schema": schema,
        "known_fields": known_fields,
        "known_explores": known_explores,
        "known_models": known_models,
    }


async def generate_eval_queries(
    session: CAChatSession,
    schema: dict,
    count: int = 25,
) -> list[EvalQuery]:
    """
    Phase 2: Use the agent to generate eval queries grounded in the real schema.

    The agent sees the actual schema and generates diverse NL questions
    that reference real fields.
    """
    print(f"\n{'=' * 60}")
    print(f"PHASE 2: Query Generation ({count} queries)")
    print(f"{'=' * 60}\n")

    schema_json = json.dumps(schema, indent=2)
    prompt = QUERY_GENERATION_PROMPT.format(schema_json=schema_json, count=count)

    response = await session.chat(prompt)
    session.clear_history()

    # Parse generated queries
    json_match = re.search(r'\[[\s\S]*\]', response)
    eval_queries = []

    if json_match:
        try:
            items = json.loads(json_match.group(0))
            for item in items:
                eval_queries.append(EvalQuery(
                    query=item.get("query", ""),
                    category=item.get("category", "unknown"),
                    target_model=item.get("target_model", ""),
                    target_explore=item.get("target_explore", ""),
                    expected_dimensions=item.get("expected_dimensions", []),
                    expected_measures=item.get("expected_measures", []),
                    difficulty=item.get("difficulty", "medium"),
                ))
        except json.JSONDecodeError:
            print("  [WARNING] Could not parse eval queries from agent response")

    print(f"  Generated {len(eval_queries)} eval queries")

    # Show category distribution
    categories: dict[str, int] = {}
    for eq in eval_queries:
        categories[eq.category] = categories.get(eq.category, 0) + 1
    for cat, cnt in sorted(categories.items()):
        print(f"    {cat}: {cnt}")

    # Pop the generation interaction out of the eval log
    if session.interaction_log:
        session.interaction_log.pop()

    # Save generated queries
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    queries_path = OUTPUT_DIR / "generated_eval_queries.json"
    queries_path.write_text(json.dumps(
        [{"query": q.query, "category": q.category, "target_model": q.target_model,
          "target_explore": q.target_explore, "expected_dimensions": q.expected_dimensions,
          "expected_measures": q.expected_measures, "difficulty": q.difficulty}
         for q in eval_queries],
        indent=2
    ))
    print(f"  Saved to {queries_path}")

    return eval_queries


async def run_eval(
    session: CAChatSession,
    eval_queries: list[EvalQuery] | None = None,
    scorer: EvalScorer | None = None,
) -> None:
    """
    Phase 3 + 4: Execute eval queries and score each response.
    """
    if not eval_queries:
        print("  No eval queries to run.")
        return

    if not scorer:
        scorer = EvalScorer()

    print(f"\n{'=' * 60}")
    print(f"PHASE 3: Eval Execution — {len(eval_queries)} queries")
    print(f"{'=' * 60}\n")

    for i, eq in enumerate(eval_queries, 1):
        print(f"\n[{i}/{len(eval_queries)}] [{eq.category}] {eq.query}")
        print("-" * 60)

        try:
            response = await session.chat(eq.query, eval_query=eq)
            print(f"\n{'─' * 60}")
            print(f"Answer: {response[:300]}{'...' if len(response) > 300 else ''}")
            print(f"{'─' * 60}")
        except Exception as e:
            print(f"\nError: {e}")
            if session.interaction_log:
                session.interaction_log[-1].error = str(e)

        # Score the interaction
        if session.interaction_log:
            record = session.interaction_log[-1]
            record.scores = scorer.score(record)
            print(f"  Score: {record.scores.overall:.1%}  "
                  f"[tools={record.scores.tool_selection:.0%} "
                  f"fields={record.scores.field_accuracy:.0%} "
                  f"sql={record.scores.sql_generation:.0%} "
                  f"complete={record.scores.answer_completeness:.0%} "
                  f"halluc={record.scores.hallucination:.0%} "
                  f"recovery={record.scores.error_recovery:.0%} "
                  f"efficiency={record.scores.efficiency:.0%}]")

        # Clear history between queries so each is independent
        session.clear_history()

    # Phase 4: Report
    print_eval_report(session)


def print_eval_report(session: CAChatSession) -> None:
    """Phase 4: Print aggregated evaluation report."""
    print(f"\n{'=' * 60}")
    print("PHASE 4: Evaluation Report")
    print(f"{'=' * 60}")

    scored = [r for r in session.interaction_log if r.scores]
    total = len(scored)

    if not total:
        print("  No scored interactions.")
        return

    # Overall metrics
    avg_overall = sum(r.scores.overall for r in scored) / total
    avg_latency = sum(r.latency_ms for r in scored) / total
    errors = sum(1 for r in scored if r.error)
    total_tools = sum(len(r.tool_calls) for r in scored)

    print(f"\n  Queries evaluated:  {total}")
    print(f"  Errors:             {errors}")
    print(f"  Total tool calls:   {total_tools}")
    print(f"  Avg latency:        {avg_latency:.0f}ms")
    print(f"  Overall score:      {avg_overall:.1%}")

    # Per-metric averages
    metrics = ["tool_selection", "field_accuracy", "sql_generation",
               "answer_completeness", "hallucination", "error_recovery", "efficiency"]
    print(f"\n  Metric breakdown:")
    for m in metrics:
        avg = sum(getattr(r.scores, m) for r in scored) / total
        bar = "█" * int(avg * 20)
        light = "░" * (20 - int(avg * 20))
        print(f"    {m:<25} {avg:>5.1%}  {bar}{light}")

    # Per-category breakdown
    categories: dict[str, list[InteractionRecord]] = {}
    for r in scored:
        cat = r.eval_query.category if r.eval_query else "unknown"
        categories.setdefault(cat, []).append(r)

    print(f"\n  Per-category scores:")
    for cat, records in sorted(categories.items()):
        avg = sum(r.scores.overall for r in records) / len(records)
        print(f"    {cat:<25} {avg:>5.1%}  ({len(records)} queries)")

    # Tool usage frequency
    tool_freq: dict[str, int] = {}
    for record in scored:
        for tc in record.tool_calls:
            tool_freq[tc["tool"]] = tool_freq.get(tc["tool"], 0) + 1

    print(f"\n  Tool usage frequency:")
    for tool, count in sorted(tool_freq.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 30)
        print(f"    {tool:<25} {count:>3}x  {bar}")

    # Worst performing queries
    sorted_by_score = sorted(scored, key=lambda r: r.scores.overall)
    print(f"\n  Lowest scoring queries:")
    for r in sorted_by_score[:5]:
        cat = r.eval_query.category if r.eval_query else "?"
        print(f"    {r.scores.overall:.1%}  [{cat}]  {r.query[:60]}")

    # Best performing queries
    print(f"\n  Highest scoring queries:")
    for r in sorted_by_score[-5:]:
        cat = r.eval_query.category if r.eval_query else "?"
        print(f"    {r.scores.overall:.1%}  [{cat}]  {r.query[:60]}")

    print(f"\n{'=' * 60}")

    # Auto-export
    path = session.export_log()
    print(f"  Full results saved to: {path}")
    print(f"{'=' * 60}\n")


async def run_full_eval(session: CAChatSession, query_count: int = 25) -> None:
    """Run the complete eval pipeline: discover → generate → execute → score."""

    # Phase 1: Schema Discovery
    discovery = await discover_schema(session)

    # Build scorer with real schema knowledge
    scorer = EvalScorer(
        known_fields=discovery["known_fields"],
        known_explores=discovery["known_explores"],
        known_models=discovery["known_models"],
    )

    # Phase 2: Query Generation
    eval_queries = await generate_eval_queries(
        session, discovery["schema"], count=query_count
    )

    if not eval_queries:
        print("  [ERROR] No eval queries generated. Check agent connectivity.")
        return

    # Phase 3 + 4: Execution + Scoring
    await run_eval(session, eval_queries, scorer)


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Conversational Analytics Agent")
    parser.add_argument("--eval", action="store_true",
                        help="Run full evaluation pipeline")
    parser.add_argument("--eval-file", type=str, default=None,
                        help="JSON file with pre-generated eval queries")
    parser.add_argument("--query-count", type=int, default=25,
                        help="Number of eval queries to generate (default: 25)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress thinking output during eval")
    args = parser.parse_args()

    print("""
╔═════════════════════════════════════════════════════════════╗
║                                                             ║
║       Conversational Analytics Agent                        ║
║                                                             ║
║      Evaluating Looker MCP tools via SafeChain              ║
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

    # Step 2: Load MCP tools
    print("[2/3] Loading MCP tools...")
    try:
        tools = await MCPToolLoader.load_tools(config)
        print(f"      ✓ Loaded {len(tools)} tools")
    except Exception as e:
        print(f"      ✗ Error: {e}")
        print("      Make sure MCP servers are running")
        return

    # Step 3: Initialize orchestrator with CA system prompt
    print("[3/3] Initializing CA agent...")

    model_id = (
        getattr(config, 'model_id', None) or
        getattr(config, 'model', None) or
        getattr(config, 'llm_model', None) or
        "gemini-pro"
    )

    console_callback = ConsoleThinkingCallback(use_rich=True)
    logging_callback = LoggingThinkingCallback(
        console_callback, verbose=not args.quiet
    )

    orchestrator = AgentOrchestrator(
        model_id=model_id,
        tools=tools,
        system_prompt=CA_SYSTEM_PROMPT,
        max_iterations=15,
        thinking_callback=logging_callback,
    )
    print("      ✓ CA agent ready")

    session = CAChatSession(orchestrator, logging_callback)

    # Eval mode
    if args.eval:
        if args.eval_file:
            # Load pre-generated queries
            with open(args.eval_file) as f:
                items = json.load(f)
            eval_queries = [
                EvalQuery(
                    query=item.get("query", ""),
                    category=item.get("category", "unknown"),
                    target_model=item.get("target_model", ""),
                    target_explore=item.get("target_explore", ""),
                    expected_dimensions=item.get("expected_dimensions", []),
                    expected_measures=item.get("expected_measures", []),
                    difficulty=item.get("difficulty", "medium"),
                )
                for item in items
            ]
            print(f"      Loaded {len(eval_queries)} eval queries from {args.eval_file}")

            # Still discover schema for the scorer
            discovery = await discover_schema(session)
            scorer = EvalScorer(
                known_fields=discovery["known_fields"],
                known_explores=discovery["known_explores"],
                known_models=discovery["known_models"],
            )
            await run_eval(session, eval_queries, scorer)
        else:
            await run_full_eval(session, query_count=args.query_count)
        return

    # Interactive mode
    session.show_tools()
    session.show_help()

    print("Type your question or command. Use /quit to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            cmd = user_input.lower()
            if cmd == "/quit":
                if session.interaction_log:
                    session.export_log()
                print("\nGoodbye!")
                break
            elif cmd == "/tools":
                session.show_tools()
                continue
            elif cmd == "/clear":
                session.clear_history()
                continue
            elif cmd == "/help":
                session.show_help()
                continue
            elif cmd == "/log":
                session.show_log()
                continue
            elif cmd == "/export":
                session.export_log()
                continue
            elif cmd == "/eval":
                await run_full_eval(session)
                continue

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
            if session.interaction_log:
                session.export_log()
            print("\n\nGoodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
