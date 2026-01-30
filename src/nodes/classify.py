"""Intent classification node."""

import json
from ..state import AgentState
from ..adapter import SafeChainAdapter
from ..prompts.classifier import INTENT_CLASSIFICATION_PROMPT


async def classify_intent_node(
    state: AgentState,
    adapter: SafeChainAdapter,
) -> dict:
    """
    Classify the user's intent from their message.

    Intents:
    - query: User wants to build a query / get SQL
    - schema_overview: User wants to see available data
    - explore_details: User wants details on a specific explore
    - field_explain: User wants to understand a specific field
    - follow_up: User is refining a previous query
    """
    messages = state.get("messages", [])
    if not messages:
        return {"error": "No messages to classify"}

    # Get the last user message
    last_message = None
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            last_message = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            last_message = msg.get("content")
            break

    if not last_message:
        return {"error": "No user message found"}

    explanation_trace = list(state.get("explanation_trace", []))
    explanation_trace.append(f"🎯 Classifying intent for: \"{last_message[:50]}...\"")

    # Build the classification prompt
    prompt = INTENT_CLASSIFICATION_PROMPT.format(user_message=last_message)

    try:
        # Use SafeChain for LLM call (no tools needed for classification)
        result = await adapter.invoke(
            messages=[{"role": "user", "content": prompt}],
            tool_names=[],  # No tools for classification
        )

        content = result.get("content", "")

        # Parse the JSON response
        classification = _parse_classification(content)

        intent = classification.get("intent", "query")
        confidence = classification.get("confidence", 0.5)
        reasoning = classification.get("reasoning", "")

        explanation_trace.append(
            f"   Intent: {intent} (confidence: {confidence:.0%})"
        )
        explanation_trace.append(f"   Reasoning: {reasoning}")

        return {
            "intent": intent,
            "current_query": last_message,
            "confidence": confidence,
            "explanation_trace": explanation_trace,
        }

    except Exception as e:
        explanation_trace.append(f"❌ Classification error: {str(e)}")
        # Default to query intent on error
        return {
            "intent": "query",
            "current_query": last_message,
            "confidence": 0.5,
            "explanation_trace": explanation_trace,
            "error": str(e),
        }


def _parse_classification(content: str) -> dict:
    """Parse the classification response, handling various formats."""
    # Try to find JSON in the response
    try:
        # Look for JSON block
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            json_str = content[json_start:json_end].strip()
            return json.loads(json_str)

        # Try direct JSON parse
        return json.loads(content)

    except json.JSONDecodeError:
        # Fall back to keyword matching
        content_lower = content.lower()

        if "schema_overview" in content_lower or "what data" in content_lower:
            return {"intent": "schema_overview", "confidence": 0.6}
        elif "explore_details" in content_lower or "tell me about" in content_lower:
            return {"intent": "explore_details", "confidence": 0.6}
        elif "field_explain" in content_lower or "what is" in content_lower:
            return {"intent": "field_explain", "confidence": 0.6}
        elif "follow_up" in content_lower or "filter" in content_lower:
            return {"intent": "follow_up", "confidence": 0.6}
        else:
            return {"intent": "query", "confidence": 0.5}
