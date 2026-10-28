"""FastAPI application behind ``m3allema serve``.

Endpoints:

* ``GET /`` - the dashboard (static HTML, CSS and JS bundled with the package).
* ``GET /api/...`` - status, runs, run events, conversations (read-only).
* ``GET/POST /api/onboarding`` - the onboarding interview and its answers.
* ``WS /api/ws`` - one live agent session: tasks in, events and approval
  requests out.

Security: the server binds to localhost and every API call and WebSocket must
carry the session token printed by ``m3allema serve``. WebSocket connections
from other origins are refused, so a website open in another tab cannot drive
M3allema.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from m3allema import __version__
from m3allema.agent.permissions import Approver
from m3allema.config.loader import ConfigError, load_config
from m3allema.config.policy import load_policy
from m3allema.integrations.google.auth import GoogleAuthError
from m3allema.providers.base import ProviderError
from m3allema.runtime import (
    ResumeError,
    Session,
    google_auth,
    open_session,
    open_stores,
)
from m3allema.server.approvals import WebApprover
from m3allema.speech import SpeechError, Transcriber, build_transcriber
from m3allema.storage.codec import message_to_dict
from m3allema.storage.event_store import RunRecord
from m3allema.storage.serialization import event_kind, event_to_payload
from m3allema.workspace.onboarding import (
    Answers,
    apply_answers,
    needs_onboarding,
    questions_json,
)
from m3allema.workspace.workspace import Workspace

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

SessionFactory = Callable[..., AbstractAsyncContextManager[Session]]


def create_app(
    root: Path, token: str, *, session_factory: SessionFactory = open_session
) -> FastAPI:
    """Build the dashboard app for the workspace at ``root``.

    Args:
        root: Workspace folder.
        token: Secret every request must present.
        session_factory: Builds agent sessions; replaceable in tests.

    """
    workspace = Workspace.open(root)
    app = FastAPI(title="M3allema", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_token(
        token_query: Annotated[str | None, Query(alias="token")] = None,
        token_header: Annotated[str | None, Header(alias="X-M3allema-Token")] = None,
    ) -> None:
        if not _token_ok(token_query or token_header, token):
            raise HTTPException(status_code=401, detail="missing or wrong token")

    authed = [Depends(require_token)]

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        # Revalidate every time, so a new version's hashed assets load after an upgrade.
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/status", dependencies=authed)
    async def status() -> dict[str, Any]:
        stores = open_stores(workspace)
        try:
            spent_today = stores.events.spent_today()
        finally:
            stores.close()
        policy = load_policy(workspace.policy_path)
        info: dict[str, Any] = {
            "version": __version__,
            "workspace": workspace.root.name,
            "spent_today_usd": spent_today,
            "budget": policy.budget.model_dump(),
            "policy": policy.defaults.model_dump(mode="json"),
            "google_connected": google_auth(workspace).is_connected,
        }
        try:
            config = load_config(workspace.config_path)
            info |= {"model": config.models.main, "tools": config.builtin_tools, "ready": True}
        except ConfigError as exc:
            info |= {"model": None, "tools": [], "ready": False, "problem": str(exc)}
        return info

    @app.get("/api/runs", dependencies=authed)
    async def runs(limit: int = 30) -> list[dict[str, Any]]:
        stores = open_stores(workspace)
        try:
            return [_run_json(run) for run in stores.events.list_runs(min(limit, 200))]
        finally:
            stores.close()

    @app.get("/api/runs/{run_id}/events", dependencies=authed)
    async def run_events(run_id: str) -> list[dict[str, Any]]:
        stores = open_stores(workspace)
        try:
            return [
                {"seq": e.seq, "kind": e.kind, "payload": e.payload, "at": e.created_at.isoformat()}
                for e in stores.events.list_events(run_id)
            ]
        finally:
            stores.close()

    @app.get("/api/conversations", dependencies=authed)
    async def conversations(limit: int = 30) -> list[dict[str, Any]]:
        stores = open_stores(workspace)
        try:
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "messages": c.messages,
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in stores.conversations.list_recent(min(limit, 200))
            ]
        finally:
            stores.close()

    @app.get("/api/onboarding", dependencies=authed)
    async def onboarding_questions() -> dict[str, Any]:
        return {"needed": needs_onboarding(workspace), "questions": questions_json()}

    @app.post("/api/onboarding", dependencies=authed)
    async def onboarding_apply(answers: Answers) -> dict[str, Any]:
        result = apply_answers(workspace, answers)
        return {
            "changed": list(result.changed),
            "skipped": list(result.skipped),
            "backup_dir": result.backup_dir.relative_to(workspace.root).as_posix(),
        }

    transcribers: dict[str, Transcriber | None] = {}

    @app.post("/api/transcribe", dependencies=authed)
    async def transcribe(request: Request) -> dict[str, str]:
        # The text goes back into the message box for the owner to review; it is never sent.
        if "engine" not in transcribers:
            try:
                transcribers["engine"] = build_transcriber(
                    load_config(workspace.config_path).speech
                )
            except (ConfigError, SpeechError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        engine = transcribers["engine"]
        if engine is None:
            raise HTTPException(status_code=503, detail="voice input is off (speech.engine)")
        audio = await request.body()
        try:
            result = await engine.transcribe(audio, _audio_name(request.headers))
        except SpeechError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"text": result.text, "language": result.language}

    @app.websocket("/api/ws")
    async def live(websocket: WebSocket) -> None:
        if not _token_ok(websocket.query_params.get("token"), token) or not _origin_ok(
            websocket.headers.get("origin"), websocket.url.port
        ):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        resume = websocket.query_params.get("conversation")
        await LiveSession(websocket, root, session_factory, resume).serve()

    return app


class LiveSession:
    """Drives one agent session for one browser tab."""

    def __init__(
        self,
        websocket: WebSocket,
        root: Path,
        session_factory: SessionFactory,
        resume: str | None,
    ) -> None:
        self._ws = websocket
        self._root = root
        self._factory = session_factory
        self._resume = resume
        self._send_lock = asyncio.Lock()
        self._approver = WebApprover(self.send)
        self._task: asyncio.Task[None] | None = None

    async def send(self, message: dict[str, Any]) -> None:
        """Send one JSON message; safe to call from concurrent tasks."""
        async with self._send_lock:
            await self._ws.send_json(message)

    async def serve(self) -> None:
        """Run until the browser disconnects."""
        try:
            async with self._open() as session:
                await self.send(_ready(session))
                await self._read_loop(session)
        except (ConfigError, ResumeError, GoogleAuthError, ValueError) as exc:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await self.send({"type": "fatal", "message": str(exc)})
                await self._ws.close()
        finally:
            self._approver.decline_all()
            if self._task is not None:
                self._task.cancel()

    def _open(self) -> AbstractAsyncContextManager[Session]:
        approver: Approver = self._approver
        return self._factory(
            self._root,
            approver=approver,
            resume=self._resume,
            on_receipt=self._on_receipt,
        )

    def _on_receipt(self, path: Path) -> None:
        markdown = path.read_text(encoding="utf-8")
        asyncio.get_running_loop().create_task(
            self.send({"type": "receipt", "path": path.name, "markdown": markdown})
        )

    async def _read_loop(self, session: Session) -> None:
        while True:
            try:
                message = await self._ws.receive_json()
            except WebSocketDisconnect:
                return
            kind = message.get("type")
            if kind == "approval":
                self._approver.answer(str(message.get("id")), bool(message.get("allow")))
            elif kind == "task":
                await self._start(self._run(session, str(message.get("text", "")).strip()))
            elif kind == "compact":
                await self._start(self._compact(session))
            elif kind == "new":
                await self._start(self._new(session))

    async def _start(self, work: Any) -> None:
        if self._task is not None and not self._task.done():
            work.close()
            await self.send(
                {"type": "error", "message": "M3allema is still working on the last task."}
            )
            return
        self._task = asyncio.create_task(work)

    async def _run(self, session: Session, text: str) -> None:
        if not text:
            return
        async for event in session.agent.run(text):
            await self.send(
                {"type": "event", "kind": event_kind(event), "payload": event_to_payload(event)}
            )

    async def _compact(self, session: Session) -> None:
        try:
            summary = await session.agent.compact()
        except ProviderError as exc:
            await self.send({"type": "error", "message": f"Could not compact: {exc}"})
            return
        await self.send(
            {
                "type": "compacted",
                "summary": summary,
                "conversation_id": session.agent.conversation_id,
            }
        )

    async def _new(self, session: Session) -> None:
        session.agent.start_new_conversation()
        await self.send(_ready(session))


def _ready(session: Session) -> dict[str, Any]:
    return {
        "type": "ready",
        "conversation_id": session.agent.conversation_id,
        "history": [message_to_dict(m) for m in session.agent.history],
        "pending_tools": [
            {"server": p.server, "name": p.name, "status": p.status.value}
            for p in session.pending_tools
        ],
    }


def _run_json(run: RunRecord) -> dict[str, Any]:
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "task": run.task,
        "model": run.model,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "steps": run.steps,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": run.cost_usd,
    }


def _audio_name(headers: Mapping[str, str]) -> str:
    """Pick a file name whose extension tells the engine the audio format."""
    kind = headers.get("content-type", "").split(";")[0].strip()
    extension = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
    return f"voice.{extension.get(kind, 'webm')}"


def _token_ok(given: str | None, expected: str) -> bool:
    return given is not None and secrets.compare_digest(given, expected)


def _origin_ok(origin: str | None, port: int | None) -> bool:
    """Accept only pages served by this local server (or clients without an Origin)."""
    if origin is None:
        return True
    parsed = urlparse(origin)
    return parsed.hostname in LOCAL_HOSTS and parsed.port == port
