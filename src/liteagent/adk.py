"""Google ADK adapter — exposes Agent as an ADK BaseAgent.

Usage:
    from liteagent.adk import LiteAgent

    # With MCP tool names (triggers MCP bootstrap)
    looker = LiteAgent(
        name="LookerAnalyst",
        system_prompt="You are a Looker analytics expert",
        tool_names=["conversational-analytics", "get-models"],
        output_key="looker_result",
    )

    # With tool objects (no MCP needed)
    looker = LiteAgent(
        name="LookerAnalyst",
        system_prompt="You are a Looker analytics expert",
        tools=[my_tool_1, my_tool_2],
        output_key="looker_result",
    )

Requires: pip install liteagent[adk]
"""

from __future__ import annotations

try:
    from google.adk.agents import BaseAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.genai import types as genai_types
    import google.adk.events as adk_events

    _HAS_ADK = True
except ImportError:
    _HAS_ADK = False

from .agent import Agent


def _require_adk():
    if not _HAS_ADK:
        raise ImportError(
            "google-adk is required for the ADK adapter. "
            "Install it with: pip install liteagent[adk]"
        )


if _HAS_ADK:

    class LiteAgent(BaseAgent):
        """Wraps liteagent.Agent as an ADK BaseAgent for use in ADK orchestration.

        Args:
            name: Agent name (used by ADK's orchestration).
            system_prompt: System prompt for the underlying Agent.
            tool_names: Optional list of MCP tool names to scope.
            output_key: Session state key where the result is stored.
            model: Model ID override.
            max_iterations: Max ReAct iterations.
        """

        system_prompt: str = "You are a helpful assistant."
        tool_names: list[str] | None = None
        tools: list | None = None
        output_key: str = "result"
        model: str | None = None
        max_iterations: int = 15

        def model_post_init(self, __context):
            super().model_post_init(__context)
            # tool objects take precedence over name strings
            resolved_tools = self.tools if self.tools is not None else self.tool_names
            self._agent = Agent(
                system_prompt=self.system_prompt,
                model=self.model,
                tools=resolved_tools,
                max_iterations=self.max_iterations,
            )

        async def _run_async_impl(
            self, ctx: InvocationContext
        ):
            """Run the agent and yield ADK events."""
            # Collect user messages from session state
            user_msg = ctx.session.state.get("user_message", "")
            if not user_msg:
                # Try to get from the last user event
                for event in reversed(ctx.session.events or []):
                    if event.author == "user" and event.content and event.content.parts:
                        user_msg = event.content.parts[0].text
                        break

            if not user_msg:
                yield adk_events.Event(
                    author=self.name,
                    content=genai_types.Content(
                        role="model",
                        parts=[genai_types.Part(text="No input provided.")],
                    ),
                )
                return

            result = await self._agent.run_prompt(user_msg)
            answer = result.get("content", "")

            # Save to session state
            ctx.session.state[self.output_key] = answer

            yield adk_events.Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=answer)],
                ),
            )

else:

    class LiteAgent:  # type: ignore[no-redef]
        """Stub that raises ImportError when google-adk is not installed."""

        def __init__(self, *args, **kwargs):
            _require_adk()
