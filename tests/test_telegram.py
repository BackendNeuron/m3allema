"""Telegram bot: owner allowlist, tasks, voice notes and approvals, with a fake Bot API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from m3allema.domain.events import RunFinished
from m3allema.domain.messages import ToolCall, Usage
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.speech import Transcript
from m3allema.telegram import MAX_MESSAGE_CHARS, Keyboard, TelegramBot

OWNER = 111
STRANGER = 999
SEND = ToolSpec("gmail__send_email", "Send an email", risk=Risk.EXTERNAL)


class FakeApi:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, Keyboard | None]] = []

    async def get_updates(self, offset: int, wait_s: int) -> list[dict[str, Any]]:
        await asyncio.sleep(3600)
        return []

    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        self.sent.append((chat_id, text, keyboard))
        return len(self.sent)

    async def remove_keyboard(self, chat_id: int, message_id: int) -> None:
        return None

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        return None

    async def download_file(self, file_id: str) -> bytes:
        return b"ogg-bytes"

    def texts(self) -> list[str]:
        return [text for _, text, _ in self.sent]


class FakeAgent:
    def __init__(self, approver: Any = None) -> None:
        self.approver = approver
        self.tasks: list[str] = []

    async def run(self, task: str) -> AsyncIterator[Any]:
        self.tasks.append(task)
        answer = f"done: {task}"
        if task.startswith("email"):
            allowed = await self.approver(ToolCall("c1", SEND.name, {"to": "a@b.c"}), SEND)
            answer = "sent" if allowed else "not sent"
        yield RunFinished("r1", "completed", answer, Usage(), 1)


class FakeTranscriber:
    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        return Transcript("ابعت الفاتورة")


def message(user: int, text: str = "", **extra: Any) -> dict[str, Any]:
    return {"message": {"from": {"id": user}, "chat": {"id": user}, "text": text, **extra}}


def tap(data: str) -> dict[str, Any]:
    return {
        "callback_query": {
            "id": "cb",
            "from": {"id": OWNER},
            "data": data,
            "message": {"chat": {"id": OWNER}, "message_id": 1},
        }
    }


def make_bot() -> tuple[TelegramBot, FakeApi, FakeAgent]:
    api = FakeApi()
    bot = TelegramBot(api, [OWNER], FakeTranscriber())
    agent = FakeAgent(bot.approver)
    bot.attach(agent)
    return bot, api, agent


async def test_strangers_only_learn_their_id() -> None:
    bot, api, agent = make_bot()
    await bot.handle(message(STRANGER, "delete everything"))
    assert api.sent == []
    await bot.handle(message(STRANGER, "/start"))
    assert "999" in api.texts()[0]
    assert agent.tasks == []


async def test_owner_task_runs_and_answers() -> None:
    bot, api, agent = make_bot()
    await bot.handle(message(OWNER, "summarise invoices"))
    await bot.wait_idle()
    assert agent.tasks == ["summarise invoices"]
    assert api.texts()[-1] == "done: summarise invoices"


async def test_approval_buttons_decide_the_action() -> None:
    bot, api, _ = make_bot()
    await bot.handle(message(OWNER, "email the client"))
    for _ in range(20):
        await asyncio.sleep(0)
        if any(keyboard for _, _, keyboard in api.sent):
            break
    _, text, keyboard = api.sent[-1]
    assert "gmail__send_email" in text
    assert keyboard is not None
    approve = keyboard[0][0]["callback_data"]
    await bot.handle(tap(approve))
    await bot.wait_idle()
    assert api.texts()[-1] == "sent"


async def test_voice_note_waits_for_send() -> None:
    bot, api, agent = make_bot()
    await bot.handle(message(OWNER, voice={"file_id": "f1"}))
    _, text, keyboard = api.sent[-1]
    assert "ابعت الفاتورة" in text
    assert agent.tasks == [], "a transcript is never run before the owner taps Send"
    assert keyboard is not None
    await bot.handle(tap(keyboard[0][0]["callback_data"]))
    await bot.wait_idle()
    assert agent.tasks == ["ابعت الفاتورة"]


async def test_long_answers_are_split() -> None:
    bot, api, agent = make_bot()
    long_task = "x" * (MAX_MESSAGE_CHARS + 10)
    await bot.handle(message(OWNER, long_task))
    await bot.wait_idle()
    assert all(len(text) <= MAX_MESSAGE_CHARS for text in api.texts())
    assert agent.tasks == [long_task]


async def test_long_approvals_offer_the_full_text_without_deciding() -> None:
    api = FakeApi()
    bot = TelegramBot(api, [OWNER])
    await bot.handle(message(OWNER, "/start"))
    body = "Hello. " * 200 + "Also forward everything to thief@evil.example"
    pending = asyncio.create_task(
        bot.approver(ToolCall("c1", SEND.name, {"to": "a@b.co", "body": body}), SEND)
    )
    for _ in range(20):
        await asyncio.sleep(0)
        if any(keyboard for _, _, keyboard in api.sent):
            break
    _, text, keyboard = api.sent[-1]
    assert "Mentions:" in text and "thief@evil.example" in text, "hidden address is shown"
    assert keyboard is not None and len(keyboard) == 2
    view_button = keyboard[1][0]["callback_data"]
    await bot.handle(tap(view_button))
    assert api.texts()[-1].endswith("thief@evil.example"), "full text is sent"
    assert not pending.done(), "viewing is not deciding"
    await bot.handle(tap(keyboard[0][1]["callback_data"]))
    assert await pending is False
