"""Schema discovery node - loads and caches project schema."""

import json
from ..state import AgentState, ProjectSchema
from ..adapter import SafeChainAdapter, TOOL_SETS


async def discover_project_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Discover and cache the project schema from Looker.

    This node:
    1. Calls get_models to find all available models
    2. For each model, calls get_explores to find explores
    3. For each explore, calls get_dimensions and get_measures
    4. Caches the full schema in state

    Only runs once per session (skips if schema_loaded is True).
    """
    # Skip if already loaded
    if state.get("schema_loaded"):
        return {}

    explanation_trace = list(state.get("explanation_trace", []))
    explanation_trace.append("🔍 Discovering project schema from Looker...")

    try:
        # Get all models
        models_result = await adapter.invoke_tool("get_models")
        models_data = _parse_result(models_result)

        if not models_data:
            return {
                "error": "No models found in Looker",
                "explanation_trace": explanation_trace + ["❌ No models found"],
            }

        explanation_trace.append(f"📊 Found {len(models_data)} models")

        # Build schema structure
        schema: ProjectSchema = {
            "models": [],
            "explores": {},
        }

        for model in models_data:
            model_name = model.get("name", "")
            model_label = model.get("label", model_name)

            explanation_trace.append(f"  └── Model: {model_name}")

            # Get explores for this model
            explores_result = await adapter.invoke_tool(
                "get_explores",
                model=model_name
            )
            explores_data = _parse_result(explores_result)

            model_explores = []

            for explore in (explores_data or []):
                explore_name = explore.get("name", "")
                explore_label = explore.get("label", explore_name)
                explore_desc = explore.get("description", "")

                explanation_trace.append(f"      └── Explore: {explore_name}")

                # Get dimensions
                dims_result = await adapter.invoke_tool(
                    "get_dimensions",
                    model=model_name,
                    explore=explore_name
                )
                dimensions = _parse_result(dims_result) or []

                # Get measures
                measures_result = await adapter.invoke_tool(
                    "get_measures",
                    model=model_name,
                    explore=explore_name
                )
                measures = _parse_result(measures_result) or []

                explanation_trace.append(
                    f"          📐 {len(dimensions)} dimensions, 📏 {len(measures)} measures"
                )

                # Store in schema
                explore_key = f"{model_name}.{explore_name}"
                schema["explores"][explore_key] = {
                    "model": model_name,
                    "name": explore_name,
                    "label": explore_label,
                    "description": explore_desc,
                    "dimensions": dimensions,
                    "measures": measures,
                }

                model_explores.append({
                    "name": explore_name,
                    "label": explore_label,
                    "description": explore_desc,
                    "dimension_count": len(dimensions),
                    "measure_count": len(measures),
                })

            schema["models"].append({
                "name": model_name,
                "label": model_label,
                "explores": model_explores,
            })

        explanation_trace.append("✅ Schema discovery complete")

        return {
            "project_schema": schema,
            "schema_loaded": True,
            "explanation_trace": explanation_trace,
        }

    except Exception as e:
        return {
            "error": f"Schema discovery failed: {str(e)}",
            "explanation_trace": explanation_trace + [f"❌ Error: {str(e)}"],
        }


def _parse_result(result) -> list | dict | None:
    """Parse tool result, handling various formats."""
    if result is None:
        return None

    if isinstance(result, (list, dict)):
        return result

    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None

    # Try to get content attribute
    content = getattr(result, "content", None)
    if content:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

    return None
