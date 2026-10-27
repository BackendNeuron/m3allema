"""The ``m3allema`` command (alias ``mek``)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from m3allema import __version__
from m3allema.cli.render import EventRenderer, terminal_approver
from m3allema.config.loader import ConfigError
from m3allema.providers.base import ProviderError
from m3allema.runtime import ResumeError, Session, Stores, open_session, open_stores
from m3allema.workspace.workspace import Workspace, WorkspaceError

app = typer.Typer(
    name="m3allema",
    help="M3allema: the open-source AI back office. She drafts, asks, then acts.",
    no_args_is_help=True,
    add_completion=False,
)
runs_app = typer.Typer(help="Inspect past runs from the event log.", no_args_is_help=True)
app.add_typer(runs_app, name="runs")

console = Console()

CHAT_HELP = """\
[bold]/compact[/bold]  summarise the conversation and continue from the summary
[bold]/new[/bold]      start a fresh conversation
[bold]/help[/bold]     show this list
[bold]/exit[/bold]     leave (the conversation is saved; resume with --resume)"""

WorkspaceOption = Annotated[
    Path, typer.Option("--workspace", "-w", help="Workspace folder.", show_default="current folder")
]


def main() -> None:
    """Entry point used by the ``m3allema`` and ``mek`` scripts."""
    app()


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"m3allema {__version__}")


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Folder to create.")] = Path(),
    force: Annotated[bool, typer.Option(help="Overwrite existing template files.")] = False,
) -> None:
    """Create a workspace with starter identity, business, policy and config files."""
    workspace = Workspace.create(path, overwrite=force)
    console.print(f"[green]Workspace ready[/green] at {escape(str(workspace.root))}")
    console.print(
        "Next: copy .env.example to .env, add your API key, then run [bold]m3allema chat[/bold]."
    )


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What M3allema should do.")],
    workspace: WorkspaceOption = Path(),
) -> None:
    """Run one task and exit."""
    _run_async(_run_task(workspace, task))


@app.command()
def chat(
    workspace: WorkspaceOption = Path(),
    resume: Annotated[
        bool, typer.Option("--resume", "-r", help="Continue the most recent conversation.")
    ] = False,
    conversation: Annotated[
        str | None,
        typer.Option("--conversation", "-c", help="Continue a specific conversation by id."),
    ] = None,
) -> None:
    """Talk to M3allema. Type /help for commands."""
    target = conversation or ("latest" if resume else None)
    _run_async(_chat(workspace, target))


@app.command()
def conversations(
    workspace: WorkspaceOption = Path(),
    limit: Annotated[int, typer.Option(help="How many to show.")] = 20,
) -> None:
    """List saved conversations you can resume."""
    stores = _stores(workspace)
    try:
        table = Table("id", "last active", "messages", "started with")
        for item in stores.conversations.list_recent(limit):
            table.add_row(
                item.id[:8],
                item.updated_at.strftime("%Y-%m-%d %H:%M"),
                str(item.messages),
                escape(item.title),
            )
        console.print(table)
    finally:
        stores.close()


@runs_app.command("list")
def runs_list(
    workspace: WorkspaceOption = Path(),
    limit: Annotated[int, typer.Option(help="How many runs to show.")] = 20,
) -> None:
    """Show recent runs with status, tokens and cost."""
    stores = _stores(workspace)
    try:
        table = Table("id", "started", "status", "steps", "tokens in/out", "cost", "task")
        for item in stores.events.list_runs(limit):
            table.add_row(
                item.id[:8],
                item.started_at.strftime("%Y-%m-%d %H:%M"),
                item.status,
                str(item.steps),
                f"{item.input_tokens:,} / {item.output_tokens:,}",
                "?" if item.cost_usd is None else f"${item.cost_usd:.4f}",
                escape(item.task[:60]),
            )
        console.print(table)
        console.print(f"[dim]Spent today: ${stores.events.spent_today():.4f}[/dim]")
    finally:
        stores.close()


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id (the first characters are enough).")],
    workspace: WorkspaceOption = Path(),
) -> None:
    """Replay every recorded step of a run."""
    stores = _stores(workspace)
    try:
        matches = stores.events.find_runs(run_id)
        if len(matches) != 1:
            _fail(f"no single run matches {run_id!r}")
        item = matches[0]
        console.print(f"[bold]{escape(item.task)}[/bold]  [dim]{item.id}  {item.status}[/dim]")
        for event in stores.events.list_events(item.id):
            summary = _summary(event.payload)
            console.print(f"[cyan]{event.seq:>3}[/cyan] {event.kind:<20} [dim]{summary}[/dim]")
    finally:
        stores.close()


async def _run_task(root: Path, task: str) -> None:
    async with _open(root) as session:
        await _stream(session, task)


async def _chat(root: Path, resume: str | None) -> None:
    async with _open(root, resume) as session:
        agent = session.agent
        if resume:
            count = len(agent.history)
            console.print(
                f"[dim]Resumed conversation {agent.conversation_id[:8]} ({count} messages).[/dim]"
            )
        console.print("[bold]M3allema[/bold] [dim]is listening. /help for commands.[/dim]")
        while True:
            text = (
                await asyncio.to_thread(console.input, "\n[bold cyan]you >[/bold cyan] ")
            ).strip()
            command = text.lower()
            if command in {"/exit", "/quit", "exit", "quit"}:
                console.print("[dim]Saved. Resume with: m3allema chat --resume[/dim]")
                return
            if command == "/help":
                console.print(CHAT_HELP)
            elif command == "/compact":
                await _compact(session)
            elif command == "/new":
                await _restart(session)
            elif text:
                await _stream(session, text)


async def _compact(session: Session) -> None:
    before = len(session.agent.history)
    with console.status("Summarising the conversation..."):
        try:
            summary = await session.agent.compact()
        except ProviderError as exc:
            console.print(f"[red]Could not compact:[/red] {escape(str(exc))}")
            return
    if not summary:
        console.print("[dim]Nothing to compact yet.[/dim]")
        return
    console.print(f"[green]Compacted[/green] {before} messages into a summary:")
    console.print(f"[dim]{escape(summary)}[/dim]")


async def _restart(session: Session) -> None:
    session.agent.start_new_conversation()
    console.print("[dim]Started a new conversation.[/dim]")


async def _stream(session: Session, task: str) -> None:
    renderer = EventRenderer(console)
    async for event in session.agent.run(task):
        renderer.render(event)


def _open(root: Path, resume: str | None = None) -> AbstractAsyncContextManager[Session]:
    return open_session(
        root,
        approver=terminal_approver(console),
        resume=resume,
        on_receipt=lambda path: console.print(f"[dim]Receipt: {escape(str(path))}[/dim]"),
    )


def _stores(root: Path) -> Stores:
    try:
        return open_stores(Workspace.open(root))
    except WorkspaceError as exc:
        _fail(str(exc))


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coro)
    except (WorkspaceError, ConfigError, ResumeError) as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped. Resume with: m3allema chat --resume[/dim]")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(1)


def _summary(payload: dict[str, object]) -> str:
    for key in ("task", "answer", "call"):
        if key in payload:
            return escape(str(payload[key])[:100])
    return ""
