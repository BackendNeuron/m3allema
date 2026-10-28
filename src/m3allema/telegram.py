"""Telegram bot: talk to M3allema and approve her actions from your phone.

``m3allema telegram`` long-polls the Bot API (no public server or webhook
needed). Only the user ids in ``telegram.owner_ids`` are served; messages from
anyone else get, at most, their own id back so the owner can finish setup.

* A text message is a task.
* A voice note is transcribed and sent back with **Send** and **Edit** buttons;
  nothing runs until the owner taps Send, the same rule as the dashboard.
* Approvals arrive as messages with **Approve** and **Decline** buttons.
  Unanswered requests are declined after the usual timeout.

Messages are sent as plain text (no Markdown parsing), so text from emails or
web pages can never turn into links or formatting the owner did not expect.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any, Protocol

import httpx

from m3allema.agent.permissions import Approver
from m3allema.domain.events import RunFinished, ToolCallStarted
from m3allema.server.approvals import WebApprover
from m3allema.speech import SpeechError, Transcriber

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 4000
"""Telegram's limit is 4096; longer texts are split."""

POLL_TIMEOUT_S = 50

Keyboard = list[list[dict[str, str]]]


class TelegramError(Exception):
    """The Bot API refused a request."""


class BotApi(Protocol):
    """The few Bot API calls M3allema uses."""

    async def get_updates(self, offset: int, wait_s: int) -> list[dict[str, Any]]:
        """Wait for new updates after ``offset``."""
        ...

    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        """Send plain text; return the message id."""
        ...

    async def remove_keyboard(self, chat_id: int, message_id: int) -> None:
        """Remove the buttons under a message once they were used."""
        ...

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Acknowledge a button tap."""
        ...

    async def download_file(self, file_id: str) -> bytes:
        """Download an attachment such as a voice note."""
        ...


class HttpBotApi:
    """:class:`BotApi` over HTTPS with httpx."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=POLL_TIMEOUT_S + 10)

    async def _call(self, method: str, **params: Any) -> Any:
        response = await self._client.post(f"{self._base}/{method}", json=params)
        body = response.json()
        if not body.get("ok"):
            # The token is part of the URL; never include the URL in errors.
            raise TelegramError(f"{method} failed: {body.get('description', response.status_code)}")
        return body["result"]

    async def get_updates(self, offset: int, wait_s: int) -> list[dict[str, Any]]:
        """Long-poll for updates."""
        result: list[dict[str, Any]] = await self._call(
            "getUpdates",
            offset=offset,
            timeout=wait_s,
            allowed_updates=["message", "callback_query"],
        )
        return result

    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        """Send plain text, with inline buttons when given."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if keyboard:
            params["reply_markup"] = {"inline_keyboard": keyboard}
        message = await self._call("sendMessage", **params)
        return int(message["message_id"])

    async def remove_keyboard(self, chat_id: int, message_id: int) -> None:
        """Clear a message's inline buttons."""
        await self._call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup={"inline_keyboard": []},
        )

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Stop the button's loading spinner."""
        await self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    async def download_file(self, file_id: str) -> bytes:
        """Fetch a file by id."""
        info = await self._call("getFile", file_id=file_id)
        response = await self._client.get(f"{self._files}/{info['file_path']}")
        response.raise_for_status()
        return response.content

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


