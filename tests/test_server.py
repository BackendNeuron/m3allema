"""Dashboard server: token and origin checks, REST endpoints and the live WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from m3allema.domain.events import TextDelta
from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.server.app import _origin_ok, create_app
from m3allema.server.approvals import WebApprover
from m3allema.workspace.workspace import Workspace

TOKEN = "test-token"  # noqa: S105 - test value, not a secret
SEND = ToolSpec("gmail__send", "Send an email", risk=Risk.EXTERNAL)


class FakeAgent:
    """Streams one text event, asking for approval first when the task says so."""

    def __init__(self, approver: Any) -> None:
        self.approver = approver
        self.conversation_id = "conv-1"
        self.history: list[Any] = []

    async def run(self, task: str) -> AsyncIterator[Any]:
        if task.startswith("send"):
            allowed = await self.approver(ToolCall("c1", "gmail__send", {"to": "a@b.c"}), SEND)
            yield TextDelta("sent" if allowed else "declined")
        else:
            yield TextDelta(f"echo: {task}")

    async def compact(self) -> str:
        return "summary"

    def start_new_conversation(self) -> None:
        self.conversation_id = "conv-2"


def fake_factory(root: Path, *, approver: Any, resume: str | None, on_receipt: Any) -> Any:
    @asynccontextmanager
    async def session() -> AsyncIterator[Any]:
        yield SimpleNamespace(agent=FakeAgent(approver), pending_tools=())

    return session()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    Workspace.create(tmp_path)
    return TestClient(create_app(tmp_path, TOKEN, session_factory=fake_factory))


def test_api_requires_token(client: TestClient) -> None:
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", params={"token": "wrong"}).status_code == 401
    ok = client.get("/api/status", headers={"X-M3allema-Token": TOKEN})
    assert ok.status_code == 200
    assert ok.json()["workspace"]


def test_runs_and_conversations_start_empty(client: TestClient) -> None:
    params = {"token": TOKEN}
    assert client.get("/api/runs", params=params).json() == []
    assert client.get("/api/conversations", params=params).json() == []


def test_onboarding_endpoints(client: TestClient) -> None:
    params = {"token": TOKEN}
    interview = client.get("/api/onboarding", params=params).json()
    assert interview["needed"] is True
    assert interview["questions"][0]["id"] == "business_name"
    bad = client.post("/api/onboarding", params=params, json={"business_name": "x"})
    assert bad.status_code == 422
    good = client.post(
        "/api/onboarding",
        params=params,
        json={"business_name": "Nour", "offering": "Cakes", "owner_name": "Mona"},
    )
    assert good.status_code == 200
    assert "BUSINESS.md" in good.json()["changed"]
    assert client.get("/api/onboarding", params=params).json()["needed"] is False
    assert client.post("/api/onboarding", json={}).status_code == 401


def test_index_is_revalidated(client: TestClient) -> None:
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_websocket_rejects_missing_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws") as ws:
        ws.receive_json()


def test_websocket_rejects_foreign_origin(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/ws?token={TOKEN}", headers={"origin": "https://evil.example"}
        ) as ws,
    ):
        ws.receive_json()


def test_origin_check() -> None:
    assert _origin_ok(None, 8765)
    assert _origin_ok("http://127.0.0.1:8765", 8765)
    assert _origin_ok("http://localhost:8765", 8765)
    assert not _origin_ok("http://localhost:9999", 8765)
    assert not _origin_ok("https://evil.example:8765", 8765)


def test_websocket_task_streams_events(client: TestClient) -> None:
    with client.websocket_connect(f"/api/ws?token={TOKEN}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["conversation_id"] == "conv-1"
        ws.send_json({"type": "task", "text": "hello"})
        event = ws.receive_json()
        assert event == {"type": "event", "kind": "text_delta", "payload": {"text": "echo: hello"}}


def test_websocket_approval_round_trip(client: TestClient) -> None:
    with client.websocket_connect(f"/api/ws?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "task", "text": "send it"})
        request = ws.receive_json()
        assert request["type"] == "approval_request"
        assert request["risk"] == "external"
        ws.send_json({"type": "approval", "id": request["id"], "allow": True})
        assert ws.receive_json()["payload"]["text"] == "sent"


def test_websocket_compact_and_new(client: TestClient) -> None:
    with client.websocket_connect(f"/api/ws?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "compact"})
        assert ws.receive_json() == {
            "type": "compacted",
            "summary": "summary",
            "conversation_id": "conv-1",
        }
        ws.send_json({"type": "new"})
        assert ws.receive_json()["conversation_id"] == "conv-2"


async def test_web_approver_declines_unanswered_requests() -> None:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    approver = WebApprover(send, timeout_s=5)
    pending = asyncio.create_task(approver(ToolCall("c1", "gmail__send", {}), SEND))
    await asyncio.sleep(0)
    approver.decline_all()
    assert await pending is False
    assert not approver.answer(sent[0]["id"], True)


async def test_web_approver_times_out() -> None:
    async def send(message: dict[str, Any]) -> None:
        return None

    approver = WebApprover(send, timeout_s=0.01)
    assert await approver(ToolCall("c1", "gmail__send", {}), SEND) is False
