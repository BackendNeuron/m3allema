"""The ``m3allema`` command (alias ``mek``)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.table import Table

from m3allema import __version__
from m3allema.cli.render import EventRenderer, terminal_approver
from m3allema.config.loader import ConfigError, load_config
from m3allema.integrations.google.auth import SCOPES, GoogleAuthError
from m3allema.providers.base import ProviderError
from m3allema.runtime import (
    ResumeError,
    Session,
    Stores,
    google_auth,
    open_session,
    open_stores,
    trust_store,
)
from m3allema.tools.hub import ToolHub
from m3allema.tools.trust import PendingTool
from m3allema.workspace.onboarding import (
    QUESTIONS,
    Answers,
    Kind,
    Question,
    apply_answers,
    questions_json,
)
from m3allema.workspace.workspace import Workspace, WorkspaceError

app = typer.Typer(
    name="m3allema",
    help="M3allema: the open-source AI back office. She drafts, asks, then acts.",
    no_args_is_help=True,
    add_completion=False,
)
runs_app = typer.Typer(help="Inspect past runs from the event log.", no_args_is_help=True)
app.add_typer(runs_app, name="runs")
google_app = typer.Typer(help="Connect Gmail, Calendar and Sheets.", no_args_is_help=True)
app.add_typer(google_app, name="google")
mcp_app = typer.Typer(help="Review and approve external MCP servers.", no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")

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
        "Next: run [bold]m3allema onboard[/bold] (or use the dashboard), copy .env.example to "
        ".env and add your API key, then run [bold]m3allema chat[/bold]."
    )


@app.command()
def onboard(workspace: WorkspaceOption = Path()) -> None:
    """Answer a short interview that fills in the workspace files for your business."""
    ws = _workspace(workspace)
    defaults = {q["id"]: q["default"] for q in questions_json()}
    answers: dict[str, Any] = {}
    section = ""
    for question in QUESTIONS:
        if question.section != section:
            section = question.section
            console.print(f"\n[bold]{escape(section)}[/bold]")
        answers[question.id] = _ask(question, defaults.get(question.id))
    try:
        result = apply_answers(ws, Answers.model_validate(answers))
    except ValidationError as exc:
        _fail(str(exc))
    console.print(f"\n[green]Updated:[/green] {', '.join(result.changed) or 'nothing changed'}")
    for item in result.skipped:
        console.print(f"[yellow]Set by hand:[/yellow] {escape(item)}")
    console.print(f"[dim]Previous versions: {escape(str(result.backup_dir))}[/dim]")


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
def serve(
    workspace: WorkspaceOption = Path(),
    port: Annotated[int, typer.Option(help="Local port.")] = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the dashboard in the browser.")
    ] = True,
) -> None:
    """Start the web dashboard on this computer only (127.0.0.1)."""
    import os
    import secrets
    import webbrowser

    import uvicorn

    from m3allema.server.app import create_app

    ws = _workspace(workspace)
    # A fixed token can be set for development; normally a fresh one is made per start.
    access_token = os.environ.get("M3ALLEMA_DASHBOARD_TOKEN") or secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{port}/?token={access_token}"
    console.print(f"[bold]M3allema dashboard[/bold] for {escape(ws.root.name)}")
    console.print(f"Open: [cyan]{url}[/cyan]")
    console.print("[dim]The link contains a private access token. Press Ctrl+C to stop.[/dim]")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(ws.root, access_token), host="127.0.0.1", port=port, log_level="warning")


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


@google_app.command("connect")
def google_connect(
    client_secret: Annotated[
        Path,
        typer.Option(
            "--client-secret", help="OAuth client JSON downloaded from Google Cloud (Desktop app)."
        ),
    ],
    workspace: WorkspaceOption = Path(),
) -> None:
    """Sign in to Google once; the token is stored encrypted in the workspace."""
    auth = google_auth(_workspace(workspace))
    console.print("Opening Google's sign-in page in your browser...")
    try:
        message = auth.connect(client_secret)
    except GoogleAuthError as exc:
        _fail(str(exc))
    console.print(f"[green]{escape(message)}[/green]")
    console.print(
        "Enable the tools in config.yaml: builtin_tools: [files, excel, docs, web, "
        "gmail, calendar, sheets]"
    )


@google_app.command("status")
def google_status(workspace: WorkspaceOption = Path()) -> None:
    """Show whether Google is connected and still valid."""
    auth = google_auth(_workspace(workspace))
    if not auth.is_connected:
        console.print(
            "[yellow]Not connected.[/yellow] Run: m3allema google connect --client-secret FILE"
        )
        return
    try:
        auth.credentials()
    except GoogleAuthError as exc:
        _fail(str(exc))
    scopes = ", ".join(s.rsplit("/", 1)[-1] for s in SCOPES)
    console.print(f"[green]Connected[/green] [dim]({scopes})[/dim]")


@google_app.command("disconnect")
def google_disconnect(workspace: WorkspaceOption = Path()) -> None:
    """Delete the stored Google sign-in from this workspace."""
    removed = google_auth(_workspace(workspace)).disconnect()
    console.print("Disconnected." if removed else "Google was not connected.")
    console.print(
        "[dim]To revoke access completely, also remove the app at "
        "https://myaccount.google.com/permissions[/dim]"
    )


@mcp_app.command("list")
def mcp_list(workspace: WorkspaceOption = Path()) -> None:
    """Show external MCP servers and which of their tools wait for approval."""
    _run_async(_mcp_review(workspace, server=None, approve=False))


@mcp_app.command("trust")
def mcp_trust(
    server: Annotated[str, typer.Argument(help="Server name from config.yaml mcp_servers.")],
    workspace: WorkspaceOption = Path(),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Approve without asking.")] = False,
) -> None:
    """Review an external server's tools and approve them as they are now."""
    _run_async(_mcp_review(workspace, server=server, approve=True, assume_yes=yes))


