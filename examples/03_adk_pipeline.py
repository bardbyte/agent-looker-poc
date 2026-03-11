#!/usr/bin/env python3
"""LiteAgent inside ADK SequentialAgent — Cortex pattern.

Requires: pip install liteagent[adk]

Run:
    python examples/03_adk_pipeline.py
"""

from google.adk.agents import SequentialAgent
from liteagent.adk import LiteAgent


# Define agents for the pipeline
planner = LiteAgent(
    name="Planner",
    system_prompt="You are a query planner. Break down the user's question into steps.",
    output_key="plan",
)

analyst = LiteAgent(
    name="LookerAnalyst",
    system_prompt="You are a Looker analytics expert. Execute queries based on the plan.",
    tool_names=["conversational-analytics", "get-models"],
    output_key="analysis",
)

summarizer = LiteAgent(
    name="Summarizer",
    system_prompt="You are a data summarizer. Summarize the analysis results clearly.",
    output_key="summary",
)

# Compose into a pipeline
pipeline = SequentialAgent(
    name="cortex",
    sub_agents=[planner, analyst, summarizer],
)
