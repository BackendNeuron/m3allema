"""Convert conversation messages to and from JSON, losslessly.

Round-tripping must be exact: a resumed conversation is sent back to the
provider, and Claude rejects replayed thinking blocks that changed.
"""

from __future__ import annotations

from typing import Any

from m3allema.domain.messages import (
    AssistantMessage,
    ContentBlock,
    Message,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)


class CodecError(ValueError):
    """Stored data does not describe a valid message."""


def message_to_dict(message: Message) -> dict[str, Any]:
    """Serialize a message to a JSON-compatible dict."""
    if isinstance(message, UserMessage):
        return {"role": "user", "text": message.text}
    if isinstance(message, AssistantMessage):
        return {
            "role": "assistant",
            "blocks": [_block_to_dict(b) for b in message.blocks],
            "provider": message.provider,
            "raw": message.raw,
        }
    return {
        "role": "tool",
        "results": [
            {"call_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in message.results
        ],
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    """Rebuild a message serialized by :func:`message_to_dict`.

    Raises:
        CodecError: ``data`` has an unknown role or missing fields.

    """
    try:
        role = data["role"]
        if role == "user":
            return UserMessage(data["text"])
        if role == "assistant":
            return AssistantMessage(
                blocks=tuple(_block_from_dict(b) for b in data["blocks"]),
                provider=data.get("provider"),
                raw=data.get("raw"),
            )
        if role == "tool":
            return ToolResultMessage(
                tuple(
                    ToolResult(r["call_id"], r["content"], is_error=r["is_error"])
                    for r in data["results"]
                )
            )
    except (KeyError, TypeError) as exc:
        raise CodecError(f"malformed message: {exc}") from exc
    raise CodecError(f"unknown message role {data.get('role')!r}")


def _block_to_dict(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    return {"type": "tool_call", "id": block.id, "name": block.name, "arguments": block.arguments}


def _block_from_dict(data: dict[str, Any]) -> ContentBlock:
    if data["type"] == "text":
        return TextBlock(data["text"])
    if data["type"] == "tool_call":
        return ToolCall(data["id"], data["name"], data["arguments"])
    raise CodecError(f"unknown block type {data['type']!r}")
