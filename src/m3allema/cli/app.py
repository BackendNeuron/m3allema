"""The ``m3allema`` command (alias ``mek``)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from m3allema import __version__
from m3allema.cli.render import EventRenderer, terminal_approver
from m3allema.config.loader import ConfigError, load_config
from m3allema.domain.tools import Risk
from m3allema.runtime import Session, open_session, open_store
from m3allema.storage.event_store import EventStore
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

WorkspaceOption = Annotated[
    Path, typer.Option("--workspace", "-w", help="Workspace folder.", show_default="current folder")
]
AutoOption = Annotated[
    Risk,
    typer.Option(
        "--auto",
        help="Highest risk level that runs without asking: read, write or external.",
        case_sensitive=False,
    ),
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
    """Create a workspace with starter IDENTITY, BUSINESS, OWNER, RULES and config files."""
    workspace = Workspace.create(path, overwrite=force)
    console.print(f"[green]Workspace ready[/green] at {escape(str(workspace.root))}")
    console.print(
        "Next: copy .env.example to .env, add your API key, then run [bold]m3allema chat[/bold]."
    )


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What M3allema should do.")],
    workspace: WorkspaceOption = Path(),
    auto: AutoOption = Risk.READ,
) -> None:
    """Run one task and exit."""
    _run_async(_run_task(workspace, task, auto))


@app.command()
def chat(workspace: WorkspaceOption = Path(), auto: AutoOption = Risk.READ) -> None:
    """Talk to M3allema. Type 'exit' or press Ctrl+C to leave."""
    _run_async(_chat(workspace, auto))


@runs_app.command("list")
def runs_list(
    workspace: WorkspaceOption = Path(),
    limit: Annotated[int, typer.Option(help="How many runs to show.")] = 20,
) -> None:
    """Show recent runs."""
    store = _store(workspace)
    table = Table("id", "started", "status", "steps", "tokens in/out", "task")
    for run_ in store.list_runs(limit):
        table.add_row(
            run_.id[:8],
            run_.started_at.strftime("%Y-%m-%d %H:%M"),
            run_.status,
            str(run_.steps),
            f"{run_.input_tokens:,} / {run_.output_tokens:,}",
            escape(run_.task[:60]),
        )
    store.close()
    console.print(table)


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id (the first characters are enough).")],
    workspace: WorkspaceOption = Path(),
) -> None:
    """Replay every recorded step of a run."""
    store = _store(workspace)
    matches = [r for r in store.list_runs(limit=1000) if r.id.startswith(run_id)]
    if len(matches) != 1:
        store.close()
        _fail(f"no single run matches {run_id!r}")
    run_ = matches[0]
    console.print(f"[bold]{escape(run_.task)}[/bold]  [dim]{run_.id}  {run_.status}[/dim]")
    for event in store.list_events(run_.id):
        console.print(
            f"[cyan]{event.seq:>3}[/cyan] {event.kind:<20} [dim]{_summary(event.payload)}[/dim]"
        )
    store.close()


async def _run_task(root: Path, task: str, auto: Risk) -> None:
    async with open_session(root, approver=terminal_approver(console), auto_up_to=auto) as session:
        await _stream(session, task)


async def _chat(root: Path, auto: Risk) -> None:
    async with open_session(root, approver=terminal_approver(console), auto_up_to=auto) as session:
        console.print("[bold]M3allema[/bold] [dim]is listening. Type 'exit' to leave.[/dim]")
        while True:
            task = await asyncio.to_thread(console.input, "\n[bold cyan]you >[/bold cyan] ")
            if task.strip().lower() in {"exit", "quit"}:
                return
            if task.strip():
                await _stream(session, task)


async def _stream(session: Session, task: str) -> None:
    renderer = EventRenderer(console)
    async for event in session.agent.run(task):
        renderer.render(event)


def _store(root: Path) -> EventStore:
    try:
        workspace = Workspace.open(root)
        return open_store(workspace, load_config(workspace.config_path))
    except (WorkspaceError, ConfigError) as exc:
        _fail(str(exc))


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coro)
    except (WorkspaceError, ConfigError) as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(1)


def _summary(payload: dict[str, object]) -> str:
    for key in ("task", "answer", "call"):
        if key in payload:
            return escape(str(payload[key])[:100])
    return ""
