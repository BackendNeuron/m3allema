"""Abstractions the agent loop depends on.

The loop never imports MCP, a database or a UI. It talks to these protocols,
and concrete implementations are injected at start-up. That keeps the loop
small, testable with simple fakes, and open to new tool sources or stores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from m3allema.domain.events import AgentEvent
from m3allema.domain.messages import Message
from m3allema.domain.tools import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """What a tool returned, as text for the model."""

    content: str
    is_error: bool = False


class ToolExecutor(Protocol):
    """Lists the available tools and runs them."""

    def specs(self) -> Sequence[ToolSpec]:
        """Every tool the model may call."""
        ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        """Run a tool. Expected failures come back as ``is_error`` outputs."""
        ...


class EventSink(Protocol):
    """Receives every step of every run (the event log, a websocket, ...)."""

    def record(self, run_id: str, event: AgentEvent) -> None:
        """Store or forward one event."""
        ...


class MessageLog(Protocol):
    """Persists conversation messages so a conversation can be resumed."""

    def append(self, conversation_id: str, message: Message) -> None:
        """Save one message at the end of a conversation."""
        ...