class TelegramBot:
    """Routes Telegram updates to one M3allema agent session.

    Create the bot first, open the session with :attr:`approver`, then
    :meth:`attach` the session's agent.

    Args:
        api: The Bot API.
        owner_ids: Telegram user ids allowed to use the bot.
        transcriber: Voice engine, or ``None`` when voice input is off.

    """

    def __init__(
        self,
        api: BotApi,
        owner_ids: list[int],
        transcriber: Transcriber | None = None,
    ) -> None:
        self._api = api
        self._owners = frozenset(owner_ids)
        self._agent: Any = None
        self._transcriber = transcriber
        self._chat_id: int | None = None
        self._approver = WebApprover(self._send_approval)
        self._transcripts: dict[str, str] = {}
        self._full_texts: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def approver(self) -> Approver:
        """Pass this to the session so approvals go to Telegram."""
        return self._approver

    def attach(self, agent: Any) -> None:
        """Use ``agent`` (anything with ``run(task)`` yielding events) for tasks."""
        self._agent = agent

    async def poll_forever(self) -> None:
        """Process updates until cancelled."""
        offset = 0
        while True:
            try:
                updates = await self._api.get_updates(offset, POLL_TIMEOUT_S)
            except (httpx.HTTPError, TelegramError) as exc:
                log.warning("Telegram polling failed, retrying: %s", exc)
                await asyncio.sleep(5)
                continue
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    await self.handle(update)
                except (httpx.HTTPError, TelegramError) as exc:
                    log.warning("Could not handle a Telegram update: %s", exc)

    async def handle(self, update: dict[str, Any]) -> None:
        """Handle one update (a message or a button tap)."""
        if "callback_query" in update:
            await self._on_button(update["callback_query"])
        elif "message" in update:
            await self._on_message(update["message"])

    async def wait_idle(self) -> None:
        """Wait for the current task to finish (used by tests)."""
        if self._task is not None:
            await self._task

    async def _on_message(self, message: dict[str, Any]) -> None:
        user_id = int(message.get("from", {}).get("id", 0))
        chat_id = int(message["chat"]["id"])
        if user_id not in self._owners:
            if message.get("text", "").strip() == "/start":
                await self._api.send_message(
                    chat_id,
                    f"Your Telegram id is {user_id}. Add it to telegram.owner_ids in "
                    "config.yaml to use this bot.",
                )
            return
        self._chat_id = chat_id
        if "voice" in message or "audio" in message:
            await self._on_voice(message.get("voice") or message["audio"])
            return
        text = str(message.get("text", "")).strip()
        if text == "/start":
            await self._say("Ready. Send a task, or a voice note.")
        elif text:
            await self._start(text)

    async def _on_voice(self, voice: dict[str, Any]) -> None:
        if self._transcriber is None:
            await self._say("Voice notes are off (speech.engine in config.yaml).")
            return
        try:
            audio = await self._api.download_file(str(voice["file_id"]))
            transcript = await self._transcriber.transcribe(audio, "voice.ogg")
        except SpeechError as exc:
            await self._say(f"I could not transcribe that: {exc}")
            return
        if not transcript.text:
            await self._say("I didn't catch anything. Try again?")
            return
        key = uuid.uuid4().hex[:12]
        self._transcripts[key] = transcript.text
        await self._say(
            f"I heard:\n\n{transcript.text}",
            [
                [
                    {"text": "Send", "callback_data": f"tx:{key}:send"},
                    {"text": "Edit", "callback_data": f"tx:{key}:edit"},
                ]
            ],
        )

    async def _on_button(self, query: dict[str, Any]) -> None:
        if int(query.get("from", {}).get("id", 0)) not in self._owners:
            await self._api.answer_callback(str(query["id"]))
            return
        kind, _, rest = str(query.get("data", "")).partition(":")
        key, _, choice = rest.partition(":")
        if kind == "vw":
            # Keep the Approve/Decline buttons: viewing is not deciding.
            await self._api.answer_callback(str(query["id"]))
            full = self._full_texts.get(key)
            await self._say(full if full is not None else "That request is no longer open.")
            return
        message = query.get("message", {})
        with contextlib.suppress(TelegramError, httpx.HTTPError):
            await self._api.remove_keyboard(int(message["chat"]["id"]), int(message["message_id"]))
        if kind == "ap":
            allow = choice == "yes"
            self._full_texts.pop(key, None)
            answered = self._approver.answer(key, allow)
            note = ("Approved" if allow else "Declined") if answered else "Already answered"
            await self._api.answer_callback(str(query["id"]), note)
        elif kind == "tx":
            await self._api.answer_callback(str(query["id"]))
            text = self._transcripts.pop(key, None)
            if text is None:
                await self._say("That transcript expired. Send the voice note again.")
            elif choice == "send":
                await self._start(text)
            else:
                await self._say("Send the corrected text as a message:")
                await self._say(text)

    async def _start(self, task: str) -> None:
        if self._task is not None and not self._task.done():
            await self._say("Still working on the last task. I'll tell you when it's done.")
            return
        self._task = asyncio.create_task(self._run(task))

    async def _run(self, task: str) -> None:
        await self._say("On it.")
        if self._agent is None:
            await self._say("M3allema is still starting. Try again in a moment.")
            return
        answer = ""
        try:
            async for event in self._agent.run(task):
                if isinstance(event, ToolCallStarted):
                    log.info("tool %s", event.call.name)
                elif isinstance(event, RunFinished):
                    answer = event.answer or f"Finished ({event.status})."
        except Exception as exc:
            log.exception("Telegram task failed")
            answer = f"Something went wrong: {exc}"
        await self._say(answer or "Done.")

    async def _send_approval(self, request: dict[str, Any]) -> None:
        """Render a WebApprover request as a message with buttons.

        Email addresses, links and long numbers anywhere in the arguments are
        listed at the top in full; long text gets a "View full text" button.
        """
        view = request["view"]
        lines = [f"Approve? {view['title']} ({request['risk']})", f"Tool: {request['tool']}"]
        lines += [f"{label}: {value}" for label, value in view["fields"]]
        lines += [f"! {warning}" for warning in view["warnings"]]
        if view["mentions"]:
            lines.append("Mentions: " + " · ".join(view["mentions"]))
        lines += ["", request["preview"]]
        buttons = [
            {"text": "Approve", "callback_data": f"ap:{request['id']}:yes"},
            {"text": "Decline", "callback_data": f"ap:{request['id']}:no"},
        ]
        keyboard: Keyboard = [buttons]
        if request["is_long"]:
            self._full_texts[request["id"]] = request["full_text"]
            keyboard.append([{"text": "View full text", "callback_data": f"vw:{request['id']}:"}])
        await self._say("\n".join(lines), keyboard)

    async def _say(self, text: str, keyboard: Keyboard | None = None) -> None:
        if self._chat_id is None:
            return
        chunks = [text[i : i + MAX_MESSAGE_CHARS] for i in range(0, len(text), MAX_MESSAGE_CHARS)]
        for index, chunk in enumerate(chunks or [""]):
            last = index == len(chunks) - 1
            await self._api.send_message(self._chat_id, chunk, keyboard if last else None)

    def decline_all(self) -> None:
        """Decline open approvals, e.g. on shutdown."""
        self._approver.decline_all()
