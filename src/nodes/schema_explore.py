"""Schema exploration node - displays schema to user."""

from ..state import AgentState
from ..adapter import SafeChainAdapter
from ..prompts.explainer import SCHEMA_OVERVIEW_PROMPT


async def schema_explore_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Display schema information to the user.

    Handles both overview and detailed explore views.
    """
    schema = state.get("project_schema")
    if not schema:
        return {"error": "Schema not loaded"}

    intent = state.get("intent")
    user_query = state.get("current_query", "")

    explanation_trace = list(state.get("explanation_trace", []))

    if intent == "schema_overview":
        # Show full schema tree
        response = _format_schema_tree(schema)
        explanation_trace.append("📁 Showing schema overview")

    elif intent == "explore_details":
        # Find and show specific explore
        explore_name = _extract_explore_name(user_query, schema)
        if explore_name:
            response = _format_explore_details(schema, explore_name)
            explanation_trace.append(f"🔍 Showing details for: {explore_name}")
        else:
            response = _format_schema_tree(schema)
            response += "\n\n💡 Tip: Ask about a specific explore like 'Tell me about order_items'"
            explanation_trace.append("📁 Showing schema (couldn't identify specific explore)")

    else:
        response = _format_schema_tree(schema)
        explanation_trace.append("📁 Showing schema")

    return {
        "final_response": response,
        "explanation_trace": explanation_trace,
    }


def _format_schema_tree(schema: dict) -> str:
    """Format schema as a visual tree."""
    lines = [
        "📁 **AVAILABLE DATA**",
        "",
    ]

    for model in schema.get("models", []):
        model_name = model.get("name", "")
        model_label = model.get("label", model_name)

        lines.append(f"├── 📊 **Model: {model_name}**")
        if model_label != model_name:
            lines.append(f"│   ({model_label})")

        explores = model.get("explores", [])
        for i, explore in enumerate(explores):
            explore_name = explore.get("name", "")
            explore_desc = explore.get("description", "")
            dim_count = explore.get("dimension_count", 0)
            measure_count = explore.get("measure_count", 0)

            is_last = (i == len(explores) - 1)
            prefix = "    └──" if is_last else "    ├──"

            lines.append(f"│   {prefix} 🔍 **{explore_name}**")
            if explore_desc:
                lines.append(f"│       {explore_desc[:60]}...")
            lines.append(f"│       📐 {dim_count} dimensions | 📏 {measure_count} measures")

        lines.append("│")

    lines.append("")
    lines.append("💡 **Try asking:**")
    lines.append("  • \"Tell me about the [explore_name] explore\"")
    lines.append("  • \"What dimensions are in [explore_name]?\"")
    lines.append("  • \"Show me sales by region\" (to generate SQL)")

    return "\n".join(lines)


def _format_explore_details(schema: dict, explore_name: str) -> str:
    """Format detailed view of a specific explore."""
    # Find the explore
    explore_data = None
    model_name = None

    for key, data in schema.get("explores", {}).items():
        if explore_name.lower() in key.lower():
            explore_data = data
            model_name = data.get("model")
            break

    if not explore_data:
        return f"❌ Explore '{explore_name}' not found."

    lines = [
        f"🔍 **EXPLORE: {explore_data.get('name', '')}**",
        f"   Model: {model_name}",
    ]

    desc = explore_data.get("description")
    if desc:
        lines.append(f"   {desc}")

    lines.append("")
    lines.append("═" * 50)
    lines.append("📐 **DIMENSIONS**")
    lines.append("═" * 50)

    dimensions = explore_data.get("dimensions", [])
    for dim in dimensions[:15]:  # Show first 15
        name = dim.get("name", "")
        label = dim.get("label", "")
        dim_type = dim.get("type", "")
        desc = dim.get("description", "")

        line = f"  • {name}"
        if dim_type:
            line += f" [{dim_type}]"
        lines.append(line)
        if desc:
            lines.append(f"    {desc[:60]}")

    if len(dimensions) > 15:
        lines.append(f"  ... and {len(dimensions) - 15} more")

    lines.append("")
    lines.append("═" * 50)
    lines.append("📏 **MEASURES**")
    lines.append("═" * 50)

    measures = explore_data.get("measures", [])
    for measure in measures[:15]:
        name = measure.get("name", "")
        label = measure.get("label", "")
        measure_type = measure.get("type", "")
        desc = measure.get("description", "")

        line = f"  • {name}"
        if measure_type:
            line += f" [{measure_type}]"
        lines.append(line)
        if desc:
            lines.append(f"    {desc[:60]}")

    if len(measures) > 15:
        lines.append(f"  ... and {len(measures) - 15} more")

    lines.append("")
    lines.append("💡 **Example queries:**")
    if dimensions and measures:
        dim = dimensions[0].get("name", "field")
        measure = measures[0].get("name", "count")
        lines.append(f"  • \"Show me {measure} by {dim}\"")

    return "\n".join(lines)


def _extract_explore_name(query: str, schema: dict) -> str | None:
    """Try to extract an explore name from the user query."""
    query_lower = query.lower()

    # Check each explore name
    for key in schema.get("explores", {}).keys():
        explore_name = key.split(".")[-1]  # Get just the explore name
        if explore_name.lower() in query_lower:
            return explore_name

    # Check model names
    for model in schema.get("models", []):
        model_name = model.get("name", "")
        if model_name.lower() in query_lower:
            # Return first explore in this model
            explores = model.get("explores", [])
            if explores:
                return explores[0].get("name")

    return None
