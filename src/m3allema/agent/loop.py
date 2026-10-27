"""The agent loop: think, propose a tool call, pass the gate, act, observe, repeat."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence

from m3allema.agent.interfaces import EventSink, ToolExecutor, ToolOutput
from m3allema.agent.permissions import PermissionGate
from m3allema.config.models import AgentSettings
from m3allema.domain.events import (
    AgentEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
)
from m3allema.domain.messages import (
    Message,
    StopReason,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from m3allema.domain.tools import ToolSpec
from m3allema.providers.base import INVALID_ARGUMENTS_KEY, CompletionRequest, ProviderError
from m3allema.providers.factory import ResolvedModel

MAX_TOOL_OUTPUT_CHARS = 20_000
"""Longer tool output is cut, so one large file cannot flood the context."""


class Agent:
    """Runs tasks for the owner, one conversation at a time.

    The agent keeps the conversation history between calls to :meth:`run`, so
    follow-up requests have context. Every step is yielded to the caller and
    recorded in the optional event sink.

    Args:
        model: The main model.
        tools: Where tools come from (built-in and external MCP servers).
        gate: Decides which tool calls may run.
        system_prompt: Stable instructions plus workspace context.
        settings: Step, token and timeout limits.
        sink: Receives every event, for example the event log.
        fallback: Model to try when the main one is temporarily unavailable.
        new_id: Run id factory, injectable for tests.

    """

    def __init__(
        self,
        *,
        model: ResolvedModel,
        tools: ToolExecutor,
        gate: PermissionGate,
        system_prompt: str,
        settings: AgentSettings | None = None,
        sink: EventSink | None = None,
        fallback: ResolvedModel | None = None,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._model = model
        self._fallback = fallback
        self._tools = tools
        self._gate = gate
        self._system_prompt = system_prompt
        self._settings = settings or AgentSettings()
        self._sink = sink
        self._new_id = new_id
        self._messages: list[Message] = []

    @property
    def history(self) -> Sequence[Message]:
        """The conversation so far."""
        return tuple(self._messages)

    async def run(self, task: str) -> AsyncIterator[AgentEvent]:
        """Work on ``task`` until done, yielding every step.

        The run always ends with exactly one :class:`RunFinished` event, even
        when the provider fails.
        """
        run_id = self._new_id()
        specs = {spec.name: spec for spec in self._tools.specs()}
        usage = Usage()
        steps = 0
        answer = ""
        status = "max_steps"

        yield self._emit(run_id, RunStarted(run_id=run_id, task=task, model=self._model.ref))
        self._messages.append(UserMessage(task))

        try:
            while steps < self._settings.max_steps:
                steps += 1
                turn: TurnCompleted | None = None
                async for event in self._stream_turn(tuple(specs.values())):
                    if isinstance(event, TurnCompleted):
                        turn = event
                    yield self._emit(run_id, event)
                if turn is None:  # pragma: no cover - providers always complete a turn
                    raise ProviderError("the provider ended the stream without a turn")

                usage += turn.usage
                self._messages.append(turn.message)
                answer = turn.message.text or answer
                calls = turn.message.tool_calls

                if turn.stop_reason in (StopReason.REFUSAL, StopReason.MAX_TOKENS):
                    # A cut-off tool call may have partial arguments: never run it.
                    # Unanswered calls are closed so the history stays valid for
                    # the next request in this conversation.
                    status = "refused" if turn.stop_reason is StopReason.REFUSAL else "truncated"
                    if calls:
                        self._messages.append(_not_run(calls, f"the turn ended ({status})"))
                    if status == "refused" and not answer:
                        answer = "I can't help with that request."
                    break
                if not calls:
                    status = "completed"
                    break

                results: list[ToolResult] = []
                for call in calls:
                    yield self._emit(run_id, ToolCallStarted(call))
                    started = time.perf_counter()
                    result = await self._execute(call, specs.get(call.name))
                    elapsed = int((time.perf_counter() - started) * 1000)
                    results.append(result)
                    yield self._emit(run_id, ToolCallFinished(call, result, elapsed))
                self._messages.append(ToolResultMessage(tuple(results)))
        except ProviderError as exc:
            status = "failed"
            answer = f"I couldn't reach the model: {exc}"

        yield self._emit(
            run_id,
            RunFinished(run_id=run_id, status=status, answer=answer, usage=usage, steps=steps),
        )

    async def _stream_turn(
        self, specs: tuple[ToolSpec, ...]
    ) -> AsyncIterator[TextDelta | TurnCompleted]:
        """Stream one turn from the main model, switching to the fallback on transient errors.

        The switch only happens before any text was shown, so the owner never
        sees two half-answers stitched together.
        """
        candidates = [self._model, *([self._fallback] if self._fallback else [])]
        for index, resolved in enumerate(candidates):
            request = CompletionRequest(
                model=resolved.model,
                system=self._system_prompt,
                messages=tuple(self._messages),
                tools=specs,
                max_tokens=self._settings.max_tokens,
            )
            produced_output = False
            try:
                async for event in resolved.provider.stream(request):
                    produced_output = True
                    yield event
                return
            except ProviderError as exc:
                is_last = index == len(candidates) - 1
                if is_last or produced_output or not exc.retryable:
                    raise

    async def _execute(self, call: ToolCall, spec: ToolSpec | None) -> ToolResult:
        """Validate, gate and run one tool call. Failures become error results for the model."""
        if spec is None:
            return ToolResult(call.id, f"Unknown tool {call.name!r}.", is_error=True)
        if INVALID_ARGUMENTS_KEY in call.arguments:
            return ToolResult(
                call.id, "The arguments were not valid JSON. Send them again.", is_error=True
            )

        decision = await self._gate.check(call, spec)
        if not decision.allowed:
            return ToolResult(
                call.id,
                f"Not run: {decision.reason}. Do not retry this call; "
                "tell the owner what you wanted to do and ask how to proceed.",
                is_error=True,
            )

        try:
            output = await asyncio.wait_for(
                self._tools.call(call.name, call.arguments), timeout=self._settings.tool_timeout_s
            )
        except TimeoutError:
            output = ToolOutput(f"Timed out after {self._settings.tool_timeout_s:.0f}s.", True)
        except Exception as exc:
            output = ToolOutput(f"Tool failed: {type(exc).__name__}: {exc}", True)

        return ToolResult(call.id, _truncate(output.content), is_error=output.is_error)

    def _emit(self, run_id: str, event: AgentEvent) -> AgentEvent:
        if self._sink is not None:
            self._sink.record(run_id, event)
        return event


def _not_run(calls: Sequence[ToolCall], reason: str) -> ToolResultMessage:
    return ToolResultMessage(
        tuple(ToolResult(call.id, f"Not run: {reason}.", is_error=True) for call in calls)
    )


def _truncate(content: str) -> str:
    if len(content) <= MAX_TOOL_OUTPUT_CHARS:
        return content
    dropped = len(content) - MAX_TOOL_OUTPUT_CHARS
    return f"{content[:MAX_TOOL_OUTPUT_CHARS]}\n\n[output truncated: {dropped} more characters]"


def describe_arguments(arguments: dict[str, object], limit: int = 300) -> str:
    """Compact, human-readable rendering of tool arguments for approval prompts."""
    text = json.dumps(arguments, ensure_ascii=False)
    return text if len(text) <= limit else f"{text[:limit]}..."
