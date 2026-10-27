from pathlib import Path

from anthropic.types import TextBlock as SdkTextBlock
from anthropic.types import ThinkingBlock, ToolUseBlock

from fakes import READ_TOOL, FakeTools, ScriptedProvider, turn
from m3allema.agent.loop import Agent
from m3allema.agent.permissions import PolicyGate
from m3allema.domain.messages import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from m3allema.providers.anthropic_provider import to_anthropic_messages, to_assistant_message
from m3allema.providers.factory import ResolvedModel
from m3allema.storage.codec import message_from_dict, message_to_dict
from m3allema.storage.conversation_store import ConversationStore
from m3allema.storage.database import Database


def make_db(tmp_path: Path) -> Database:
    return Database(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")


def test_codec_round_trip_keeps_claude_raw_blocks_exactly() -> None:
    claude_turn = to_assistant_message(
        [
            ThinkingBlock(type="thinking", thinking="", signature="sig-abc"),
            SdkTextBlock(type="text", text="Let me check."),
            ToolUseBlock(type="tool_use", id="t1", name="files__read_file", input={"path": "a"}),
        ]
    )
    messages = [
        UserMessage("hi"),
        claude_turn,
        ToolResultMessage((ToolResult("t1", "contents", is_error=False),)),
    ]
    restored = [message_from_dict(message_to_dict(m)) for m in messages]
    assert restored == messages
    assert to_anthropic_messages(restored) == to_anthropic_messages(messages)


def test_store_appends_loads_and_lists(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    store = ConversationStore(db)
    store.append("conv-1", UserMessage("Chase overdue invoices"))
    store.append("conv-1", AssistantMessage((), provider="fake"))
    store.append("conv-2", UserMessage("Weekly report"))

    assert [type(m).__name__ for m in store.load("conv-1")] == ["UserMessage", "AssistantMessage"]
    assert store.latest_id() == "conv-2"
    assert store.find("conv-") == ["conv-1", "conv-2"]
    recent = store.list_recent()
    assert [c.id for c in recent] == ["conv-2", "conv-1"]
    assert recent[1].title == "Chase overdue invoices"
    db.close()


async def test_agent_persists_and_resumes_a_conversation(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    store = ConversationStore(db)
    call = ToolCall("c1", "files__read_file", {"path": "a"})
    first = Agent(
        model=ResolvedModel("fake/m", ScriptedProvider(turn("", call), turn("Done.")), "m"),
        tools=FakeTools([READ_TOOL]),
        gate=PolicyGate(),
        system_prompt="s",
        messages=store,
    )
    _ = [e async for e in first.run("read a")]

    provider = ScriptedProvider(turn("You asked me to read a."))
    resumed = Agent(
        model=ResolvedModel("fake/m", provider, "m"),
        tools=FakeTools([READ_TOOL]),
        gate=PolicyGate(),
        system_prompt="s",
        messages=store,
        conversation_id=first.conversation_id,
        history=store.load(first.conversation_id),
    )
    _ = [e async for e in resumed.run("what did I ask?")]

    sent = provider.requests[0].messages
    assert sent[:4] == tuple(first.history)
    assert len(store.load(first.conversation_id)) == 6
    db.close()


async def test_compact_starts_a_new_conversation_from_the_summary(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    store = ConversationStore(db)
    provider = ScriptedProvider(turn("Hello."), turn("Owner asked for a greeting."), turn("Hi!"))
    agent = Agent(
        model=ResolvedModel("fake/m", provider, "m"),
        tools=FakeTools([]),
        gate=PolicyGate(),
        system_prompt="s",
        messages=store,
    )
    _ = [e async for e in agent.run("say hello")]
    old_id = agent.conversation_id

    summary = await agent.compact()

    assert summary == "Owner asked for a greeting."
    assert agent.conversation_id != old_id
    assert len(store.load(old_id)) == 2  # the old conversation is untouched
    first = agent.history[0]
    assert isinstance(first, UserMessage)
    assert "<conversation_summary>" in first.text
    _ = [e async for e in agent.run("again")]
    assert len(provider.requests[-1].messages) == 3  # summary, ack, new request
    db.close()
