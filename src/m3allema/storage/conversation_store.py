"""Repository for conversations, so a chat can be resumed after M3allema exits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from m3allema.domain.messages import Message, UserMessage
from m3allema.storage.codec import message_from_dict, message_to_dict
from m3allema.storage.database import Database
from m3allema.storage.models import MessageRow


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """One conversation, for listing."""

    id: str
    title: str
    messages: int
    updated_at: datetime


class ConversationStore:
    """Saves every message as it happens and loads whole conversations back.

    Implements the agent's message-log interface.
    """

    def __init__(self, database: Database) -> None:
        self._sessions = database.sessions

    def append(self, conversation_id: str, message: Message) -> None:
        """Save one message at the end of a conversation."""
        with self._sessions.begin() as session:
            seq = session.scalar(
                select(func.coalesce(func.max(MessageRow.seq), 0)).where(
                    MessageRow.conversation_id == conversation_id
                )
            )
            session.add(
                MessageRow(
                    conversation_id=conversation_id,
                    seq=(seq or 0) + 1,
                    data=message_to_dict(message),
                )
            )

    def load(self, conversation_id: str) -> Sequence[Message]:
        """Every message of a conversation, oldest first."""
        with self._sessions() as session:
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.seq)
            )
            return [message_from_dict(row.data) for row in rows]

    def latest_id(self) -> str | None:
        """Id of the most recently active conversation, if any."""
        with self._sessions() as session:
            return session.scalar(
                select(MessageRow.conversation_id).order_by(MessageRow.id.desc()).limit(1)
            )

    def find(self, id_prefix: str) -> Sequence[str]:
        """Conversation ids starting with ``id_prefix`` (at most two, to detect ambiguity)."""
        with self._sessions() as session:
            rows = session.scalars(
                select(MessageRow.conversation_id)
                .where(MessageRow.conversation_id.startswith(id_prefix))
                .distinct()
                .limit(2)
            )
            return list(rows)

    def list_recent(self, limit: int = 20) -> Sequence[ConversationSummary]:
        """Most recently active conversations first, titled by their first request."""
        with self._sessions() as session:
            stats = session.execute(
                select(
                    MessageRow.conversation_id,
                    func.count(MessageRow.id),
                    func.max(MessageRow.created_at),
                    func.max(MessageRow.id).label("last_id"),
                )
                .group_by(MessageRow.conversation_id)
                .order_by(func.max(MessageRow.id).desc())
                .limit(limit)
            ).all()
            summaries: list[ConversationSummary] = []
            for conversation_id, count, updated_at, _ in stats:
                first = session.scalar(
                    select(MessageRow.data)
                    .where(MessageRow.conversation_id == conversation_id)
                    .order_by(MessageRow.seq)
                    .limit(1)
                )
                summaries.append(
                    ConversationSummary(
                        id=conversation_id,
                        title=_title(message_from_dict(first)) if first else "",
                        messages=count,
                        updated_at=updated_at,
                    )
                )
            return summaries


def _title(message: Message) -> str:
    if not isinstance(message, UserMessage):
        return "(conversation)"
    text = message.text
    if text.startswith("<conversation_summary>"):
        return "(continued from a compacted conversation)"
    return text.splitlines()[0][:80] if text else ""
