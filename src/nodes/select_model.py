"""Model selection node."""

import json
from ..state import AgentState
from ..adapter import SafeChainAdapter
from ..prompts.selector import MODEL_SELECTION_PROMPT


async def select_model_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Select the best model and explore for the user's question.

    This node analyzes the user's question against the cached schema
    and determines which model/explore contains the relevant data.
    """
    schema = state.get("project_schema")
    if not schema:
        return {"error": "Schema not loaded"}

    user_question = state.get("current_query", "")
    if not user_question:
        return {"error": "No query to process"}

    explanation_trace = list(state.get("explanation_trace", []))
    explanation_trace.append("📊 Selecting best model for your question...")

    # Format schema for the prompt
    schema_summary = _format_schema_for_prompt(schema)

    # Get previous context from messages
    previous_context = _get_previous_context(state.get("messages", []))

    # Build prompt
    prompt = MODEL_SELECTION_PROMPT.format(
        schema=schema_summary,
        user_question=user_question,
        previous_context=previous_context or "None",
    )

    try:
        result = await adapter.invoke(
            messages=[{"role": "user", "content": prompt}],
            tool_names=[],  # No tools needed
        )

        content = result.get("content", "")
        selection = _parse_selection(content)

        model = selection.get("model")
        explore = selection.get("explore")
        confidence = selection.get("confidence", 0.5)
        reasoning = selection.get("reasoning", "")

        if not model or not explore:
            # Couldn't find a match
            clarifying_questions = selection.get("clarifying_questions", [])
            explanation_trace.append("❓ Couldn't determine the right model")
            explanation_trace.append(f"   Reason: {reasoning}")

            return {
                "confidence": 0.0,
                "needs_clarification": True,
                "clarifying_questions": clarifying_questions or [
                    "Could you tell me more about what data you're looking for?"
                ],
                "explanation_trace": explanation_trace,
            }

        explanation_trace.append(f"   Selected: {model}.{explore}")
        explanation_trace.append(f"   Confidence: {confidence:.0%}")
        explanation_trace.append(f"   Reason: {reasoning}")

        # Store partial field selection with model/explore
        field_selection = {
            "model": model,
            "explore": explore,
            "dimensions": [],
            "measures": [],
            "filters": {},
        }

        return {
            "field_selection": field_selection,
            "confidence": confidence,
            "explanation_trace": explanation_trace,
        }

    except Exception as e:
        explanation_trace.append(f"❌ Model selection error: {str(e)}")
        return {
            "error": str(e),
            "explanation_trace": explanation_trace,
        }


def _format_schema_for_prompt(schema: dict) -> str:
    """Format schema for inclusion in prompt."""
    lines = []

    for model in schema.get("models", []):
        model_name = model.get("name", "")
        model_label = model.get("label", model_name)
        lines.append(f"\nModel: {model_name} ({model_label})")

        for explore in model.get("explores", []):
            explore_name = explore.get("name", "")
            explore_desc = explore.get("description", "")
            dim_count = explore.get("dimension_count", 0)
            measure_count = explore.get("measure_count", 0)

            lines.append(f"  Explore: {explore_name}")
            if explore_desc:
                lines.append(f"    Description: {explore_desc}")
            lines.append(f"    Dimensions: {dim_count}, Measures: {measure_count}")

            # Get full explore details from schema
            explore_key = f"{model_name}.{explore_name}"
            full_explore = schema.get("explores", {}).get(explore_key, {})

            # List key dimensions (first 10)
            dimensions = full_explore.get("dimensions", [])[:10]
            if dimensions:
                dim_names = [d.get("name", "") for d in dimensions]
                lines.append(f"    Sample dimensions: {', '.join(dim_names)}")

            # List key measures (first 10)
            measures = full_explore.get("measures", [])[:10]
            if measures:
                measure_names = [m.get("name", "") for m in measures]
                lines.append(f"    Sample measures: {', '.join(measure_names)}")

    return "\n".join(lines)


def _get_previous_context(messages: list) -> str:
    """Extract relevant context from previous messages."""
    context_parts = []

    for msg in messages[-6:]:  # Last 3 turns
        if hasattr(msg, "type"):
            if msg.type == "human":
                context_parts.append(f"User: {msg.content[:100]}")
            elif msg.type == "ai":
                context_parts.append(f"Assistant: {msg.content[:100]}")
        elif isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")[:100]
            context_parts.append(f"{role}: {content}")

    return "\n".join(context_parts) if context_parts else ""


def _parse_selection(content: str) -> dict:
    """Parse model selection response."""
    try:
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            json_str = content[json_start:json_end].strip()
            return json.loads(json_str)

        return json.loads(content)

    except json.JSONDecodeError:
        return {
            "model": None,
            "explore": None,
            "confidence": 0.0,
            "reasoning": "Could not parse model selection response",
        }
