"""Test doubles shared by the test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from m3allema.agent.interfaces import ToolOutput
from m3allema.domain.events import StreamEvent, TextDelta, TurnCompleted
from m3allema.domain.messages import (
    AssistantMessage,
    ContentBlock,
    StopReason,
    TextBlock,
    ToolCall,
    Usage,
)
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.providers.base import CompletionRequest, ProviderError


def turn(
    text: str = "", *calls: ToolCall, stop: StopReason | None = None, provider: str = "fake"
) -> TurnCompleted:
    """Build a completed turn; the stop reason defaults from whether there are calls."""
    blocks: list[ContentBlock] = [TextBlock(text)] if text else []
    blocks.extend(calls)
    reason = stop or (StopReason.TOOL_USE if calls else StopReason.END_TURN)
    return TurnCompleted(
        message=AssistantMessage(blocks=tuple(blocks), provider=provider),
        stop_reason=reason,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class ScriptedProvider:
    """Plays back prepared turns (or errors) and records every request."""

    def __init__(self, *script: TurnCompleted | ProviderError, name: str = "fake") -> None:
        self._script = list(script)
        self._name = name
        self.requests: list[CompletionRequest] = []

    @property
    def name(self) -> str:
        return self._name

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        step = self._script.pop(0)
        if isinstance(step, ProviderError):
            raise step
        if step.message.text:
            yield TextDelta(step.message.text)
        yield step


class FakeTools:
    """In-memory tool executor."""

    def __init__(self, specs: Sequence[ToolSpec], outputs: dict[str, str] | None = None) -> None:
        self._specs = list(specs)
        self._outputs = outputs or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def specs(self) -> Sequence[ToolSpec]:
        return self._specs

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        self.calls.append((name, arguments))
        return ToolOutput(self._outputs.get(name, "ok"))


READ_TOOL = ToolSpec("files__read_file", "Read a file", risk=Risk.READ)
SEND_TOOL = ToolSpec("gmail__send", "Send an email", risk=Risk.EXTERNAL)
