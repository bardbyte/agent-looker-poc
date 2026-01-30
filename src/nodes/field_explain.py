"""Field explanation node - explains what a dimension or measure means."""

from ..state import AgentState
from ..adapter import SafeChainAdapter
from ..prompts.explainer import FIELD_EXPLANATION_PROMPT


async def field_explain_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Explain a specific field (dimension or measure) to the user.

    Provides:
    - What the field represents
    - How it's calculated (for measures)
    - Common usage patterns
    - Related fields
    """
    schema = state.get("project_schema")
    if not schema:
        return {"error": "Schema not loaded"}

    user_query = state.get("current_query", "")

    explanation_trace = list(state.get("explanation_trace", []))
    explanation_trace.append("📖 Looking up field information...")

    # Try to find the field
    field_name = _extract_field_name(user_query)
    field_info = _find_field(schema, field_name)

    if not field_info:
        explanation_trace.append(f"❌ Field not found: {field_name}")
        response = _format_field_not_found(field_name, schema)
    else:
        explanation_trace.append(f"✅ Found field: {field_info['name']}")
        response = _format_field_explanation(field_info)

    return {
        "final_response": response,
        "explanation_trace": explanation_trace,
    }


def _extract_field_name(query: str) -> str:
    """Extract the field name user is asking about."""
    query_lower = query.lower()

    # Common patterns
    patterns = [
        "what is ",
        "what's ",
        "explain ",
        "tell me about ",
        "what does ",
        " mean",
        "?",
    ]

    for pattern in patterns:
        query_lower = query_lower.replace(pattern, " ")

    # Clean up
    words = query_lower.split()
    # Remove common words
    stop_words = {"the", "a", "an", "field", "dimension", "measure", "is", "are"}
    words = [w for w in words if w not in stop_words]

    return " ".join(words).strip()


def _find_field(schema: dict, field_name: str) -> dict | None:
    """Find a field in the schema."""
    field_name_lower = field_name.lower().replace(" ", "_")

    for explore_key, explore_data in schema.get("explores", {}).items():
        # Check dimensions
        for dim in explore_data.get("dimensions", []):
            dim_name = dim.get("name", "").lower()
            if field_name_lower in dim_name or dim_name.endswith(field_name_lower):
                return {
                    **dim,
                    "field_type": "dimension",
                    "explore": explore_data.get("name"),
                    "model": explore_data.get("model"),
                }

        # Check measures
        for measure in explore_data.get("measures", []):
            measure_name = measure.get("name", "").lower()
            if field_name_lower in measure_name or measure_name.endswith(field_name_lower):
                return {
                    **measure,
                    "field_type": "measure",
                    "explore": explore_data.get("name"),
                    "model": explore_data.get("model"),
                }

    return None


def _format_field_explanation(field_info: dict) -> str:
    """Format a detailed explanation of a field."""
    name = field_info.get("name", "")
    label = field_info.get("label", name)
    field_type = field_info.get("type", "")
    description = field_info.get("description", "No description available")
    sql = field_info.get("sql", "")
    explore = field_info.get("explore", "")
    model = field_info.get("model", "")
    is_measure = field_info.get("field_type") == "measure"

    icon = "📏" if is_measure else "📐"
    type_label = "MEASURE" if is_measure else "DIMENSION"

    lines = [
        f"{icon} **{type_label}: {name}**",
        "",
        "┌" + "─" * 50 + "┐",
        f"│ **Label:** {label}",
        f"│ **Type:** {field_type}",
        f"│ **Explore:** {explore}",
        f"│ **Model:** {model}",
        "└" + "─" * 50 + "┘",
        "",
        "**📝 Description:**",
        f"  {description}",
        "",
    ]

    if sql:
        lines.extend([
            "**💻 SQL Definition:**",
            f"  ```sql",
            f"  {sql}",
            f"  ```",
            "",
        ])

    lines.extend([
        "**💡 Usage:**",
    ])

    if is_measure:
        lines.append(f"  This is an aggregation (typically {field_type}). Use it to calculate totals, averages, etc.")
        lines.append(f"  Example: \"Show me {name} by region\"")
    else:
        lines.append(f"  This is a dimension used for grouping data.")
        lines.append(f"  Example: \"Show me sales by {name}\"")

    return "\n".join(lines)


def _format_field_not_found(field_name: str, schema: dict) -> str:
    """Format response when field is not found."""
    lines = [
        f"❌ **Field not found:** {field_name}",
        "",
        "I couldn't find a field matching that name.",
        "",
        "**💡 Try one of these:**",
    ]

    # Suggest some fields
    sample_fields = []
    for explore_data in list(schema.get("explores", {}).values())[:2]:
        for dim in explore_data.get("dimensions", [])[:3]:
            sample_fields.append(dim.get("name", ""))
        for measure in explore_data.get("measures", [])[:3]:
            sample_fields.append(measure.get("name", ""))

    for field in sample_fields[:6]:
        lines.append(f"  • {field}")

    lines.append("")
    lines.append("Or ask \"What data is available?\" to see the full schema.")

    return "\n".join(lines)
