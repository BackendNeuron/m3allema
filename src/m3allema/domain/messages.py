"""Conversation messages in M3allema's own, provider-neutral format.

Each provider adapter translates these types to and from its SDK's wire
format. Assistant messages may also carry a provider-specific ``raw`` payload
so that an adapter can replay its own output byte-for-byte on the next turn
(required, for example, to keep Claude's thinking blocks valid).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Who authored a message."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(StrEnum):
    """Why the model stopped generating a turn."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A run of plain text."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A request from the model to run a tool.

    Attributes:
        id: Provider-issued identifier, echoed back in the matching result.
        name: Fully qualified tool name, for example ``files__read_file``.
        arguments: Parsed JSON arguments. Treat as untrusted model output.

    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of running one tool call."""

    call_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ToolCall


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for one model turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True, slots=True)
class UserMessage:
    """A message typed (or spoken) by the business owner."""

    text: str
    role: Role = field(default=Role.USER, init=False)


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """A model turn: text and/or tool calls.

    Attributes:
        blocks: Neutral content, in the order the model produced it.
        provider: Name of the adapter that produced ``raw``, if any.
        raw: The provider's own serialized content, replayed verbatim by the
            same adapter. Other adapters ignore it and rebuild from ``blocks``.

    """

    blocks: tuple[ContentBlock, ...]
    provider: str | None = None
    raw: Any = None
    role: Role = field(default=Role.ASSISTANT, init=False)

    @property
    def text(self) -> str:
        """All text blocks joined together."""
        return "".join(b.text for b in self.blocks if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        """The tool calls in this turn, in order."""
        return tuple(b for b in self.blocks if isinstance(b, ToolCall))


@dataclass(frozen=True, slots=True)
class ToolResultMessage:
    """The results of every tool call from the previous assistant turn.

    All results of one turn travel together in a single message, which is
    what providers expect for parallel tool use.
    """

    results: tuple[ToolResult, ...]
    role: Role = field(default=Role.TOOL, init=False)


Message = UserMessage | AssistantMessage | ToolResultMessage
