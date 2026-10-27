"""Events emitted while the agent works.

Two layers of events exist:

* :data:`StreamEvent` - what a provider adapter yields while one model turn
  streams in.
* :data:`AgentEvent` - what the agent loop yields to interfaces (CLI, web UI,
  Telegram) and records in the event log. Every step of a run is one of these,
  which is what makes runs observable and replayable.
"""

from __future__ import annotations

from dataclasses import dataclass

from m3allema.domain.messages import AssistantMessage, StopReason, ToolCall, ToolResult, Usage


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of model text, streamed as it is generated."""

    text: str


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    """A model turn finished; carries the whole assistant message.

    Attributes:
        model: ``provider/model`` that produced the turn (set by the agent, since a
            fallback model may have answered).
        cost_usd: Price of the turn, or ``None`` when the model's price is unknown.

    """

    message: AssistantMessage
    stop_reason: StopReason
    usage: Usage
    model: str = ""
    cost_usd: float | None = None


StreamEvent = TextDelta | TurnCompleted


@dataclass(frozen=True, slots=True)
class RunStarted:
    """The agent accepted a task."""

    run_id: str
    task: str
    model: str
    conversation_id: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallStarted:
    """The agent is about to run a tool."""

    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolCallFinished:
    """A tool finished (or failed); the result goes back to the model."""

    call: ToolCall
    result: ToolResult
    duration_ms: int
    risk: str = ""


@dataclass(frozen=True, slots=True)
class RunFinished:
    """The run ended.

    Attributes:
        status: ``completed``, ``refused``, ``max_steps``, ``truncated``, ``budget``
            or ``failed``.
        answer: The final text shown to the owner.
        usage: Total tokens across every turn of the run.
        steps: Number of model turns taken.
        cost_usd: Total price, or ``None`` if any turn's price was unknown.

    """

    run_id: str
    status: str
    answer: str
    usage: Usage
    steps: int
    cost_usd: float | None = None


AgentEvent = (
    TextDelta | TurnCompleted | RunStarted | ToolCallStarted | ToolCallFinished | RunFinished
)
