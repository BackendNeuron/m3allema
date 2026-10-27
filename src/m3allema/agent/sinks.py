"""Event sinks beyond the database: fan-out and task receipts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from m3allema.agent.interfaces import EventSink
from m3allema.domain.events import (
    AgentEvent,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    TurnCompleted,
)

NOT_RUN_PREFIX = "Not run:"


class FanOutSink:
    """Forwards every event to several sinks, in order."""

    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self._sinks = tuple(sinks)

    def record(self, run_id: str, event: AgentEvent) -> None:
        """Forward ``event`` to every sink."""
        for sink in self._sinks:
            sink.record(run_id, event)


@dataclass
class _RunNotes:
    task: str
    started_at: datetime
    models: list[str] = field(default_factory=list)
    actions: list[ToolCallFinished] = field(default_factory=list)


class ReceiptWriter:
    """Writes a plain-language receipt for every finished run.

    A receipt answers what the owner wants to know afterwards: what was asked,
    what M3allema did, what it touched, what it cost, and what still needs them.

    Args:
        directory: Where receipts are saved (``<workspace>/receipts``).
        on_written: Optional callback with the path of each new receipt.

    """

    def __init__(self, directory: Path, on_written: Callable[[Path], None] | None = None) -> None:
        self._directory = directory
        self._on_written = on_written
        self._runs: dict[str, _RunNotes] = {}

    def record(self, run_id: str, event: AgentEvent) -> None:
        """Collect the run's events and write the receipt when it finishes."""
        if isinstance(event, RunStarted):
            self._runs[run_id] = _RunNotes(task=event.task, started_at=datetime.now(UTC))
            return
        notes = self._runs.get(run_id)
        if notes is None:
            return
        if isinstance(event, TurnCompleted) and event.model and event.model not in notes.models:
            notes.models.append(event.model)
        elif isinstance(event, ToolCallFinished):
            notes.actions.append(event)
        elif isinstance(event, RunFinished):
            del self._runs[run_id]
            path = self._write(event, notes)
            if self._on_written:
                self._on_written(path)

    def _write(self, finished: RunFinished, notes: _RunNotes) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        stamp = notes.started_at.strftime("%Y-%m-%d-%H%M%S")
        path = self._directory / f"{stamp}-{finished.run_id[:8]}.md"
        path.write_text(render_receipt(finished, notes.task, notes.models, notes.actions), "utf-8")
        return path


def render_receipt(
    finished: RunFinished,
    task: str,
    models: Sequence[str],
    actions: Sequence[ToolCallFinished],
) -> str:
    """Render a receipt as markdown."""
    cost = "unknown" if finished.cost_usd is None else f"${finished.cost_usd:.4f}"
    lines = [
        f"# Receipt {finished.run_id[:8]}",
        "",
        f"**Task:** {task}",
        "",
        f"- **Status:** {finished.status}",
        f"- **Model:** {', '.join(models) or 'n/a'}",
        f"- **Steps:** {finished.steps}",
        f"- **Tokens:** {finished.usage.input_tokens:,} in / {finished.usage.output_tokens:,} out",
        f"- **Cost:** {cost}",
        "",
        "## Result",
        "",
        finished.answer or "(no answer)",
    ]

    if actions:
        lines += ["", "## Actions", "", "| # | Tool | Risk | Outcome |", "|---|---|---|---|"]
        for number, action in enumerate(actions, start=1):
            outcome = _outcome(action)
            lines.append(f"| {number} | `{action.call.name}` | {action.risk or '?'} | {outcome} |")

    needs_you = [a for a in actions if a.result.is_error]
    if needs_you:
        lines += ["", "## Needs you", ""]
        lines += [f"- `{a.call.name}`: {_first_line(a.result.content)}" for a in needs_you]

    return "\n".join(lines) + "\n"


def _outcome(action: ToolCallFinished) -> str:
    if not action.result.is_error:
        return f"done ({action.duration_ms} ms)"
    if action.result.content.startswith(NOT_RUN_PREFIX):
        return "not run"
    return "failed"


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:200].replace("|", "/")
