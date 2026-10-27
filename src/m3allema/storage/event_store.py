"""Repository for runs and their append-only event log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from m3allema.domain.events import AgentEvent, RunFinished, RunStarted
from m3allema.storage.models import Base, EventRow, RunRow
from m3allema.storage.serialization import event_kind, event_to_payload

# Streaming text fragments are reconstructable from the completed turn, so
# storing each one would only bloat the log.
_SKIPPED_KINDS = frozenset({"text_delta"})


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A stored run, as returned to interfaces."""

    id: str
    task: str
    model: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    input_tokens: int
    output_tokens: int
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

    Args:
        url: SQLAlchemy database URL (SQLite or Postgres).

    """

    def __init__(self, url: str) -> None:
        self._engine: Engine = create_engine(url)
        Base.metadata.create_all(self._engine)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def record(self, run_id: str, event: AgentEvent) -> None:
        """Append one event to a run's log, creating or closing the run as needed."""
        kind = event_kind(event)
        if kind in _SKIPPED_KINDS:
            return
        with self._sessions.begin() as session:
            if isinstance(event, RunStarted):
                session.add(RunRow(id=run_id, task=event.task, model=event.model))
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

    def close(self) -> None:
        """Release database connections."""
        self._engine.dispose()

    @staticmethod
    def _close_run(session: Session, event: RunFinished) -> None:
        run = session.get(RunRow, event.run_id)
        if run is None:
            return
        run.status = event.status
        run.finished_at = datetime.now(UTC)
        run.input_tokens = event.usage.input_tokens
        run.output_tokens = event.usage.output_tokens
        run.steps = event.steps


def _to_run_record(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        task=row.task,
        model=row.model,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        steps=row.steps,
    )
