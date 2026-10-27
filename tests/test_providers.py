from types import SimpleNamespace
from typing import Any

from anthropic.types import TextBlock as SdkTextBlock
from anthropic.types import ToolUseBlock

from m3allema.domain.messages import (
    AssistantMessage,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from m3allema.providers.anthropic_provider import to_anthropic_messages, to_assistant_message
from m3allema.providers.base import INVALID_ARGUMENTS_KEY
from m3allema.providers.openai_compat import _StreamAccumulator, to_openai_messages


def test_anthropic_response_keeps_raw_blocks_for_exact_replay() -> None:
    content = [
        SdkTextBlock(type="text", text="Checking."),
        ToolUseBlock(type="tool_use", id="tu1", name="files__read_file", input={"path": "a"}),
    ]
    message = to_assistant_message(content)
    assert message.text == "Checking."
    assert message.tool_calls == (ToolCall("tu1", "files__read_file", {"path": "a"}),)

    replay = to_anthropic_messages([message])[0]
    assert replay["content"] == message.raw


def test_anthropic_rebuilds_turns_from_other_providers() -> None:
    history = [
        UserMessage("hi"),
        AssistantMessage((TextBlock("x"), ToolCall("c1", "t", {"a": 1})), provider="openai_compat"),
        ToolResultMessage((ToolResult("c1", "done"),)),
    ]
    converted = to_anthropic_messages(history)
    assert converted[1]["content"][1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "t",
        "input": {"a": 1},
    }
    assert converted[2]["content"][0]["tool_use_id"] == "c1"


def test_openai_messages_split_tool_results_per_call() -> None:
    history = [
        UserMessage("hi"),
        AssistantMessage((ToolCall("c1", "t", {}), ToolCall("c2", "t", {}))),
        ToolResultMessage((ToolResult("c1", "a"), ToolResult("c2", "b"))),
    ]
    converted = to_openai_messages("sys", history)
    assert converted[0] == {"role": "system", "content": "sys"}
    assert [m["role"] for m in converted[3:]] == ["tool", "tool"]
    assert converted[2]["tool_calls"][1]["id"] == "c2"


def chunk(
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        usage=None, choices=[SimpleNamespace(finish_reason=finish_reason, delta=delta)]
    )


def fragment(
    index: int, *, call_id: str | None = None, name: str | None = None, args: str | None = None
) -> SimpleNamespace:
    function = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=index, id=call_id, function=function)


def test_openai_stream_reassembles_text_and_tool_call_fragments() -> None:
    acc = _StreamAccumulator()
    assert acc.add(chunk(content="Hel")) == "Hel"
    acc.add(chunk(content="lo"))
    acc.add(chunk(tool_calls=[fragment(0, call_id="c1", name="files__read", args='{"pa')]))
    acc.add(chunk(tool_calls=[fragment(0, args='th": "a"}')]))
    bad = fragment(1, call_id="c2", name="bad", args="{oops")
    acc.add(chunk(tool_calls=[bad], finish_reason="tool_calls"))
    acc.add(
        SimpleNamespace(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3), choices=[])
    )

    result = acc.result()
    assert result.stop_reason is StopReason.TOOL_USE
    assert result.message.text == "Hello"
    first, second = result.message.tool_calls
    assert first.arguments == {"path": "a"}
    assert INVALID_ARGUMENTS_KEY in second.arguments
    assert result.usage.input_tokens == 7
