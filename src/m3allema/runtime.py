"""Composition root: wire configuration, providers, tools and storage into an agent.

Interfaces (CLI today; web UI and Telegram later) call :func:`open_session`
instead of building objects themselves, so every interface gets the same
agent with the same safety settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from m3allema.agent.loop import Agent
from m3allema.agent.permissions import Approver, RiskPolicyGate
from m3allema.config.loader import load_config
from m3allema.config.models import AppConfig
from m3allema.domain.tools import Risk
from m3allema.providers.factory import ModelRouter
from m3allema.storage.event_store import EventStore
from m3allema.tools.hub import ToolHub
from m3allema.workspace.prompt import PromptBuilder
from m3allema.workspace.workspace import Workspace


@dataclass(frozen=True, slots=True)
class Session:
    """Everything an interface needs while talking to M3allema."""

    workspace: Workspace
    config: AppConfig
    agent: Agent
    store: EventStore


def open_store(workspace: Workspace, config: AppConfig) -> EventStore:
    """Open the event store configured for ``workspace``."""
    return EventStore(config.storage.url or workspace.default_database_url)


@asynccontextmanager
async def open_session(
    root: Path, *, approver: Approver | None = None, auto_up_to: Risk | None = Risk.READ
) -> AsyncIterator[Session]:
    """Build a ready-to-use session for the workspace at ``root``.

    Args:
        root: Workspace folder.
        approver: Asks the owner about risky tool calls. Without one, they are declined.
        auto_up_to: Highest risk level that runs without asking.

    """
    workspace = Workspace.open(root)
    config = load_config(workspace.config_path)
    router = ModelRouter(config)
    main = router.resolve("main")
    if main is None:  # pragma: no cover - models.main is required by the schema
        raise ValueError("models.main is not configured")

    store = open_store(workspace, config)
    try:
        async with ToolHub.from_config(
            config.builtin_tools, config.mcp_servers, workspace.files_dir
        ) as hub:
            agent = Agent(
                model=main,
                fallback=router.resolve("fallback"),
                tools=hub,
                gate=RiskPolicyGate(auto_up_to=auto_up_to, approver=approver),
                system_prompt=PromptBuilder().build(workspace.read_context()),
                settings=config.agent,
                sink=store,
            )
            yield Session(workspace=workspace, config=config, agent=agent, store=store)
    finally:
        store.close()
