"""Confidence check node - routes based on confidence level."""

from ..state import AgentState


async def confidence_check_node(state: AgentState) -> dict:
    """
    Check confidence level and determine next step.

    This is a routing node that doesn't modify state significantly,
    just prepares for the routing decision.
    """
    confidence = state.get("confidence", 0.0)
    needs_clarification = state.get("needs_clarification", False)

    explanation_trace = list(state.get("explanation_trace", []))

    if needs_clarification or confidence < 0.8:
        explanation_trace.append(
            f"⚠️ Confidence ({confidence:.0%}) below threshold - asking for clarification"
        )
        return {
            "needs_clarification": True,
            "explanation_trace": explanation_trace,
        }
    else:
        explanation_trace.append(
            f"✅ Confidence ({confidence:.0%}) sufficient - proceeding to SQL generation"
        )
        return {
            "needs_clarification": False,
            "explanation_trace": explanation_trace,
        }


def route_by_confidence(state: AgentState) -> str:
    """
    Routing function for conditional edges after confidence check.

    Returns:
        "high" if confidence >= 0.8 and no clarification needed
        "low" otherwise
    """
    if state.get("needs_clarification", False):
        return "low"

    confidence = state.get("confidence", 0.0)
    return "high" if confidence >= 0.8 else "low"
