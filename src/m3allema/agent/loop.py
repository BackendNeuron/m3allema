"""The agent loop: think, propose a tool call, pass the gate, act, observe, repeat."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence

from m3allema.agent.context import OutputArchive
from m3allema.agent.interfaces import EventSink, MessageLog, ToolExecutor, ToolOutput
from m3allema.agent.permissions import PermissionGate
from m3allema.config.models import AgentSettings
from m3allema.config.policy import Budget
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
    AssistantMessage,
    Message,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from m3allema.domain.tools import ToolSpec
from m3allema.providers.base import INVALID_ARGUMENTS_KEY, CompletionRequest, ProviderError
from m3allema.providers.factory import ResolvedModel
from m3allema.providers.pricing import PriceBook

MAX_TOOL_OUTPUT_CHARS = 20_000
"""Hard cap on inline tool output when no :class:`OutputArchive` is configured."""

COMPACT_INSTRUCTION = (
    "Summarise this conversation so it can continue in a fresh context. Keep every fact, "
    "decision, number, file name and open question that matters for future requests. "
    "Note which actions were completed and which were declined. Reply with the summary only."
)

EMPTY_TURN_NUDGE = (
    "Your last reply was empty. Continue the task: use a tool if you still need one, "
    "otherwise give the owner your answer."
)
"""Sent once per run when the model ends a turn with no text and no tool call."""


class Agent:
    """Runs tasks for the owner within one conversation.

    The conversation history persists across calls to :meth:`run`, so follow-up
    requests have context. Every step is yielded to the caller and recorded in
    the event sink; every message is saved to the message log, which is what
    lets a conversation be resumed later.

    Args:
        model: The main model.
        tools: Where tools come from (built-in and external MCP servers).
        gate: Decides which tool calls may run.
        system_prompt: Stable instructions plus workspace context.
        settings: Step, token and timeout limits.
        sink: Receives every event, for example the event log.
        messages: Persists the conversation, for example the conversation store.
        fallback: Model to try when the main one is temporarily unavailable.
        prices: Turns token usage into cost.
        budget: Per-run and per-day spending limits.
        spent_today: Returns what other runs already spent today, in USD.
        archive: Moves oversized tool output out of the context.
        conversation_id: Continue this conversation instead of starting a new one.
        history: Messages of the conversation being continued.
        new_id: Id factory, injectable for tests.

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
        messages: MessageLog | None = None,
        fallback: ResolvedModel | None = None,
        prices: PriceBook | None = None,
        budget: Budget | None = None,
        spent_today: Callable[[], float] | None = None,
        archive: OutputArchive | None = None,
        conversation_id: str | None = None,
        history: Sequence[Message] = (),
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._model = model
        self._fallback = fallback
        self._tools = tools
        self._gate = gate
        self._system_prompt = system_prompt
        self._settings = settings or AgentSettings()
        self._sink = sink
        self._log = messages
        self._prices = prices or PriceBook()
        self._budget = budget or Budget()
        self._spent_today = spent_today or (lambda: 0.0)
        self._archive = archive
        self._new_id = new_id
        self._conversation_id = conversation_id or new_id()
        self._messages: list[Message] = list(history)

    @property
    def conversation_id(self) -> str:
        """Id of the current conversation."""
        return self._conversation_id

    @property
    def history(self) -> Sequence[Message]:
        """The conversation so far."""
        return tuple(self._messages)

    async def run(self, task: str) -> AsyncIterator[AgentEvent]:
        """Work on ``task`` until done, yielding every step.

        The run always ends with exactly one :class:`RunFinished` event, even
        when the provider fails or a budget is reached.
        """
        run_id = self._new_id()
        specs = {spec.name: spec for spec in self._tools.specs()}
        usage = Usage()
        cost: float | None = 0.0
        steps = 0
        answer = ""
        status = "max_steps"
        nudged = False

        yield self._emit(
            run_id,
            RunStarted(
                run_id=run_id,
                task=task,
                model=self._model.ref,
                conversation_id=self._conversation_id,
            ),
        )
        self._append(UserMessage(task))

        try:
            while steps < self._settings.max_steps:
                if reason := self._budget_exceeded(cost or 0.0):
                    status, answer = "budget", f"I stopped because {reason}."
                    break
                steps += 1
                turn: TurnCompleted | None = None
                async for event in self._stream_turn(tuple(specs.values())):
                    if isinstance(event, TurnCompleted):
                        turn = event
                    yield self._emit(run_id, event)
                if turn is None:  # pragma: no cover - providers always complete a turn
                    raise ProviderError("the provider ended the stream without a turn")

                usage += turn.usage
                cost = None if cost is None or turn.cost_usd is None else cost + turn.cost_usd
                calls = turn.message.tool_calls
                if (
                    not calls
                    and not turn.message.text.strip()
                    and turn.stop_reason is StopReason.END_TURN
                    and not nudged
                ):
                    # Some reasoning models occasionally end a turn with nothing at all.
                    # Ask once for the answer instead of finishing with an empty reply;
                    # the empty turn is not kept, since some providers reject it.
                    nudged = True
                    self._append(UserMessage(EMPTY_TURN_NUDGE))
                    continue
                self._append(turn.message)
                answer = turn.message.text or answer

                if turn.stop_reason in (StopReason.REFUSAL, StopReason.MAX_TOKENS):
                    # A cut-off tool call may have partial arguments: never run it.
                    # Unanswered calls are closed so the history stays valid.
                    status = "refused" if turn.stop_reason is StopReason.REFUSAL else "truncated"
                    if calls:
                        self._append(_not_run(calls, f"the turn ended ({status})"))
                    if status == "refused" and not answer:
                        answer = "I can't help with that request."
                    break
                if not calls:
                    status = "completed"
                    break

                results: list[ToolResult] = []
                for call in calls:
                    yield self._emit(run_id, ToolCallStarted(call))
                    spec = specs.get(call.name)
                    started = time.perf_counter()
                    result = await self._execute(call, spec)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    results.append(result)
                    risk = spec.risk.value if spec else ""
                    yield self._emit(run_id, ToolCallFinished(call, result, elapsed, risk))
                self._append(ToolResultMessage(tuple(results)))
        except ProviderError as exc:
            status = "failed"
            answer = f"I couldn't reach the model: {exc}"

        yield self._emit(
            run_id,
            RunFinished(
                run_id=run_id,
                status=status,
                answer=answer,
                usage=usage,
                steps=steps,
                cost_usd=cost,
            ),
        )

    def start_new_conversation(self) -> None:
        """Forget the live context and continue in a brand-new conversation."""
        self._conversation_id = self._new_id()
        self._messages = []

    async def compact(self) -> str:
        """Summarise the conversation and continue in a new one that starts from the summary.

        The old conversation is left untouched in storage. Only the live context
        is replaced, so earlier turns are never rewritten.

        Returns:
            The summary text.

        Raises:
            ProviderError: The model could not produce a summary.

        """
        if not self._messages:
            return ""
        request = CompletionRequest(
            model=self._model.model,
            system=self._system_prompt,
            messages=(*self._messages, UserMessage(COMPACT_INSTRUCTION)),
            max_tokens=self._settings.max_tokens,
        )
        summary = ""
        async for event in self._model.provider.stream(request):
            if isinstance(event, TurnCompleted):
                summary = event.message.text.strip()
        if not summary:
            raise ProviderError("the model returned an empty summary")

        self.start_new_conversation()
        self._append(UserMessage(f"<conversation_summary>\n{summary}\n</conversation_summary>"))
        self._append(
            AssistantMessage((TextBlock("I have the summary of our earlier conversation."),))
        )
        return summary

    async def _stream_turn(
        self, specs: tuple[ToolSpec, ...]
    ) -> AsyncIterator[TextDelta | TurnCompleted]:
        """Stream one turn from the main model, switching to the fallback on transient errors.

        The switch only happens before any text was shown, so the owner never
        sees two half-answers stitched together. The completed turn is tagged
        with the model that produced it and its cost.
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
                    if isinstance(event, TurnCompleted):
                        event = dataclasses.replace(
                            event,
                            model=resolved.ref,
                            cost_usd=self._prices.cost(resolved.model, event.usage),
                        )
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

        if self._archive is not None:
            content = self._archive.fit(call.id, call.name, output.content)
        else:
            content = _truncate(output.content)
        return ToolResult(call.id, content, is_error=output.is_error)

    def _budget_exceeded(self, run_cost: float) -> str | None:
        """Explain which budget is used up, or return ``None``."""
        per_run = self._budget.per_run_usd
        if per_run is not None and run_cost >= per_run:
            return f"this task reached its ${per_run:.2f} budget"
        per_day = self._budget.per_day_usd
        if per_day is not None and self._spent_today() + run_cost >= per_day:
            return f"today's ${per_day:.2f} budget is used up"
        return None

    def _append(self, message: Message) -> None:
        self._messages.append(message)
        if self._log is not None:
            self._log.append(self._conversation_id, message)

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
