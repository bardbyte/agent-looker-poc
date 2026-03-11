"""Thinking events for real-time agent visualization.

Extracted from chat.py lines 112-211.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ThinkingType(str, Enum):
    """Types of thinking events for visualization."""
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class ThinkingEvent:
    """Represents a thinking event from the agent."""
    type: ThinkingType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ThinkingCallback(ABC):
    """Abstract callback for receiving thinking events."""

    @abstractmethod
    def on_thinking(self, event: ThinkingEvent) -> None:
        """Called when a thinking event occurs."""
        pass


class ConsoleCallback(ThinkingCallback):
    """Callback that prints thinking events to console with rich formatting."""

    def __init__(self, use_rich: bool = True):
        self.use_rich = use_rich
        self._console = None

        if use_rich:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                self.use_rich = False

    def on_thinking(self, event: ThinkingEvent) -> None:
        """Print thinking event to console."""
        if self.use_rich and self._console:
            self._print_rich(event)
        else:
            self._print_plain(event)

    def _print_rich(self, event: ThinkingEvent) -> None:
        """Print with rich formatting."""
        from rich.panel import Panel
        from rich.markdown import Markdown

        styles = {
            ThinkingType.REASONING: ("bold blue", "Thinking"),
            ThinkingType.TOOL_CALL: ("bold yellow", "Tool Call"),
            ThinkingType.TOOL_RESULT: ("bold green", "Tool Result"),
            ThinkingType.FINAL_ANSWER: ("bold cyan", "Answer"),
            ThinkingType.ERROR: ("bold red", "Error"),
        }

        style, title = styles.get(event.type, ("white", "Event"))

        if event.type == ThinkingType.TOOL_CALL:
            tool_name = event.metadata.get("tool_name", "unknown")
            title = f"Tool Call: {tool_name}"

        content = event.content
        if event.type in [ThinkingType.REASONING, ThinkingType.FINAL_ANSWER]:
            try:
                content = Markdown(event.content)
            except Exception:
                pass

        self._console.print(Panel(
            content,
            title=title,
            style=style,
            expand=False,
        ))

    def _print_plain(self, event: ThinkingEvent) -> None:
        """Print without rich formatting."""
        prefixes = {
            ThinkingType.REASONING: "[THINKING]",
            ThinkingType.TOOL_CALL: "[TOOL CALL]",
            ThinkingType.TOOL_RESULT: "[TOOL RESULT]",
            ThinkingType.FINAL_ANSWER: "[ANSWER]",
            ThinkingType.ERROR: "[ERROR]",
        }

        prefix = prefixes.get(event.type, "[EVENT]")

        if event.type == ThinkingType.TOOL_CALL:
            tool_name = event.metadata.get("tool_name", "unknown")
            prefix = f"[TOOL CALL: {tool_name}]"

        print(f"\n{prefix}")
        print("-" * 50)
        print(event.content)
        print("-" * 50)


def _wrap_callback(fn: Callable[[ThinkingEvent], None]) -> ThinkingCallback:
    """Wrap a plain function/lambda as a ThinkingCallback."""

    class _Wrapper(ThinkingCallback):
        def on_thinking(self, event: ThinkingEvent) -> None:
            fn(event)

    return _Wrapper()