async def _mcp_review(
    root: Path, *, server: str | None, approve: bool, assume_yes: bool = False
) -> None:
    ws = _workspace(root)
    config = load_config(ws.config_path)
    servers = config.mcp_servers
    if server is not None:
        if server not in servers:
            _fail(f"no MCP server named {server!r} in config.yaml")
        servers = {server: servers[server]}
    if not servers:
        console.print("No external MCP servers are configured.")
        return
    store = trust_store(ws)
    async with ToolHub({}, servers, store) as hub:
        pending = {(p.server, p.name): p for p in hub.pending}
        for name in servers:
            console.print(f"\n[bold]{escape(name)}[/bold]")
            for tool in sorted(hub.fingerprints(name)):
                waiting = pending.get((name, tool))
                if waiting is None:
                    console.print(f"  [green]approved[/green]  {escape(tool)}")
                    continue
                console.print(f"  [yellow]{waiting.status.value:<8}[/yellow]  {escape(tool)}")
                console.print(f"    [dim]{escape(waiting.description[:300])}[/dim]")
        if not approve or server is None:
            return
        if not pending:
            console.print("\nNothing new to approve.")
            return
        if not assume_yes and not await asyncio.to_thread(
            Confirm.ask, f"Approve these tools from {server}?", console=console, default=False
        ):
            console.print("Not approved.")
            return
        prints = hub.fingerprints(server)
        store.trust(server, prints)
        console.print(f"[green]Approved {len(prints)} tools from {escape(server)}.[/green]")


def _warn_pending(pending: tuple[PendingTool, ...]) -> None:
    if not pending:
        return
    servers = sorted({p.server for p in pending})
    console.print(
        f"[yellow]{len(pending)} external tool(s) are hidden until you approve them "
        f"(new or changed): run 'm3allema mcp trust {servers[0]}'.[/yellow]"
    )


async def _run_task(root: Path, task: str) -> None:
    async with _open(root) as session:
        _warn_pending(session.pending_tools)
        await _stream(session, task)


async def _chat(root: Path, resume: str | None) -> None:
    async with _open(root, resume) as session:
        _warn_pending(session.pending_tools)
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


def _workspace(root: Path) -> Workspace:
    try:
        return Workspace.open(root)
    except WorkspaceError as exc:
        _fail(str(exc))


def _stores(root: Path) -> Stores:
    try:
        return open_stores(Workspace.open(root))
    except WorkspaceError as exc:
        _fail(str(exc))


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coro)
    except (WorkspaceError, ConfigError, ResumeError, GoogleAuthError) as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped. Resume with: m3allema chat --resume[/dim]")


def _ask(question: Question, default: Any) -> Any:
    """Ask one interview question in the terminal."""
    label = escape(question.prompt)
    if question.help:
        console.print(f"[dim]{escape(question.help)}[/dim]")
    if question.kind is Kind.CHOICE:
        return Prompt.ask(label, choices=list(question.options), default=default)
    if question.kind in (Kind.LIST, Kind.MULTI):
        hint = ", ".join(question.options) if question.options else "comma-separated"
        shown = ", ".join(default) if isinstance(default, list) else ""
        raw = Prompt.ask(f"{label} [dim]({escape(hint)})[/dim]", default=shown)
        return [item.strip() for item in raw.split(",") if item.strip()]
    if question.kind is Kind.MONEY:
        return Prompt.ask(label, default=str(default))
    while True:
        value = Prompt.ask(label, default=default or None)
        if value or not question.required:
            return value or ""
        console.print("[red]This one is needed.[/red]")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(1)


def _summary(payload: dict[str, object]) -> str:
    for key in ("task", "answer", "call"):
        if key in payload:
            return escape(str(payload[key])[:100])
    return ""
