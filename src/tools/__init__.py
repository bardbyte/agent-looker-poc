"""Tool configurations for the Semantic Layer Agent."""

# Tool sets for intent-based loading
TOOL_SETS = {
    "discovery": [
        "get_models",
        "get_explores",
        "get_dimensions",
        "get_measures",
    ],
    "query": [
        "query_sql",
    ],
    "schema_explore": [
        "get_models",
        "get_explores",
        "get_dimensions",
        "get_measures",
        "get_filters",
    ],
    "lookml": [
        "get_projects",
        "get_project_files",
        "get_project_file",
    ],
}


def get_tools_for_intent(intent: str) -> list[str]:
    """
    Get tool names appropriate for a given intent.

    Args:
        intent: The classified intent

    Returns:
        List of tool names to load
    """
    intent_to_toolsets = {
        "query": ["discovery", "query"],
        "schema_overview": ["schema_explore"],
        "explore_details": ["schema_explore"],
        "field_explain": ["schema_explore"],
        "follow_up": ["discovery", "query"],
    }

    toolsets = intent_to_toolsets.get(intent, ["discovery"])
    tools = []
    for ts in toolsets:
        tools.extend(TOOL_SETS.get(ts, []))

    return list(set(tools))  # Deduplicate
