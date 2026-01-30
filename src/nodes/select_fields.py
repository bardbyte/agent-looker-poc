"""Field selection node."""

import json
from ..state import AgentState
from ..adapter import SafeChainAdapter
from ..prompts.selector import FIELD_SELECTION_PROMPT


async def select_fields_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Select dimensions, measures, and filters for the query.

    This node maps the user's natural language terms to actual
    field names in the selected explore.
    """
    schema = state.get("project_schema")
    field_selection = state.get("field_selection")

    if not schema or not field_selection:
        return {"error": "Schema or model selection missing"}

    model = field_selection.get("model")
    explore = field_selection.get("explore")
    user_question = state.get("current_query", "")

    # Get the explore details
    explore_key = f"{model}.{explore}"
    explore_data = schema.get("explores", {}).get(explore_key)

    if not explore_data:
        return {"error": f"Explore not found: {explore_key}"}

    explanation_trace = list(state.get("explanation_trace", []))
    explanation_trace.append("🎯 Mapping your question to data fields...")

    # Format fields for prompt
    dimensions = explore_data.get("dimensions", [])
    measures = explore_data.get("measures", [])

    dimensions_str = _format_fields(dimensions)
    measures_str = _format_fields(measures)
    filters_str = dimensions_str  # Filters are usually dimensions

    # Get previous context
    previous_context = _get_previous_context(state.get("messages", []))

    # Build prompt
    prompt = FIELD_SELECTION_PROMPT.format(
        user_question=user_question,
        model=model,
        explore=explore,
        dimensions=dimensions_str,
        measures=measures_str,
        filters=filters_str,
        previous_context=previous_context or "None",
    )

    try:
        result = await adapter.invoke(
            messages=[{"role": "user", "content": prompt}],
            tool_names=[],
        )

        content = result.get("content", "")
        selection = _parse_field_selection(content)

        selected_dims = selection.get("dimensions", [])
        selected_measures = selection.get("measures", [])
        selected_filters = selection.get("filters", {})
        confidence = selection.get("confidence", 0.5)
        field_mapping = selection.get("field_mapping", {})
        reasoning = selection.get("reasoning", "")

        # Log field mapping for explainability
        explanation_trace.append("   Field mapping:")
        for user_term, field_name in field_mapping.items():
            explanation_trace.append(f"     \"{user_term}\" → {field_name}")

        explanation_trace.append(f"   Dimensions: {selected_dims}")
        explanation_trace.append(f"   Measures: {selected_measures}")
        if selected_filters:
            explanation_trace.append(f"   Filters: {selected_filters}")
        explanation_trace.append(f"   Confidence: {confidence:.0%}")

        # Check for uncertainty
        uncertain_terms = selection.get("uncertain_terms", [])
        clarifying_questions = selection.get("clarifying_questions", [])

        if uncertain_terms or clarifying_questions:
            explanation_trace.append(f"   ⚠️ Uncertain about: {uncertain_terms}")

        # Update field selection
        updated_selection = {
            **field_selection,
            "dimensions": selected_dims,
            "measures": selected_measures,
            "filters": selected_filters,
        }

        return {
            "field_selection": updated_selection,
            "confidence": confidence,
            "needs_clarification": len(clarifying_questions) > 0,
            "clarifying_questions": clarifying_questions if clarifying_questions else None,
            "explanation_trace": explanation_trace,
        }

    except Exception as e:
        explanation_trace.append(f"❌ Field selection error: {str(e)}")
        return {
            "error": str(e),
            "explanation_trace": explanation_trace,
        }


def _format_fields(fields: list) -> str:
    """Format fields list for prompt."""
    lines = []
    for field in fields:
        name = field.get("name", "")
        label = field.get("label", name)
        field_type = field.get("type", "")
        description = field.get("description", "")

        line = f"- {name}"
        if label != name:
            line += f" ({label})"
        if field_type:
            line += f" [{field_type}]"
        if description:
            line += f": {description[:80]}"

        lines.append(line)

    return "\n".join(lines) if lines else "None available"


def _get_previous_context(messages: list) -> str:
    """Extract relevant context from previous messages."""
    context_parts = []

    for msg in messages[-4:]:
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


def _parse_field_selection(content: str) -> dict:
    """Parse field selection response."""
    try:
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            json_str = content[json_start:json_end].strip()
            return json.loads(json_str)

        return json.loads(content)

    except json.JSONDecodeError:
        return {
            "dimensions": [],
            "measures": [],
            "filters": {},
            "confidence": 0.0,
            "reasoning": "Could not parse field selection response",
        }
