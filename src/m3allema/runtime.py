"""Composition root: wire configuration, providers, tools and storage into an agent.

Interfaces (CLI today; web UI and Telegram later) call :func:`open_session`
instead of building objects themselves, so every interface gets the same agent
with the same safety settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from m3allema.agent.context import OutputArchive
from m3allema.agent.loop import Agent
from m3allema.agent.permissions import Approver, PolicyGate
from m3allema.agent.sinks import FanOutSink, ReceiptWriter
from m3allema.config.loader import load_config, read_storage_url
from m3allema.config.models import AppConfig
from m3allema.config.policy import Policy, load_policy
from m3allema.integrations.google.auth import GoogleAuth
from m3allema.providers.factory import ModelRouter
from m3allema.providers.pricing import PriceBook
from m3allema.storage.conversation_store import ConversationStore
from m3allema.storage.database import Database
from m3allema.storage.event_store import EventStore
from m3allema.tools.hub import ToolHub
from m3allema.tools.servers import ToolContext
from m3allema.tools.trust import PendingTool, ToolTrustStore
from m3allema.workspace.prompt import PromptBuilder
from m3allema.workspace.skills import SkillLibrary
from m3allema.workspace.workspace import Workspace

TOOL_OUTPUTS_DIR = "_tool_outputs"


class ResumeError(Exception):
    """The conversation to resume does not exist or is ambiguous."""


@dataclass(frozen=True, slots=True)
class Stores:
    """The repositories of one workspace, sharing one database connection."""

    database: Database
    events: EventStore
    conversations: ConversationStore

    def close(self) -> None:
        """Release the database."""
        self.database.close()


@dataclass(frozen=True, slots=True)
class Session:
    """Everything an interface needs while talking to M3allema."""

    workspace: Workspace
    config: AppConfig
    policy: Policy
    agent: Agent
    stores: Stores
    pending_tools: tuple[PendingTool, ...] = ()


def open_stores(workspace: Workspace) -> Stores:
    """Open the workspace's stores without needing provider keys (used by ``runs``)."""
    url = read_storage_url(workspace.config_path) or workspace.default_database_url
    database = Database(url)
    return Stores(database, EventStore(database), ConversationStore(database))


def trust_store(workspace: Workspace) -> ToolTrustStore:
    """Approved fingerprints of the workspace's external MCP tools."""
    return ToolTrustStore(workspace.state_dir / "mcp_trust.json")


def google_auth(workspace: Workspace) -> GoogleAuth:
    """Google sign-in for ``workspace``."""
    return GoogleAuth(workspace.state_dir, workspace.env_path)


def _resolve_resume(conversations: ConversationStore, resume: str) -> str:
    if resume == "latest":
        latest = conversations.latest_id()
        if latest is None:
            raise ResumeError("there is no earlier conversation to resume")
        return latest
    matches = conversations.find(resume)
    if len(matches) != 1:
        raise ResumeError(f"no single conversation matches {resume!r}")
    return matches[0]


@asynccontextmanager
async def open_session(
    root: Path,
    *,
    approver: Approver | None = None,
    resume: str | None = None,
    on_receipt: Callable[[Path], None] | None = None,
) -> AsyncIterator[Session]:
    """Build a ready-to-use session for the workspace at ``root``.

    Args:
        root: Workspace folder.
        approver: Asks the owner about ``ask`` tool calls. Without one, they are declined.
        resume: ``"latest"`` or a conversation id (prefix) to continue.
        on_receipt: Called with the path of each receipt written.

    Raises:
        ResumeError: ``resume`` does not identify one conversation.

    """
    workspace = Workspace.open(root)
    config = load_config(workspace.config_path)
    policy = load_policy(workspace.policy_path)
    router = ModelRouter(config)
    main = router.resolve("main")
    if main is None:  # pragma: no cover - models.main is required by the schema
        raise ValueError("models.main is not configured")

    stores = open_stores(workspace)
    try:
        conversation_id = _resolve_resume(stores.conversations, resume) if resume else None
        history = stores.conversations.load(conversation_id) if conversation_id else ()
        sink = FanOutSink([stores.events, ReceiptWriter(workspace.receipts_dir, on_receipt)])
        tool_context = ToolContext(workspace.files_dir, google_auth(workspace), workspace.root)
        skills = SkillLibrary(workspace.root).index() if "skills" in config.builtin_tools else ""
        async with ToolHub.from_config(
            config.builtin_tools, config.mcp_servers, tool_context, trust_store(workspace)
        ) as hub:
            agent = Agent(
                model=main,
                fallback=router.resolve("fallback"),
                tools=hub,
                gate=PolicyGate(policy, approver),
                system_prompt=PromptBuilder().build(workspace.read_context(), skills),
                settings=config.agent,
                sink=sink,
                messages=stores.conversations,
                prices=PriceBook(config.pricing),
                budget=policy.budget,
                spent_today=stores.events.spent_today,
                archive=OutputArchive(workspace.files_dir / TOOL_OUTPUTS_DIR, workspace.files_dir),
                conversation_id=conversation_id,
                history=history,
            )
            yield Session(workspace, config, policy, agent, stores, tuple(hub.pending))
    finally:
        stores.close()
