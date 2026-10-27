"""Any OpenAI-compatible Chat Completions server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import openai

from m3allema.domain.events import StreamEvent, TextDelta, TurnCompleted
from m3allema.domain.messages import (
    AssistantMessage,
    ContentBlock,
    Message,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from m3allema.domain.tools import ToolSpec
from m3allema.providers.base import INVALID_ARGUMENTS_KEY, CompletionRequest, ProviderError

PROVIDER_NAME = "openai_compat"
_LOCAL_PLACEHOLDER_KEY = "not-needed"

_FINISH_REASONS: dict[str | None, StopReason] = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}

_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIConnectionError,
)


class OpenAICompatProvider:
    """Adapter for OpenAI-style ``/chat/completions`` endpoints.

    Args:
        api_key: Key for the server; local servers (Ollama) need none.
        base_url: Server endpoint, for example ``https://api.groq.com/openai/v1``.
        options: Reserved for adapter-specific settings.
        client: Pre-built client, mainly for tests.

    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        options: dict[str, Any] | None = None,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key or _LOCAL_PLACEHOLDER_KEY, base_url=base_url
        )
        self._options = options or {}

    @property
    def name(self) -> str:
        """Adapter name stored with the assistant messages it produces."""
        return PROVIDER_NAME

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Stream one turn; see :meth:`LLMProvider.stream`."""
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": to_openai_messages(request.system, request.messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            params["tools"] = to_openai_tools(request.tools)

        accumulator = _StreamAccumulator()
        try:
            chunks = await self._client.chat.completions.create(**params)
            async for chunk in chunks:
                if text := accumulator.add(chunk):
                    yield TextDelta(text)
        except _RETRYABLE_ERRORS as exc:
            raise ProviderError(f"provider temporarily unavailable: {exc}", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                f"provider rejected the request ({exc.status_code}): {exc}"
            ) from exc

        yield accumulator.result()


def to_openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert tool specs to Chat Completions ``tools``."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def to_openai_messages(system: str, messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Convert neutral messages to Chat Completions ``messages``.

    Tool results become one ``tool`` message per call, as the API expects.
    """
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": message.text or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in message.tool_calls
                ]
            converted.append(entry)
        elif isinstance(message, ToolResultMessage):
            converted.extend(
                {"role": "tool", "tool_call_id": r.call_id, "content": r.content}
                for r in message.results
            )
    return converted


@dataclass
class _PartialToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class _StreamAccumulator:
    """Rebuilds a whole turn from streamed chunks.

    Tool call names and JSON arguments arrive in fragments keyed by index;
    they are concatenated here and parsed once the stream ends.
    """

    text: list[str] = field(default_factory=list)
    calls: dict[int, _PartialToolCall] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)

    def add(self, chunk: Any) -> str:
        """Absorb one chunk and return any new text in it."""
        if getattr(chunk, "usage", None):
            self.usage = Usage(
                input_tokens=chunk.usage.prompt_tokens or 0,
                output_tokens=chunk.usage.completion_tokens or 0,
            )
        if not chunk.choices:
            return ""
        choice = chunk.choices[0]
        if choice.finish_reason:
            self.finish_reason = choice.finish_reason
        delta = choice.delta
        for fragment in delta.tool_calls or ():
            partial = self.calls.setdefault(fragment.index, _PartialToolCall())
            partial.id = fragment.id or partial.id
            if fragment.function is not None:
                partial.name += fragment.function.name or ""
                partial.arguments += fragment.function.arguments or ""
        if delta.content:
            self.text.append(delta.content)
            return str(delta.content)
        return ""

    def result(self) -> TurnCompleted:
        """Build the completed turn from everything accumulated."""
        blocks: list[ContentBlock] = []
        if text := "".join(self.text):
            blocks.append(TextBlock(text))
        for index in sorted(self.calls):
            partial = self.calls[index]
            blocks.append(
                ToolCall(
                    id=partial.id or f"call_{index}",
                    name=partial.name,
                    arguments=_parse_arguments(partial.arguments),
                )
            )
        stop = _FINISH_REASONS.get(self.finish_reason, StopReason.OTHER)
        if stop is StopReason.OTHER and any(isinstance(b, ToolCall) for b in blocks):
            stop = StopReason.TOOL_USE
        return TurnCompleted(
            message=AssistantMessage(blocks=tuple(blocks), provider=PROVIDER_NAME),
            stop_reason=stop,
            usage=self.usage,
        )


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {INVALID_ARGUMENTS_KEY: raw}
    return parsed if isinstance(parsed, dict) else {INVALID_ARGUMENTS_KEY: raw}
