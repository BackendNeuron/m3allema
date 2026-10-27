"""The provider interface every adapter implements."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from m3allema.domain.events import StreamEvent
from m3allema.domain.messages import Message
from m3allema.domain.tools import ToolSpec

INVALID_ARGUMENTS_KEY = "__invalid_arguments__"
"""Set in :attr:`ToolCall.arguments` when a provider returned unparseable JSON.

The agent loop sees this key and answers the call with an error result instead
of running the tool, so the model can correct itself.
"""


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """One model turn to generate.

    Attributes:
        model: Model identifier as the provider knows it (no ``provider/`` prefix).
        system: System prompt. Keep it stable across turns so it can be cached.
        messages: Conversation so far, oldest first.
        tools: Tools the model may call.
        max_tokens: Upper bound on generated tokens for this turn.

    """

    model: str
    system: str
    messages: Sequence[Message]
    tools: Sequence[ToolSpec] = field(default_factory=tuple)
    max_tokens: int = 16_000


class ProviderError(Exception):
    """A provider call failed.

    Attributes:
        retryable: True for transient failures (rate limits, overload, network),
            where trying again or switching to a fallback model makes sense.

    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class LLMProvider(Protocol):
    """Streams one model turn in M3allema's neutral format."""

    @property
    def name(self) -> str:
        """Short adapter name, stored with assistant messages it produced."""
        ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Generate one turn.

        Yields :class:`~m3allema.domain.events.TextDelta` events as text
        arrives, then exactly one
        :class:`~m3allema.domain.events.TurnCompleted`.

        Raises:
            ProviderError: The request failed.

        """
        ...
