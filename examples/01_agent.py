#!/usr/bin/env python3
"""Agent with thinking output — same as chat.py's AgentOrchestrator.

Run:
    python examples/01_agent.py
"""

import asyncio
from liteagent import Agent, ConsoleCallback


async def main():
    agent = Agent(
        system_prompt="You are a Looker analytics expert.",
        on_thinking=ConsoleCallback(use_rich=True),
    )

    result = await agent.run_prompt("What models are available?")
    print("\nFinal answer:", result["content"])


if __name__ == "__main__":
    asyncio.run(main())
