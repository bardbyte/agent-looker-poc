#!/usr/bin/env python3
"""Interactive CLI — same as chat.py's ChatSession.

Run:
    python examples/02_chat.py
"""

import asyncio
from liteagent import Agent, Chat, ConsoleCallback


async def main():
    agent = Agent(
        system_prompt="You are a Looker analytics expert.",
        on_thinking=ConsoleCallback(use_rich=True),
    )
    chat = Chat(agent)
    await chat.start()


if __name__ == "__main__":
    asyncio.run(main())
