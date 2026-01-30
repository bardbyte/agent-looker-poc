"""Clarification node - asks user for more information."""

from ..state import AgentState


async def ask_clarify_node(state: AgentState) -> dict:
    """
    Format and present clarifying questions to the user.

    This node prepares a response asking for clarification
    when confidence is low or the agent is uncertain.
    """
    questions = state.get("clarifying_questions", [])
    explanation_trace = list(state.get("explanation_trace", []))

    if not questions:
        questions = [
            "Could you provide more details about what you're looking for?"
        ]

    explanation_trace.append("❓ Asking for clarification:")
    for q in questions:
        explanation_trace.append(f"   • {q}")

    # Format the response
    response_parts = [
        "I want to make sure I understand your question correctly.",
        "",
    ]

    if len(questions) == 1:
        response_parts.append(questions[0])
    else:
        response_parts.append("I have a few questions:")
        for i, q in enumerate(questions, 1):
            response_parts.append(f"  {i}. {q}")

    final_response = "\n".join(response_parts)

    return {
        "final_response": final_response,
        "explanation_trace": explanation_trace,
    }
