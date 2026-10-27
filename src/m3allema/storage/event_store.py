"""Repository for runs and their append-only event log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from m3allema.domain.events import AgentEvent, RunFinished, RunStarted
from m3allema.storage.database import Database
from m3allema.storage.models import EventRow, RunRow
from m3allema.storage.serialization import event_kind, event_to_payload

# Streaming text fragments are reconstructable from the completed turn, so
# storing each one would only bloat the log.
_SKIPPED_KINDS = frozenset({"text_delta"})


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A stored run, as returned to interfaces."""

    id: str
    conversation_id: str
    task: str
    model: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    steps: int


@dataclass(frozen=True, slots=True)
class EventRecord:
    """A stored event."""

    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class EventStore:
    """Stores runs and every step taken within them.

    Implements the agent's event-sink interface, so the agent loop can record
    events without knowing anything about databases.
    """

    def __init__(self, database: Database) -> None:
        self._sessions = database.sessions

    def record(self, run_id: str, event: AgentEvent) -> None:
        """Append one event to a run's log, creating or closing the run as needed."""
        kind = event_kind(event)
        if kind in _SKIPPED_KINDS:
            return
        with self._sessions.begin() as session:
            if isinstance(event, RunStarted):
                session.add(
                    RunRow(
                        id=run_id,
                        conversation_id=event.conversation_id,
                        task=event.task,
                        model=event.model,
                    )
                )
            elif isinstance(event, RunFinished):
                self._close_run(session, event)
            seq = session.scalar(
                select(func.coalesce(func.max(EventRow.seq), 0)).where(EventRow.run_id == run_id)
            )
            session.add(
                EventRow(
                    run_id=run_id, seq=(seq or 0) + 1, kind=kind, payload=event_to_payload(event)
                )
            )

    def list_runs(self, limit: int = 20) -> Sequence[RunRecord]:
        """Most recent runs first."""
        with self._sessions() as session:
            rows = session.scalars(select(RunRow).order_by(RunRow.started_at.desc()).limit(limit))
            return [_to_run_record(row) for row in rows]

    def find_runs(self, id_prefix: str) -> Sequence[RunRecord]:
        """Find runs whose id starts with ``id_prefix`` (at most two, to detect ambiguity)."""
        with self._sessions() as session:
            rows = session.scalars(select(RunRow).where(RunRow.id.startswith(id_prefix)).limit(2))
            return [_to_run_record(row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord | None:
        """One run by id, or ``None``."""
        with self._sessions() as session:
            row = session.get(RunRow, run_id)
            return _to_run_record(row) if row else None

    def list_events(self, run_id: str) -> Sequence[EventRecord]:
        """Every stored event of a run, in order. This is what replay reads."""
        with self._sessions() as session:
            rows = session.scalars(
                select(EventRow).where(EventRow.run_id == run_id).order_by(EventRow.seq)
            )
            return [
                EventRecord(seq=r.seq, kind=r.kind, payload=r.payload, created_at=r.created_at)
                for r in rows
            ]

    def spent_since(self, since: datetime) -> float:
        """Total known cost of runs started at or after ``since``, in USD."""
        with self._sessions() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(RunRow.cost_usd), 0.0)).where(
                    RunRow.started_at >= since
                )
            )
            return float(total or 0.0)

    def spent_today(self) -> float:
        """Total known cost of runs started today (UTC), in USD."""
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.spent_since(midnight)

    @staticmethod
    def _close_run(session: Session, event: RunFinished) -> None:
        run = session.get(RunRow, event.run_id)
        if run is None:
            return
        run.status = event.status
        run.finished_at = datetime.now(UTC)
        run.input_tokens = event.usage.input_tokens
        run.output_tokens = event.usage.output_tokens
        run.cost_usd = event.cost_usd
        run.steps = event.steps


def _to_run_record(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        task=row.task,
        model=row.model,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        steps=row.steps,
    )
