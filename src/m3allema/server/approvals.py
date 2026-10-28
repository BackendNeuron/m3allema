"""Approvals over a WebSocket: ask the owner in the browser and wait for the answer."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import ToolSpec

Send = Callable[[dict[str, Any]], Awaitable[None]]

APPROVAL_TIMEOUT_S = 15 * 60
"""An unanswered request is declined after this long."""


class WebApprover:
    """An :data:`~m3allema.agent.permissions.Approver` that asks through the dashboard.

    Each request gets an id; the browser answers with that id. Requests that
    are never answered (closed tab, timeout) are declined, so a run never
    performs a risky action without an explicit yes.

    Args:
        send: Sends one JSON message to the browser.
        timeout_s: How long to wait for an answer.

    """

    def __init__(self, send: Send, timeout_s: float = APPROVAL_TIMEOUT_S) -> None:
        self._send = send
        self._timeout_s = timeout_s
        self._waiting: dict[str, asyncio.Future[bool]] = {}

    async def __call__(self, call: ToolCall, spec: ToolSpec) -> bool:
        """Ask the owner about ``call``; ``True`` only on an explicit approval."""
        request_id = uuid.uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = future
        try:
            await self._send(
                {
                    "type": "approval_request",
                    "id": request_id,
                    "tool": call.name,
                    "risk": spec.risk.value,
                    "description": spec.description,
                    "arguments": call.arguments,
                }
            )
            return await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError:
            return False
        finally:
            self._waiting.pop(request_id, None)

    def answer(self, request_id: str, allow: bool) -> bool:
        """Deliver the owner's answer. Returns whether a request was waiting for it."""
        future = self._waiting.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(allow)
        return True

    def decline_all(self) -> None:
        """Decline every open request, for example when the browser disconnects."""
        for future in self._waiting.values():
            if not future.done():
                future.set_result(False)
