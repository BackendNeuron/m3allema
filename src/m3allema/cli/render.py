"""Render agent events in the terminal and ask the owner for approvals."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from m3allema.agent.approval_view import describe_call
from m3allema.agent.loop import describe_arguments
from m3allema.agent.permissions import Approver
from m3allema.domain.events import (
    AgentEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
)
from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import Risk, ToolSpec

_RISK_STYLE = {Risk.READ: "dim", Risk.WRITE: "yellow", Risk.EXTERNAL: "bold red"}
_STATUS_STYLE = {"completed": "green", "refused": "yellow", "truncated": "yellow"}


class EventRenderer:
    """Prints a run as it happens: streamed text, tool steps and a summary line."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._mid_line = False

    def render(self, event: AgentEvent) -> None:
        """Print one event."""
        match event:
            case RunStarted(model=model):
                self._console.print(f"[dim]model {escape(model)}[/dim]")
            case TextDelta(text=text):
                self._console.print(escape(text), end="")
                self._mid_line = True
            case TurnCompleted():
                self._end_line()
            case ToolCallStarted(call=call):
                self._end_line()
                arguments = escape(describe_arguments(call.arguments))
                self._console.print(f"[cyan]>[/cyan] {escape(call.name)} [dim]{arguments}[/dim]")
            case ToolCallFinished(result=result, duration_ms=ms):
                mark = "[red]x[/red]" if result.is_error else "[green]ok[/green]"
                first_line = result.content.splitlines()[0][:120] if result.content else ""
                self._console.print(f"  {mark} [dim]{ms} ms  {escape(first_line)}[/dim]")
            case RunFinished(status=status, usage=usage, steps=steps, answer=answer):
                self._end_line()
                if status != "completed":
                    self._console.print(escape(answer))
                style = _STATUS_STYLE.get(status, "red")
                cost = "cost unknown" if event.cost_usd is None else f"${event.cost_usd:.4f}"
                self._console.print(
                    f"[{style}]{status}[/{style}] [dim]{steps} steps, "
                    f"{usage.input_tokens:,} in / {usage.output_tokens:,} out tokens, {cost}[/dim]"
                )

    def _end_line(self) -> None:
        if self._mid_line:
            self._console.print()
            self._mid_line = False


def terminal_approver(console: Console) -> Approver:
    """Build an approver that asks the owner in the terminal."""

    async def approve(call: ToolCall, spec: ToolSpec) -> bool:
        view = describe_call(call, spec)
        style = _RISK_STYLE[spec.risk]
        console.print(
            f"\n[{style}]{spec.risk.value}[/{style}] [bold]{escape(view.title)}[/bold] "
            f"[dim]({escape(call.name)})[/dim]"
        )
        for label, value in view.fields:
            console.print(f"  {escape(label)}: {escape(value)}")
        for warning in view.warnings:
            console.print(f"  [bold red]! {escape(warning)}[/bold red]")
        if view.mentions:
            mentions = escape(" · ".join(view.mentions))
            console.print(f"  [bold yellow]Mentions:[/bold yellow] {mentions}")
        console.print(f"[dim]{escape(view.preview)}[/dim]")
        choices = ["y", "n", "v"] if view.is_long else ["y", "n"]
        question = "Allow?" + (" (v = view the full text)" if view.is_long else "")
        while True:
            answer = await asyncio.to_thread(
                Prompt.ask, question, console=console, choices=choices, default="n"
            )
            if answer != "v":
                return answer == "y"
            console.print(escape(view.full_text))

    return approve
