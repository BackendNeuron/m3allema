"""Claude through the official Anthropic SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

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
from m3allema.providers.base import CompletionRequest, ProviderError

PROVIDER_NAME = "anthropic"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_STOP_REASONS: dict[str | None, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}

_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
)


class AnthropicProvider:
    """Adapter for the Claude Messages API.

    Native features kept on purpose:

    * Prompt caching: the request is marked cacheable, so the stable system
      prompt and tool list are reused across the turns of a run.
    * Effort: ``options["effort"]`` maps to ``output_config.effort``.
    * Refusal fallbacks: when ``options["refusal_fallback"]`` is true (the
      default), the server retries a declined request on a suitable model.
    * Exact replay: each assistant turn keeps the SDK's own content blocks,
      including thinking blocks, and sends them back unchanged.

    Args:
        api_key: Anthropic API key. ``None`` lets the SDK find credentials itself.
        base_url: Optional endpoint override.
        options: ``effort`` and ``refusal_fallback``.
        client: Pre-built client, mainly for tests.

    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        options: dict[str, Any] | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
        self._options = options or {}

    @property
    def name(self) -> str:
        """Adapter name stored with the assistant messages it produces."""
        return PROVIDER_NAME

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Stream one Claude turn; see :meth:`LLMProvider.stream`."""
        params = self._build_params(request)
        try:
            if self._options.get("refusal_fallback", True):
                stream_ctx: Any = self._client.beta.messages.stream(
                    betas=[FALLBACK_BETA], fallbacks="default", **params
                )
            else:
                stream_ctx = self._client.messages.stream(**params)
            async with stream_ctx as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                final = await stream.get_final_message()
        except _RETRYABLE_ERRORS as exc:
            raise ProviderError(
                f"Claude is temporarily unavailable: {exc}", retryable=True
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Claude rejected the request ({exc.status_code}): {exc}") from exc

        yield TurnCompleted(
            message=to_assistant_message(final.content),
            stop_reason=_STOP_REASONS.get(final.stop_reason, StopReason.OTHER),
            usage=Usage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
                cache_read_tokens=final.usage.cache_read_input_tokens or 0,
                cache_write_tokens=final.usage.cache_creation_input_tokens or 0,
            ),
        )

    def _build_params(self, request: CompletionRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": to_anthropic_messages(request.messages),
            "cache_control": {"type": "ephemeral"},
        }
        if request.tools:
            params["tools"] = to_anthropic_tools(request.tools)
        if effort := self._options.get("effort"):
            params["output_config"] = {"effort": effort}
        return params


def to_anthropic_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert tool specs to Messages API tool definitions."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def to_anthropic_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Convert neutral messages to Messages API ``messages``.

    Assistant turns produced by this adapter are replayed from ``raw``
    verbatim; turns from other providers are rebuilt from neutral blocks.
    """
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantMessage):
            converted.append({"role": "assistant", "content": _assistant_content(message)})
        elif isinstance(message, ToolResultMessage):
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
                        for r in message.results
                    ],
                }
            )
    return converted


def _assistant_content(message: AssistantMessage) -> list[dict[str, Any]]:
    if message.provider == PROVIDER_NAME and message.raw is not None:
        return list(message.raw)
    content: list[dict[str, Any]] = []
    for block in message.blocks:
        if isinstance(block, TextBlock):
            if block.text:
                content.append({"type": "text", "text": block.text})
        else:
            content.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.arguments}
            )
    return content


def to_assistant_message(content: Sequence[Any]) -> AssistantMessage:
    """Convert SDK response blocks to a neutral assistant message.

    Text and tool-use blocks become neutral blocks; every block, thinking
    included, is also serialized into ``raw`` for exact replay.
    """
    blocks: list[ContentBlock] = []
    for block in content:
        if block.type == "text":
            blocks.append(TextBlock(block.text))
        elif block.type == "tool_use":
            arguments = block.input if isinstance(block.input, dict) else {}
            blocks.append(ToolCall(id=block.id, name=block.name, arguments=arguments))
    raw = [block.model_dump(mode="json", exclude_none=True) for block in content]
    return AssistantMessage(blocks=tuple(blocks), provider=PROVIDER_NAME, raw=raw)
